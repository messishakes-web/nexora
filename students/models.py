
from django.db import models
from django.conf import settings
import uuid


class Student(models.Model):

    admission_number = models.CharField(
        max_length=30,
        unique=True
    )

    first_name = models.CharField(max_length=100)

    last_name = models.CharField(max_length=100)

    class_name = models.CharField(max_length=50)

    guardian_name = models.CharField(max_length=150)

    guardian_phone = models.CharField(max_length=20)

    is_active = models.BooleanField(default=True)

    date_registered = models.DateTimeField(auto_now_add=True)

    user = models.OneToOneField(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="student_profile",
    )

    def __str__(self):
        return f"{self.admission_number} - {self.first_name} {self.last_name}"
        


class ParentContact(models.Model):
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name='parent_contacts'
    )
    full_name = models.CharField(max_length=150)
    relationship = models.CharField(max_length=50)
    phone_number = models.CharField(max_length=20)
    is_authorized = models.BooleanField(default=True)
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name} - {self.student.admission_number}"



from decimal import Decimal
from django.conf import settings
from django.db import models


class CallingAccount(models.Model):
    student = models.OneToOneField(
        'Student',
        on_delete=models.PROTECT,
        related_name='calling_account',
    )
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    is_active = models.BooleanField(default=True)
    date_created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (
            f"{self.student.admission_number} "
            f"- KSh {self.balance}"
        )


class CreditTransaction(models.Model):
    class TransactionType(models.TextChoices):
        CREDIT = 'CREDIT', 'Credit addition'
        CALL = 'CALL', 'Call deduction'
        ADJUSTMENT = 'ADJUSTMENT', 'Authorised adjustment'

    account = models.ForeignKey(
        CallingAccount,
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    balance_after = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    description = models.CharField(
        max_length=255,
        blank=True,
    )
    reference = models.CharField(
        max_length=100,
        blank=True,
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='nexora_credit_transactions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (
            f"{self.get_transaction_type_display()} "
            f"- KSh {self.amount}"
        )



class CallRecord(models.Model):
    class CallStatus(models.TextChoices):
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        UNANSWERED = 'UNANSWERED', 'Unanswered'
        CANCELLED = 'CANCELLED', 'Cancelled'

    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name='call_records',
    )
    parent_contact = models.ForeignKey(
        ParentContact,
        on_delete=models.PROTECT,
        related_name='call_records',
    )
    booth_reference = models.CharField(
        max_length=50,
        blank=True,
    )
    call_reference = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        null=True,
        )
    started_at = models.DateTimeField()
    duration_seconds = models.PositiveIntegerField(default=0)
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    status = models.CharField(
        max_length=20,
        choices=CallStatus.choices,
        default=CallStatus.COMPLETED,
    )
    credit_transaction = models.OneToOneField(
        CreditTransaction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='call_record',
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return (
            f"{self.student.admission_number} - "
            f"{self.get_status_display()} - "
            f"{self.started_at}"
        )



class MpesaPayment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCESS = "SUCCESS", "Successful"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    payment_reference = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    calling_account = models.ForeignKey(
        CallingAccount,
        on_delete=models.PROTECT,
        related_name="mpesa_payments",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    phone_number = models.CharField(max_length=20)

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    merchant_request_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    checkout_request_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
    )

    provider_receipt = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True,
    )

    result_description = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"M-Pesa {self.payment_reference} - "
            f"{self.status}"
        )
