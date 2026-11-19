import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import (
    Student,
    ParentContact,
    CallingAccount,
    CreditTransaction,
    CallRecord,
    MpesaPayment,
)

from .services import (
    add_calling_credit,
    deduct_call_cost,
    record_completed_call,
    apply_verified_mpesa_payment,
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
            CreditTransaction.objects.filter(account=account).count(),
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
        self.client.force_authenticate(user=self.staff_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["full_name"],
            "Test Parent",
        )

    def test_non_staff_user_is_denied(self):
        self.client.force_authenticate(user=self.student_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_is_denied(self):
        response = self.client.get(self.url)

        self.assertIn(response.status_code, [401, 403])


class VerifiedMpesaPaymentTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="mpesa_verifier_test",
            password="temporary-test-password",
            is_staff=True,
        )

        self.student = Student.objects.create(
            admission_number="MPESATEST001",
            first_name="M-Pesa",
            last_name="Tester",
            class_name="Form 3",
            guardian_name="Test Guardian",
            guardian_phone="0700000000",
        )

        self.account = CallingAccount.objects.create(
            student=self.student,
            balance=Decimal("0.00"),
            is_active=True,
        )

        self.payment = MpesaPayment.objects.create(
            calling_account=self.account,
            amount=Decimal("100.00"),
            phone_number="254700000000",
        )

    def test_verified_payment_adds_credit_once(self):
        apply_verified_mpesa_payment(
            payment_id=self.payment.pk,
            administrator=self.admin,
            receipt="TESTRECEIPT001",
            verified_amount="100.00",
        )

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.SUCCESS,
        )
        self.assertEqual(
            self.payment.provider_receipt,
            "TESTRECEIPT001",
        )
        self.assertEqual(
            CreditTransaction.objects.filter(
                account=self.account,
            ).count(),
            1,
        )

    def test_reprocessing_same_payment_does_not_add_credit_twice(self):
        for _ in range(2):
            apply_verified_mpesa_payment(
                payment_id=self.payment.pk,
                administrator=self.admin,
                receipt="TESTRECEIPT002",
                verified_amount="100.00",
            )

        self.account.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertEqual(
            CreditTransaction.objects.filter(
                account=self.account,
            ).count(),
            1,
        )

    def test_incorrect_verified_amount_is_rejected(self):
        with self.assertRaises(ValidationError):
            apply_verified_mpesa_payment(
                payment_id=self.payment.pk,
                administrator=self.admin,
                receipt="TESTRECEIPT003",
                verified_amount="50.00",
            )

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_missing_receipt_is_rejected(self):
        with self.assertRaises(ValidationError):
            apply_verified_mpesa_payment(
                payment_id=self.payment.pk,
                administrator=self.admin,
                receipt="",
                verified_amount="100.00",
            )

        self.account.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_receipt_cannot_credit_two_payments(self):
        another_payment = MpesaPayment.objects.create(
            calling_account=self.account,
            amount=Decimal("100.00"),
            phone_number="254711111111",
        )

        apply_verified_mpesa_payment(
            payment_id=self.payment.pk,
            administrator=self.admin,
            receipt="TESTRECEIPT004",
            verified_amount="100.00",
        )

        with self.assertRaises(ValidationError):
            apply_verified_mpesa_payment(
                payment_id=another_payment.pk,
                administrator=self.admin,
                receipt="TESTRECEIPT004",
                verified_amount="100.00",
            )

        self.account.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertEqual(CreditTransaction.objects.count(), 1)


