
import json
import logging
import re
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from django.views.decorators.http import require_GET
from .models import Student, CallingAccount, MpesaPayment
from .mpesa import initiate_stk_push, query_stk_push_status
from .serializers import ParentContactSerializer

logger = logging.getLogger(__name__)


# STUDENT: Initiate an M-Pesa payment for calling credit
@login_required
def initiate_calling_credit_payment(request):
    """
    Start an M-Pesa STK Push for a student's calling account.

    An accepted STK Push request does not prove that payment
    succeeded. Credit is added only after independent verification.
    """
    if not hasattr(request.user, "student_profile"):
        return redirect("student-login")

    student = request.user.student_profile

    if not student.is_active:
        messages.error(request, "Your student account is inactive.")
        return redirect("student-login")

    account = CallingAccount.objects.filter(
        student=student,
        is_active=True,
    ).first()

    if account is None:
        messages.error(request, "No active calling account is available.")
        return redirect("student-calling")

    if request.method != "POST":
        return render(request, "students/mpesa_payment.html")

    raw_phone = request.POST.get("phone_number", "").strip()
    raw_amount = request.POST.get("amount", "").strip()

    # Normalize Kenyan mobile numbers to 254XXXXXXXXX.
    phone = re.sub(r"\D", "", raw_phone)

    if len(phone) == 10 and phone.startswith(("07", "01")):
        phone = "254" + phone[1:]
    elif len(phone) == 9 and phone.startswith(("7", "1")):
        phone = "254" + phone
    elif len(phone) == 12 and phone.startswith("254"):
        pass
    else:
        messages.error(request, "Enter a valid Kenyan mobile number.")
        return render(request, "students/mpesa_payment.html")

    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")

    if (
        not amount.is_finite()
        or amount <= 0
        or amount != amount.to_integral_value()
        or amount > Decimal("150000")
    ):
        messages.error(
            request,
            "Enter a whole-number amount between KSh 1 and KSh 150,000.",
        )
        return render(request, "students/mpesa_payment.html")

    # Create a pending payment before contacting Daraja.
    payment = MpesaPayment.objects.create(
        calling_account=account,
        amount=amount,
        phone_number=phone,
        status=MpesaPayment.Status.PENDING,
    )

    try:
        result = initiate_stk_push(
            phone_number=phone,
            amount=int(amount),
            account_reference=str(payment.payment_reference),
        )

        if not isinstance(result, dict):
            raise ValueError("Unexpected Daraja response.")

    except Exception:
        logger.exception(
            "M-Pesa STK initiation failed for payment %s.",
            payment.payment_reference,
        )

        payment.result_description = (
            "Payment initiation could not be confirmed. "
            "Check the payment status before retrying."
        )
        payment.save(update_fields=["result_description", "updated_at"])

        messages.error(
            request,
            "We could not confirm the payment request. "
            "Check its status before trying again.",
        )
        return render(
            request,
            "students/mpesa_payment.html",
            {"payment": payment},
        )

    response_code = str(result.get("ResponseCode", ""))
    checkout_id = result.get("CheckoutRequestID", "")
    merchant_id = result.get("MerchantRequestID", "")

    payment.checkout_request_id = (
        checkout_id if isinstance(checkout_id, str) else ""
    )
    payment.merchant_request_id = (
        merchant_id if isinstance(merchant_id, str) else ""
    )
    payment.result_description = str(
        result.get("CustomerMessage")
        or result.get("ResponseDescription")
        or "STK Push request submitted."
    )[:255]

    if response_code and response_code != "0":
        payment.status = MpesaPayment.Status.FAILED
    elif response_code == "0" and payment.checkout_request_id:
        # Accepted request only; payment remains pending.
        payment.status = MpesaPayment.Status.PENDING

    payment.save(
        update_fields=[
            "checkout_request_id",
            "merchant_request_id",
            "result_description",
            "status",
            "updated_at",
        ]
    )

    if response_code == "0" and payment.checkout_request_id:
        messages.success(
            request,
            "STK Push sent. Complete the prompt on your phone. "
            "Your balance updates after payment verification.",
        )

    elif response_code and response_code != "0":
        messages.error(
            request,
            "Daraja rejected the payment request. "
            "No calling credit has been added.",
        )

    else:
        messages.warning(
            request,
            "Daraja returned an incomplete response. "
            "Your payment remains pending and no credit has been added. "
            "Do not submit another request yet. "
            "If a checkout reference is available, check its status; "
            "otherwise contact your school administrator.",
        )

    return render(
        request,
        "students/mpesa_payment.html",
        {"payment": payment},
    )


