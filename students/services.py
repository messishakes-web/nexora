
from decimal import Decimal, InvalidOperation

import uuid
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Value
from django.db.models.functions import Coalesce

from .models import (
    CallingAccount,
    CreditTransaction,
    CallRecord,
    Student,
    ParentContact,
)


CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def add_calling_credit(
    *,
    account_id,
    amount,
    administrator,
    description,
    reference="",
):
    """
    Add credit to a calling account and record the transaction
    as one atomic database operation.
    """
    if not administrator or not administrator.is_authenticated:
        raise ValidationError(
            "An authenticated administrator is required."
        )

    if not administrator.is_staff:
        raise ValidationError(
            "Only staff administrators can add calling credit."
        )

    try:
        credit_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Enter a valid credit amount.")

    if not credit_amount.is_finite():
        raise ValidationError("The credit amount must be finite.")

    if credit_amount <= ZERO:
        raise ValidationError(
            "Credit must be greater than KSh 0.00."
        )

    if credit_amount != credit_amount.quantize(CENT):
        raise ValidationError(
            "Credit must have no more than two decimal places."
        )

    if not description or not description.strip():
        raise ValidationError(
            "Provide a description for the credit addition."
        )

    with transaction.atomic():
        updated = CallingAccount.objects.filter(
            pk=account_id,
            is_active=True,
        ).update(
            balance=Coalesce(
                F("balance"),
                Value(ZERO),
            ) + credit_amount
        )

        if updated != 1:
            raise ValidationError(
                "The calling account does not exist or is inactive."
            )

        account = CallingAccount.objects.get(pk=account_id)

        CreditTransaction.objects.create(
            account=account,
            transaction_type=CreditTransaction.TransactionType.CREDIT,
            amount=credit_amount,
            balance_after=account.balance,
            description=description.strip(),
            reference=reference.strip(),
            recorded_by=administrator,
        )

    return account



def deduct_call_cost(
    *,
    account_id,
    amount,
    description,
    reference="",
):
    """
    Deduct the cost of a completed call and record
    the transaction as one atomic database operation.
    """
    try:
        call_cost = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Enter a valid call cost.")

    if not call_cost.is_finite():
        raise ValidationError("The call cost must be finite.")

    if call_cost <= ZERO:
        raise ValidationError(
            "The call cost must be greater than KSh 0.00."
        )

    if call_cost != call_cost.quantize(CENT):
        raise ValidationError(
            "The call cost must have no more than two decimal places."
        )

    if not description or not description.strip():
        raise ValidationError(
            "Provide a description for the call."
        )

    with transaction.atomic():
        updated = CallingAccount.objects.filter(
            pk=account_id,
            is_active=True,
            student__is_active=True,
            balance__gte=call_cost,
        ).update(
            balance=F("balance") - call_cost
        )

        if updated != 1:
            account_exists = CallingAccount.objects.filter(
                pk=account_id,
                is_active=True,
                student__is_active=True,
            ).exists()

            if not account_exists:
                raise ValidationError(
                    "The calling account or student is inactive, "
                    "or the account does not exist."
                )

            raise ValidationError(
                "Insufficient calling credit for this call."
            )

        account = CallingAccount.objects.get(pk=account_id)

        CreditTransaction.objects.create(
            account=account,
            transaction_type=CreditTransaction.TransactionType.CALL,
            amount=call_cost,
            balance_after=account.balance,
            description=description.strip(),
            reference=reference.strip(),
            recorded_by=None,
        )

    return account