@override_settings(ALLOWED_HOSTS=["testserver"])
class MpesaCallbackSafetyTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(
            admission_number="MPESACALLBACK01",
            first_name="Callback",
            last_name="Test",
            class_name="Form 3",
            guardian_name="Test Guardian",
            guardian_phone="0700000000",
        )

        self.account = CallingAccount.objects.create(
            student=self.student,
            balance=Decimal("0.00"),
            is_active=True,
        )

        self.checkout_id = "ws_CO_CALLBACK_TEST_001"

        self.payment = MpesaPayment.objects.create(
            calling_account=self.account,
            amount=Decimal("100.00"),
            phone_number="254700000000",
            checkout_request_id=self.checkout_id,
        )

        self.callback_url = reverse("mpesa_stk_callback")

    def send_callback(self, checkout_id, result_code=0):
        payload = {
            "Body": {
                "stkCallback": {
                    "CheckoutRequestID": checkout_id,
                    "ResultCode": result_code,
                    "ResultDesc": "Test callback",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 100.00},
                            {
                                "Name": "MpesaReceiptNumber",
                                "Value": "TESTRECEIPT001",
                            },
                        ]
                    },
                }
            }
        }

        return self.client.post(
            self.callback_url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_success_callback_does_not_credit_account(self):
        response = self.send_callback(self.checkout_id)

        self.assertEqual(response.status_code, 200)

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_unknown_checkout_callback_does_not_credit_account(self):
        response = self.send_callback("UNKNOWN_CHECKOUT_ID")

        self.assertEqual(response.status_code, 200)

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_repeated_success_callbacks_do_not_duplicate_credit(self):
        first_response = self.send_callback(self.checkout_id)
        second_response = self.send_callback(self.checkout_id)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(CreditTransaction.objects.count(), 0)


@override_settings(ALLOWED_HOSTS=["testserver"])
class MpesaPaymentStatusTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.student_user = User.objects.create_user(
            username="mpesa_status_student",
            password="TestOnly-Password-789!",
        )

        self.student = Student.objects.create(
            admission_number="STATUS001",
            first_name="Status",
            last_name="Test",
            class_name="Form 3",
            guardian_name="Test Guardian",
            guardian_phone="0700000000",
            is_active=True,
            user=self.student_user,
        )

        self.account = CallingAccount.objects.create(
            student=self.student,
            balance=Decimal("0.00"),
            is_active=True,
        )

        self.checkout_id = "ws_CO_STATUS_TEST_001"

        self.payment = MpesaPayment.objects.create(
            calling_account=self.account,
            amount=Decimal("100.00"),
            phone_number="254700000000",
            checkout_request_id=self.checkout_id,
        )

        self.url = reverse(
            "mpesa-payment-status",
            kwargs={
                "payment_reference": self.payment.payment_reference,
            },
        )

        self.client.force_login(self.student_user)

    @patch("students.views.query_stk_push_status")
    def test_successful_provider_response_does_not_add_credit(
        self, mock_query
    ):
        mock_query.return_value = {
            "ResultCode": 0,
            "ResultDesc": "Success",
        }

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["credit_applied"])

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(CreditTransaction.objects.count(), 0)

    @patch("students.views.query_stk_push_status")
    def test_provider_error_returns_502_without_adding_credit(
        self, mock_query
    ):
        mock_query.side_effect = RuntimeError(
            "Simulated Daraja query failure"
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()["credit_applied"])

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_student_cannot_check_another_students_payment(self):
        other_student = Student.objects.create(
            admission_number="STATUS002",
            first_name="Other",
            last_name="Student",
            class_name="Form 2",
            guardian_name="Other Guardian",
            guardian_phone="0711111111",
            is_active=True,
        )

        other_account = CallingAccount.objects.create(
            student=other_student,
            balance=Decimal("0.00"),
            is_active=True,
        )

        other_payment = MpesaPayment.objects.create(
            calling_account=other_account,
            amount=Decimal("200.00"),
            phone_number="254711111111",
            checkout_request_id="ws_CO_OTHER_STATUS_001",
        )

        other_url = reverse(
            "mpesa-payment-status",
            kwargs={
                "payment_reference": other_payment.payment_reference,
            },
        )

        response = self.client.get(other_url)

        self.assertEqual(response.status_code, 404)

        other_account.refresh_from_db()
        other_payment.refresh_from_db()

        self.assertEqual(other_account.balance, Decimal("0.00"))
        self.assertEqual(
            other_payment.status,
            MpesaPayment.Status.PENDING,
        )