# ADMIN: Retrieve a student's authorized parent contacts
@api_view(["GET"])
@permission_classes([IsAdminUser])
def student_parent_contacts(request, admission_number):
    student = Student.objects.filter(
        admission_number=admission_number,
        is_active=True,
    ).first()

    if student is None:
        return Response(
            {"error": "Student not found or inactive."},
            status=status.HTTP_404_NOT_FOUND,
        )

    contacts = student.parent_contacts.filter(is_authorized=True)

    serializer = ParentContactSerializer(contacts, many=True)
    return Response(serializer.data)


# STUDENT: Retrieve own authorized parent contacts
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_parent_contacts(request):
    if not hasattr(request.user, "student_profile"):
        return Response(
            {"error": "Student account required."},
            status=status.HTTP_403_FORBIDDEN,
        )

    student = request.user.student_profile

    if not student.is_active:
        return Response(
            {"error": "Student account is inactive."},
            status=status.HTTP_403_FORBIDDEN,
        )

    contacts = student.parent_contacts.filter(is_authorized=True)
    serializer = ParentContactSerializer(contacts, many=True)

    return Response(serializer.data)


# STUDENT: Verify whether a call request is allowed
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def check_call_readiness(request):
    if not hasattr(request.user, "student_profile"):
        return Response(
            {"error": "Student account required."},
            status=status.HTTP_403_FORBIDDEN,
        )

    student = request.user.student_profile

    if not student.is_active:
        return Response(
            {"error": "Student account is inactive."},
            status=status.HTTP_403_FORBIDDEN,
        )

    contact_id = request.data.get("contact_id")

    if not contact_id:
        return Response(
            {"error": "Contact ID is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    contact = student.parent_contacts.filter(
        id=contact_id,
        is_authorized=True,
    ).first()

    if contact is None:
        return Response(
            {"error": "Contact not found or not authorized."},
            status=status.HTTP_404_NOT_FOUND,
        )

    account = CallingAccount.objects.filter(
        student=student,
        is_active=True,
    ).first()

    if account is None:
        return Response(
            {"error": "No active calling account found."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if account.balance <= 0:
        return Response(
            {"error": "Insufficient calling credit."},
            status=status.HTTP_403_FORBIDDEN,
        )

    return Response({
        "ready": True,
        "message": "Call request passed verification.",
        "contact_name": contact.full_name,
        "available_balance": str(account.balance),
    })


# TELEPHONE BOOTH: Display lockscreen
def booth_lockscreen(request):
    return render(request, "students/lockscreen.html")


# STUDENT: Display homescreen
@login_required
def student_homescreen(request):
    if not hasattr(request.user, "student_profile"):
        return redirect("student-login")

    student = request.user.student_profile

    if not student.is_active:
        return redirect("student-login")

    return render(
        request,
        "students/homescreen.html",
        {"student": student},
    )


# STUDENT: Display calling interface
@login_required
def student_calling(request):
    if not hasattr(request.user, "student_profile"):
        return redirect("student-login")

    student = request.user.student_profile

    if not student.is_active:
        return redirect("student-login")

    return render(
        request,
        "students/calling.html",
        {"student": student},
    )


# STUDENT: Check M-Pesa payment status
@login_required
@require_GET
def check_mpesa_payment_status(request, payment_reference):
    """
    Query Daraja for a payment belonging to the logged-in student.

    This endpoint reports the provider's response but does not change
    payment status or add calling credit.
    """
    if not hasattr(request.user, "student_profile"):
        return JsonResponse(
            {"error": "Student account required."},
            status=403,
        )

    student = request.user.student_profile

    payment = MpesaPayment.objects.filter(
        payment_reference=payment_reference,
        calling_account__student=student,
    ).first()

    if payment is None:
        return JsonResponse(
            {"error": "Payment not found."},
            status=404,
        )

    if payment.status != MpesaPayment.Status.PENDING:
        return JsonResponse({
            "payment_reference": str(payment.payment_reference),
            "payment_status": payment.status,
            "message": "This payment is no longer pending.",
            "credit_applied": payment.status == MpesaPayment.Status.SUCCESS,
        })

    if not payment.checkout_request_id:
        return JsonResponse({
            "payment_reference": str(payment.payment_reference),
            "payment_status": payment.status,
            "message": (
                "No checkout request ID is available yet. "
                "Check the payment again later."
            ),
            "credit_applied": False,
        }, status=409)

    try:
        result = query_stk_push_status(
            payment.checkout_request_id
        )
    except (RuntimeError, ValueError):
        logger.warning(
            "Could not query Daraja for payment %s.",
            payment.payment_reference,
        )
        return JsonResponse({
            "payment_reference": str(payment.payment_reference),
            "payment_status": payment.status,
            "message": "Payment status could not be retrieved. Try again later.",
            "credit_applied": False,
        }, status=502)

    if not isinstance(result, dict):
        return JsonResponse({
            "payment_reference": str(payment.payment_reference),
            "payment_status": payment.status,
            "message": "Daraja returned an unexpected response.",
            "credit_applied": False,
        }, status=502)

    # Do not confuse acceptance of a query request with a completed payment.
    provider_result_code = result.get("ResultCode")
    provider_description = result.get("ResultDesc")

    if provider_result_code is None:
        provider_result_code = result.get("ResponseCode")

    if provider_result_code is None:
        message = (
            "Daraja returned a response, but the payment outcome "
            "is not yet confirmed."
        )
    elif str(provider_result_code) == "0":
        message = (
            "Daraja returned a successful result code. "
            "Payment details must still be verified before crediting."
        )
    else:
        message = (
            "Daraja returned a non-success result. "
            "The payment outcome requires interpretation."
        )

    return JsonResponse({
        "payment_reference": str(payment.payment_reference),
        "payment_status": payment.status,
        "provider_result_code": str(provider_result_code)
        if provider_result_code is not None else None,
        "provider_description": str(provider_description)[:255]
        if provider_description else "",
        "message": message,
        "credit_applied": False,
    })


# M-PESA: Receive STK callback without trusting it to credit an account
@csrf_exempt
@require_POST
def mpesa_stk_callback(request):
    """
    Receive a Daraja STK callback.

    This endpoint does not mark payments successful or credit balances.
    """
    if len(request.body) > 64 * 1024:
        return JsonResponse(
            {"ResultCode": 1, "ResultDesc": "Payload too large"},
            status=413,
        )

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"ResultCode": 1, "ResultDesc": "Invalid JSON"},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {"ResultCode": 1, "ResultDesc": "Invalid payload"},
            status=400,
        )

    body = payload.get("Body")
    callback = body.get("stkCallback") if isinstance(body, dict) else None

    if not isinstance(callback, dict):
        return JsonResponse(
            {"ResultCode": 1, "ResultDesc": "Invalid callback structure"},
            status=400,
        )

    checkout_id = callback.get("CheckoutRequestID")

    if not isinstance(checkout_id, str) or not checkout_id.strip():
        return JsonResponse(
            {"ResultCode": 1, "ResultDesc": "Missing checkout ID"},
            status=400,
        )

    payment_exists = MpesaPayment.objects.filter(
        checkout_request_id=checkout_id.strip()
    ).exists()

    if not payment_exists:
        logger.warning("Received callback for an unknown checkout ID.")
        return JsonResponse(
            {"ResultCode": 0, "ResultDesc": "Callback received"}
        )

    logger.info("Received an unverified M-Pesa callback for a known checkout.")

    return JsonResponse(
        {"ResultCode": 0, "ResultDesc": "Callback received"}
    )
