
from rest_framework.test import APIClient
from django.urls import reverse
from unittest.mock import patch
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import (
    Student,
    ParentContact,
    CallingAccount,
    CreditTransaction,
    CallRecord,
)

from .services import (
    add_calling_credit,
    deduct_call_cost,
    record_completed_call,
)


class CallingCreditServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_user(
            username="credit_test_admin",
            password="temporary-test-password",
            is_staff=True,
        )

        self.student = Student.objects.create(
            admission_number="CREDITTEST001",
            first_name="Test",
            last_name="Student",
            class_name="Form 3",
            guardian_name="Test Guardian",
            guardian_phone="0700000000",
        )

        self.account = CallingAccount.objects.create(
            student=self.student,
            balance=Decimal("0.00"),
            is_active=True,
        )

    def test_valid_credit_updates_balance_and_records_transaction(self):
        account = add_calling_credit(
            account_id=self.account.pk,
            amount="100.00",
            administrator=self.admin,
            description="Automated test credit",
            reference="TEST-CREDIT-001",
        )

        account.refresh_from_db()

        self.assertEqual(account.balance, Decimal("100.00"))
        self.assertEqual(
            CreditTransaction.objects.filter(
                account=account
            ).count(),
            1,
        )

        entry = CreditTransaction.objects.get(account=account)
        self.assertEqual(entry.amount, Decimal("100.00"))
        self.assertEqual(entry.balance_after, Decimal("100.00"))
        self.assertEqual(entry.recorded_by, self.admin)

    def test_zero_credit_is_rejected(self):
        with self.assertRaises(ValidationError):
            add_calling_credit(
                account_id=self.account.pk,
                amount="0.00",
                administrator=self.admin,
                description="Invalid zero credit",
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_negative_credit_is_rejected(self):
        with self.assertRaises(ValidationError):
            add_calling_credit(
                account_id=self.account.pk,
                amount="-10.00",
                administrator=self.admin,
                description="Invalid negative credit",
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_inactive_account_is_rejected(self):
        self.account.is_active = False
        self.account.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            add_calling_credit(
                account_id=self.account.pk,
                amount="50.00",
                administrator=self.admin,
                description="Credit to inactive account",
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)



from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Student, CallingAccount, CreditTransaction
from .services import deduct_call_cost


class CallDeductionTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(
            admission_number="CALLTEST01",
            first_name="Test",
            last_name="Student",
            class_name="Form 3",
            guardian_name="Test Guardian",
            guardian_phone="0700000000",
        )

        self.account = CallingAccount.objects.create(
            student=self.student,
            balance=Decimal("10.00"),
        )

    def test_successful_call_deducts_and_records_cost(self):
        account = deduct_call_cost(
            account_id=self.account.pk,
            amount="2.50",
            description="Automated call test",
            reference="CALL-TEST-001",
        )

        self.account.refresh_from_db()

        self.assertEqual(account.balance, Decimal("7.50"))
        self.assertEqual(self.account.balance, Decimal("7.50"))

        transaction_record = CreditTransaction.objects.get(
            reference="CALL-TEST-001"
        )

        self.assertEqual(
            transaction_record.transaction_type,
            CreditTransaction.TransactionType.CALL,
        )
        self.assertEqual(
            transaction_record.amount,
            Decimal("2.50"),
        )
        self.assertEqual(
            transaction_record.balance_after,
            Decimal("7.50"),
        )

    def test_insufficient_credit_is_rejected(self):
        with self.assertRaises(ValidationError):
            deduct_call_cost(
                account_id=self.account.pk,
                amount="15.00",
                description="Insufficient credit test",
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("10.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_zero_call_cost_is_rejected(self):
        with self.assertRaises(ValidationError):
            deduct_call_cost(
                account_id=self.account.pk,
                amount="0.00",
                description="Zero cost test",
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("10.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)



class RecordCompletedCallTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(
            admission_number="TEST002",
            first_name="Brian",
            last_name="Otieno",
            class_name="Form 3",
            guardian_name="Grace Otieno",
            guardian_phone="0711111111",
            is_active=True,
        )

        self.contact = ParentContact.objects.create(
            student=self.student,
            full_name="Grace Otieno",
            relationship="Mother",
            phone_number="0711111111",
            is_authorized=True,
        )

        self.account = CallingAccount.objects.create(
            student=self.student,
            balance=Decimal("100.00"),
            is_active=True,
        )

        self.call_reference = uuid.uuid4()

    def test_completed_call_deducts_credit_and_creates_record(self):
        call = record_completed_call(
            account_id=self.account.id,
            parent_contact_id=self.contact.id,
            amount=Decimal("10.00"),
            duration_seconds=120,
            started_at=datetime.now(timezone.utc),
            call_reference=self.call_reference,
            booth_reference="BOOTH-001",
        )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("90.00"))
        self.assertEqual(call.cost, Decimal("10.00"))
        self.assertEqual(call.duration_seconds, 120)
        self.assertEqual(call.status, CallRecord.CallStatus.COMPLETED)
        self.assertEqual(call.student, self.student)
        self.assertEqual(call.parent_contact, self.contact)
        self.assertIsNotNone(call.credit_transaction)
        self.assertEqual(CreditTransaction.objects.count(), 1)

    def test_unauthorized_contact_does_not_charge_account(self):
        self.contact.is_authorized = False
        self.contact.save()

        with self.assertRaises(ValidationError):
            record_completed_call(
                account_id=self.account.id,
                parent_contact_id=self.contact.id,
                amount=Decimal("10.00"),
                duration_seconds=120,
                started_at=datetime.now(timezone.utc),
                call_reference=self.call_reference,
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)
        self.assertEqual(CallRecord.objects.count(), 0)

    def test_duplicate_call_reference_does_not_charge_twice(self):
        record_completed_call(
            account_id=self.account.id,
            parent_contact_id=self.contact.id,
            amount=Decimal("10.00"),
            duration_seconds=120,
            started_at=datetime.now(timezone.utc),
            call_reference=self.call_reference,
        )

        with self.assertRaises(ValidationError):
            record_completed_call(
                account_id=self.account.id,
                parent_contact_id=self.contact.id,
                amount=Decimal("10.00"),
                duration_seconds=120,
                started_at=datetime.now(timezone.utc),
                call_reference=self.call_reference,
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("90.00"))
        self.assertEqual(CreditTransaction.objects.count(), 1)
        self.assertEqual(CallRecord.objects.count(), 1)
        
    @patch("students.services.CallRecord.objects.create")
    def test_failed_call_record_creation_rolls_back_credit(self, mock_create):
        mock_create.side_effect = RuntimeError(
            "Simulated call-record creation failure"
        )

        with self.assertRaises(RuntimeError):
            record_completed_call(
                account_id=self.account.id,
                parent_contact_id=self.contact.id,
                amount=Decimal("10.00"),
                duration_seconds=120,
                started_at=datetime.now(timezone.utc),
                call_reference=self.call_reference,
                booth_reference="BOOTH-001",
            )

        self.account.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)
        self.assertEqual(CallRecord.objects.count(), 0)



class ParentContactsPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.staff_user = User.objects.create_user(
            username="api_staff_test",
            password="TestOnly-Password-123!",
            is_staff=True,
        )

        self.student_user = User.objects.create_user(
            username="api_student_test",
            password="TestOnly-Password-456!",
            is_staff=False,
        )

        self.student = Student.objects.create(
            admission_number="API001",
            first_name="Test",
            last_name="Student",
            class_name="Form 3",
            guardian_name="Test Guardian",
            guardian_phone="0700000000",
            is_active=True,
        )

        ParentContact.objects.create(
            student=self.student,
            full_name="Test Parent",
            relationship="Mother",
            phone_number="0711111111",
            is_authorized=True,
        )

        self.url = reverse(
            "student-parent-contacts",
            kwargs={"admission_number": "API001"},
        )

        self.client = APIClient()

    def test_staff_can_access_parent_contacts(self):
        self.client.force_authenticate(
            user=self.staff_user
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["full_name"],
            "Test Parent",
        )

    def test_non_staff_user_is_denied(self):
        self.client.force_authenticate(
            user=self.student_user
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_is_denied(self):
        response = self.client.get(self.url)

        self.assertIn(response.status_code, [401, 403])