def record_completed_call(
    *,
    account_id,
    parent_contact_id,
    amount,
    duration_seconds,
    started_at,
    call_reference,
    booth_reference="",
):
    """
    Record a completed call and deduct its cost
    as one atomic database operation.
    """

    # Validate the call reference.
    try:
        call_reference = uuid.UUID(str(call_reference))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Enter a valid call reference.")

    # Reject duplicate calls before charging.
    if CallRecord.objects.filter(
        call_reference=call_reference
    ).exists():
        raise ValidationError(
            "This call has already been recorded."
        )

    if not isinstance(duration_seconds, int) or isinstance(
        duration_seconds, bool
    ) or duration_seconds <= 0:
        raise ValidationError(
            "Call duration must be a positive whole number."
        )

    with transaction.atomic():
        account = CallingAccount.objects.filter(
            pk=account_id,
            is_active=True,
            student__is_active=True,
        ).first()

        if account is None:
            raise ValidationError(
                "The calling account is missing or inactive."
            )

        contact = ParentContact.objects.filter(
            pk=parent_contact_id,
            student_id=account.student_id,
            is_authorized=True,
        ).first()

        if contact is None:
            raise ValidationError(
                "The contact is not authorized for this student."
            )

        # Recheck inside the transaction.
        if CallRecord.objects.filter(
            call_reference=call_reference
        ).exists():
            raise ValidationError(
                "This call has already been recorded."
            )

        # Deduct credit and record the ledger entry.
        account = deduct_call_cost(
            account_id=account_id,
            amount=amount,
            description="Completed telephone call",
            reference=str(call_reference),
        )

        # Retrieve the transaction created by the deduction.
        credit_transaction = CreditTransaction.objects.get(
            account=account,
            reference=str(call_reference),
            transaction_type=CreditTransaction.TransactionType.CALL,
        )

        # Create the call record linked to that transaction.
        call_record = CallRecord.objects.create(
            student=account.student,
            parent_contact=contact,
            booth_reference=booth_reference,
            call_reference=call_reference,
            started_at=started_at,
            duration_seconds=duration_seconds,
            cost=credit_transaction.amount,
            status=CallRecord.CallStatus.COMPLETED,
            credit_transaction=credit_transaction,
        )

        return call_record



from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from .models import (
    CallingAccount,
    CreditTransaction,
    MpesaPayment,
)


def apply_verified_mpesa_payment(
    *,
    payment_id,
    receipt,
    verified_amount,
):
    """
    Apply calling credit for an independently verified M-Pesa payment.

    Call only after server-side provider verification succeeds.
    A repeated call for an already successful payment is harmless.
    """

    receipt = (receipt or "").strip()

    if not receipt:
        raise ValidationError(
            "A verified M-Pesa receipt is required."
        )

    try:
        amount = Decimal(str(verified_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(
            "The verified payment amount is invalid."
        )

    if not amount.is_finite() or amount <= Decimal("0.00"):
        raise ValidationError(
            "The verified payment amount must be positive."
        )

    if amount != amount.quantize(Decimal("0.01")):
        raise ValidationError(
            "The verified amount must have no more than "
            "two decimal places."
        )

    with transaction.atomic():
        payment = (
            MpesaPayment.objects
            .select_for_update()
            .get(pk=payment_id)
        )

        # Repeated processing must not add credit again.
        if payment.status == MpesaPayment.Status.SUCCESS:
            if payment.provider_receipt == receipt:
                return payment

            raise ValidationError(
                "This payment was already completed with "
                "a different receipt."
            )

        if payment.status != MpesaPayment.Status.PENDING:
            raise ValidationError(
                "Only pending payments can be credited."
            )

        if payment.amount != amount:
            raise ValidationError(
                "The verified amount does not match "
                "the recorded payment amount."
            )

        account = (
            CallingAccount.objects
            .select_for_update()
            .get(pk=payment.calling_account_id)
        )

        if not account.is_active:
            raise ValidationError(
                "The calling account is inactive."
            )

        if MpesaPayment.objects.filter(
            provider_receipt=receipt
        ).exclude(pk=payment.pk).exists():
            raise ValidationError(
                "This M-Pesa receipt is already assigned "
                "to another payment."
            )

        # Increase the balance within the same transaction.
        updated = CallingAccount.objects.filter(
            pk=account.pk,
            is_active=True,
        ).update(
            balance=F("balance") + amount
        )

        if updated != 1:
            raise ValidationError(
                "The calling account could not be credited."
            )

        account.refresh_from_db()

        CreditTransaction.objects.create(
            account=account,
            transaction_type=(
                CreditTransaction.TransactionType.CREDIT
            ),
            amount=amount,
            balance_after=account.balance,
            description="Verified M-Pesa calling credit",
            reference=receipt,
            recorded_by=None,
        )

        payment.status = MpesaPayment.Status.SUCCESS
        payment.provider_receipt = receipt
        payment.result_description = (
            "Payment independently verified and credited."
        )
        payment.save(
            update_fields=[
                "status",
                "provider_receipt",
                "result_description",
                "updated_at",
            ]
        )

        return payment
