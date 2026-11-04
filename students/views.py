
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import MpesaPayment

logger = logging.getLogger(__name__)

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.contrib import messages

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import Student, CallingAccount
from .serializers import ParentContactSerializer


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

    contacts = student.parent_contacts.filter(
        is_authorized=True
    )

    serializer = ParentContactSerializer(
        contacts,
        many=True,
    )

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

    contacts = student.parent_contacts.filter(
        is_authorized=True
    )

    serializer = ParentContactSerializer(
        contacts,
        many=True,
    )

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


# STUDENT: Login using admission number and PIN
def student_login(request):
    if request.method == "POST":
        admission_number = request.POST.get(
            "admission_number", ""
        ).strip()

        pin = request.POST.get("pin", "").strip()

        user = authenticate(
            request,
            username=admission_number,
            password=pin,
        )

        if user is not None and hasattr(
            user, "student_profile"
        ):
            student = user.student_profile

            if student.is_active:
                login(request, user)
                return redirect("student-homescreen")

        messages.error(
            request,
            "Invalid admission number or PIN."
        )

    return render(request, "students/login.html")


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


@csrf_exempt
@require_POST
def mpesa_stk_callback(request):
    """
    Receive a Daraja STK callback.

    This endpoint does NOT credit an account or mark a payment
    successful. The callback is treated as unverified input.
    """
    # Reject unusually large callback bodies.
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

    callback = (
        payload.get("Body", {}).get("stkCallback")
        if isinstance(payload, dict)
        and isinstance(payload.get("Body"), dict)
        else None
    )

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

    checkout_id = checkout_id.strip()

    # Correlate the callback with a payment Nexora initiated.
    payment_exists = MpesaPayment.objects.filter(
        checkout_request_id=checkout_id
    ).exists()

    if not payment_exists:
        # Do not reveal internal payment records to the caller.
        logger.warning("Received callback for an unknown checkout ID.")
        return JsonResponse(
            {"ResultCode": 0, "ResultDesc": "Callback received"}
        )

    # Do not trust ResultCode, receipt, amount, or phone number yet.
    # A later verification step must independently confirm the payment.
    logger.info("Received an unverified M-Pesa callback for a known checkout.")

    return JsonResponse(
        {"ResultCode": 0, "ResultDesc": "Callback received"}
    )