@override_settings(ALLOWED_HOSTS=["testserver"])
class MpesaInitiationTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="mpesa_initiation_test",
            password="TestOnly-Password-789!",
        )

        self.student = Student.objects.create(
            admission_number="INIT001",
            first_name="Initiation",
            last_name="Test",
            class_name="Form 3",
            guardian_name="Test Guardian",
            guardian_phone="0700000000",
            is_active=True,
            user=self.user,
        )

        self.account = CallingAccount.objects.create(
            student=self.student,
            balance=Decimal("0.00"),
            is_active=True,
        )

        self.client.force_login(self.user)
        self.url = reverse("mpesa-payment")

    @patch("students.views.initiate_stk_push")
    def test_accepted_stk_push_saves_ids_and_stays_pending(
        self, mock_stk
    ):
        mock_stk.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_TEST_INIT_001",
            "MerchantRequestID": "merchant_test_001",
            "CustomerMessage": "Success. Request accepted.",
        }

        response = self.client.post(
            self.url,
            {
                "phone_number": "0712345678",
                "amount": "100",
            },
        )

        self.assertEqual(response.status_code, 200)
        mock_stk.assert_called_once()

        payment = MpesaPayment.objects.get(
            calling_account=self.account
        )

        self.assertEqual(
            payment.checkout_request_id,
            "ws_CO_TEST_INIT_001",
        )
        self.assertEqual(
            payment.merchant_request_id,
            "merchant_test_001",
        )
        self.assertEqual(payment.amount, Decimal("100"))
        self.assertEqual(
            payment.status,
            MpesaPayment.Status.PENDING,
        )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)

    @patch("students.views.initiate_stk_push")
    def test_invalid_phone_does_not_create_payment(self, mock_stk):
        response = self.client.post(
            self.url,
            {
                "phone_number": "12345",
                "amount": "100",
            },
        )

        self.assertEqual(response.status_code, 200)
        mock_stk.assert_not_called()
        self.assertEqual(MpesaPayment.objects.count(), 0)

    @patch("students.views.initiate_stk_push")
    def test_invalid_amount_does_not_create_payment(
        self, mock_stk
    ):
        response = self.client.post(
            self.url,
            {
                "phone_number": "0712345678",
                "amount": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        mock_stk.assert_not_called()
        self.assertEqual(MpesaPayment.objects.count(), 0)

    @patch("students.views.initiate_stk_push")
    def test_daraja_error_does_not_add_credit(self, mock_stk):
        mock_stk.side_effect = RuntimeError(
            "Simulated Daraja failure"
        )

        response = self.client.post(
            self.url,
            {
                "phone_number": "0712345678",
                "amount": "100",
            },
        )

        self.assertEqual(response.status_code, 200)

        payment = MpesaPayment.objects.get(
            calling_account=self.account
        )

        self.assertEqual(
            payment.status,
            MpesaPayment.Status.PENDING,
        )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)
    @patch("students.views.initiate_stk_push")
    def test_incomplete_response_does_not_add_credit(
        self, mock_stk
    ):
        mock_stk.return_value = {
            "CustomerMessage": "Please try again."
        }

        response = self.client.post(
            self.url,
            {
                "phone_number": "0712345678",
                "amount": "100",
            },
        )

        self.assertEqual(response.status_code, 200)

        payment = MpesaPayment.objects.get(
            calling_account=self.account
        )

        self.assertEqual(
            payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(payment.checkout_request_id, "")

        self.account.refresh_from_db()
        self.assertEqual(
            self.account.balance,
            Decimal("0.00"),
        )
        self.assertEqual(CreditTransaction.objects.count(), 0)



class MpesaReconciliationAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_superuser(
            username="mpesa_reconciliation_admin",
            email="mpesa-admin@example.test",
            password="temporary-test-password",
        )

        self.staff_without_permission = User.objects.create_user(
            username="mpesa_staff_no_permission",
            password="temporary-test-password",
            is_staff=True,
        )

        self.non_staff = User.objects.create_user(
            username="mpesa_non_staff",
            password="temporary-test-password",
            is_staff=False,
        )

        self.student = Student.objects.create(
            admission_number="MPESARECON001",
            first_name="Reconciliation",
            last_name="Tester",
            class_name="Form 3",
            guardian_name="Test Guardian",
            guardian_phone="0700000000",
        )

        self.account = CallingAccount.objects.create(
            student=self.student,
            balance=Decimal("0.00"),
            is_active=True,
        )

        self.payment = MpesaPayment.objects.create(
            calling_account=self.account,
            amount=Decimal("100.00"),
            phone_number="254700000000",
        )

        self.url = reverse(
            "admin:students_mpesapayment_reconcile",
            args=[self.payment.pk],
        )

    def post_valid_payment(self, receipt="ADMINRECEIPT001"):
        return self.client.post(
            self.url,
            {
                "receipt": receipt,
                "verified_amount": "100.00",
                "confirm_verified": "on",
            },
        )

    def test_superuser_can_view_payment_without_crediting(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_non_staff_user_cannot_access_reconciliation(self):
        self.client.force_login(self.non_staff)

        response = self.client.get(self.url)

        self.assertIn(response.status_code, (302, 403))
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_staff_without_change_permission_is_denied(self):
        self.client.force_login(self.staff_without_permission)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_confirmed_payment_is_credited_once_and_audited(self):
        self.client.force_login(self.admin)

        response = self.post_valid_payment()

        self.assertEqual(response.status_code, 302)

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.SUCCESS,
        )
        self.assertEqual(
            self.payment.provider_receipt,
            "ADMINRECEIPT001",
        )

        transaction_record = CreditTransaction.objects.get(
            account=self.account,
        )
        self.assertEqual(
            transaction_record.recorded_by,
            self.admin,
        )

        # Repeating the submission cannot credit the account again.
        response = self.post_valid_payment()

        self.assertEqual(response.status_code, 302)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertEqual(
            CreditTransaction.objects.filter(
                account=self.account,
            ).count(),
            1,
        )

    def test_missing_confirmation_does_not_credit(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url,
            {
                "receipt": "ADMINRECEIPT002",
                "verified_amount": "100.00",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_mismatched_amount_does_not_credit(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url,
            {
                "receipt": "ADMINRECEIPT003",
                "verified_amount": "50.00",
                "confirm_verified": "on",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.account.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertEqual(
            self.payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_receipt_used_by_another_payment_is_rejected(self):
        self.client.force_login(self.admin)

        first_response = self.post_valid_payment(
            receipt="ADMINRECEIPT004",
        )
        self.assertEqual(first_response.status_code, 302)

        another_payment = MpesaPayment.objects.create(
            calling_account=self.account,
            amount=Decimal("100.00"),
            phone_number="254711111111",
        )
        another_url = reverse(
            "admin:students_mpesapayment_reconcile",
            args=[another_payment.pk],
        )

        response = self.client.post(
            another_url,
            {
                "receipt": "ADMINRECEIPT004",
                "verified_amount": "100.00",
                "confirm_verified": "on",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.account.refresh_from_db()
        another_payment.refresh_from_db()

        self.assertEqual(self.account.balance, Decimal("100.00"))
        self.assertEqual(
            another_payment.status,
            MpesaPayment.Status.PENDING,
        )
        self.assertEqual(CreditTransaction.objects.count(), 1)
