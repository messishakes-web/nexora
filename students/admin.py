import secrets
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    Student,
    ParentContact,
    CallingAccount,
    CreditTransaction,
    CallRecord,
)
from .services import add_calling_credit


# =========================================================
# STUDENT PIN GENERATION
# =========================================================

def generate_student_pin():
    """Generate a random six-digit numeric student PIN."""
    return f"{secrets.randbelow(1_000_000):06d}"


class StudentPINForm(forms.Form):
    confirm_reset = forms.BooleanField(
        required=True,
        label="I confirm that I want to generate or reset this PIN.",
    )


# =========================================================
# STUDENT ADMIN
# =========================================================

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "admission_number",
        "first_name",
        "last_name",
        "class_name",
        "guardian_name",
        "guardian_phone",
        "is_active",
        "user",
        "pin_action",
    )

    search_fields = (
        "admission_number",
        "first_name",
        "last_name",
        "guardian_name",
    )

    list_filter = ("class_name", "is_active")

    @admin.display(description="PIN Management")
    def pin_action(self, obj):
        url = reverse(
            "admin:students_student_set_pin",
            args=[obj.pk],
        )
        return format_html(
            '<a class="button" href="{}">Generate / Reset PIN</a>',
            url,
        )

    def save_model(self, request, obj, form, change):
        """
        When a new student is saved, automatically create a linked
        login account and generate a six-digit PIN.

        Existing student accounts are not reset when student details
        are edited.
        """
        is_new_student = not change and obj.user_id is None

        with transaction.atomic():
            super().save_model(request, obj, form, change)

            if not is_new_student:
                return

            User = get_user_model()

            # Avoid accidentally linking the student to the wrong user.
            if User.objects.filter(
                username=obj.admission_number
            ).exists():
                messages.warning(
                    request,
                    "The student was saved, but an account was not "
                    "created because this admission number is already "
                    "being used as a username. Resolve the conflict "
                    "before generating the student's PIN.",
                )
                return

            pin = generate_student_pin()

            user = User.objects.create_user(
                username=obj.admission_number,
                password=pin,
                is_staff=False,
                is_superuser=False,
                is_active=obj.is_active,
            )

            obj.user = user
            obj.save(update_fields=["user"])

            messages.success(
                request,
                f"Student account created. Temporary six-digit PIN: "
                f"{pin}. Give it to the student securely. "
                "It will not be displayed again.",
            )

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/set-pin/",
                self.admin_site.admin_view(self.set_pin_view),
                name="students_student_set_pin",
            ),
        ]
        return custom_urls + super().get_urls()

    def set_pin_view(self, request, object_id):
        student = get_object_or_404(
            self.get_queryset(request),
            pk=object_id,
        )

        if not self.has_change_permission(request, student):
            raise PermissionDenied

        form = StudentPINForm(request.POST or None)

        if request.method == "POST" and form.is_valid():
            User = get_user_model()

            try:
                with transaction.atomic():
                    if student.user_id:
                        # Reset the existing account's password.
                        user = student.user
                        pin = generate_student_pin()

                        user.set_password(pin)
                        user.is_active = student.is_active
                        user.save(
                            update_fields=["password", "is_active"]
                        )

                    else:
                        # Create an account if the student has none.
                        username = student.admission_number

                        if User.objects.filter(
                            username=username
                        ).exists():
                            form.add_error(
                                None,
                                "An account with this username already "
                                "exists. Resolve the conflict first.",
                            )
                            raise ValidationError(
                                "Username conflict."
                            )

                        pin = generate_student_pin()

                        user = User.objects.create_user(
                            username=username,
                            password=pin,
                            is_staff=False,
                            is_superuser=False,
                            is_active=student.is_active,
                        )

                        student.user = user
                        student.save(update_fields=["user"])

            except ValidationError:
                # Keep the form open so the administrator can see the error.
                pass

            else:
                messages.success(
                    request,
                    f"PIN generated successfully for "
                    f"{student.first_name} {student.last_name}. "
                    f"Temporary six-digit PIN: {pin}. "
                    "Give it to the student securely; it will not "
                    "be displayed again.",
                )

                return redirect(
                    reverse(
                        "admin:students_student_change",
                        args=[student.pk],
                    )
                )

        context = {
            **self.admin_site.each_context(request),
            "title": (
                f"Generate / Reset PIN for "
                f"{student.first_name} {student.last_name}"
            ),
            "opts": self.model._meta,
            "student": student,
            "form": form,
        }

        return TemplateResponse(
            request,
            "admin/student_set_pin.html",
            context,
        )


# =========================================================
# PARENT CONTACT ADMIN
# =========================================================

@admin.register(ParentContact)
class ParentContactAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "student",
        "relationship",
        "phone_number",
        "is_authorized",
    )

    search_fields = (
        "full_name",
        "phone_number",
        "student__admission_number",
    )

    list_filter = ("relationship", "is_authorized")


# =========================================================
# CALLING CREDIT FORM
# =========================================================

class CallingCreditForm(forms.Form):
    amount = forms.DecimalField(
        label="Credit amount (KSh)",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    description = forms.CharField(
        label="Reason for credit addition",
        max_length=255,
    )

    reference = forms.CharField(
        label="Transaction reference",
        max_length=100,
        required=False,
    )


# =========================================================
# CALLING ACCOUNT ADMIN
# =========================================================

@admin.register(CallingAccount)
class CallingAccountAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "balance",
        "is_active",
        "date_created",
        "credit_action",
    )

    search_fields = (
        "student__admission_number",
        "student__first_name",
        "student__last_name",
    )

    list_filter = ("is_active",)

    readonly_fields = ("balance", "date_created")

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/add-credit/",
                self.admin_site.admin_view(self.add_credit_view),
                name="students_callingaccount_add_credit",
            ),
        ]
        return custom_urls + super().get_urls()

    @admin.display(description="Credit")
    def credit_action(self, obj):
        url = reverse(
            "admin:students_callingaccount_add_credit",
            args=[obj.pk],
        )
        return format_html(
            '<a href="{}">Add calling credit</a>',
            url,
        )

    def add_credit_view(self, request, object_id):
        account = get_object_or_404(
            self.get_queryset(request),
            pk=object_id,
        )

        if not self.has_change_permission(request, account):
            raise PermissionDenied

        form = CallingCreditForm(request.POST or None)

        if request.method == "POST" and form.is_valid():
            try:
                add_calling_credit(
                    account_id=account.pk,
                    amount=form.cleaned_data["amount"],
                    administrator=request.user,
                    description=form.cleaned_data["description"],
                    reference=form.cleaned_data["reference"],
                )

            except ValidationError as error:
                form.add_error(None, error)

            else:
                messages.success(
                    request,
                    "Calling credit added successfully.",
                )
                return redirect(
                    "admin:students_callingaccount_changelist"
                )

        context = {
            **self.admin_site.each_context(request),
            "title": "Add Calling Credit",
            "opts": self.model._meta,
            "account": account,
            "form": form,
            "account_list_url": reverse(
                "admin:students_callingaccount_changelist"
            ),
        }

        return TemplateResponse(
            request,
            "admin/calling_credit.html",
            context,
        )


# =========================================================
# CREDIT TRANSACTION ADMIN
# =========================================================

@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "transaction_type",
        "amount",
        "balance_after",
        "recorded_by",
        "created_at",
    )

    search_fields = (
        "account__student__admission_number",
        "description",
        "reference",
    )

    list_filter = ("transaction_type", "created_at")

    readonly_fields = (
        "account",
        "transaction_type",
        "amount",
        "balance_after",
        "description",
        "reference",
        "recorded_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# =========================================================
# CALL RECORD ADMIN
# =========================================================

@admin.register(CallRecord)
class CallRecordAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "parent_contact",
        "booth_reference",
        "started_at",
        "duration_seconds",
        "cost",
        "status",
    )

    search_fields = (
        "student__admission_number",
        "student__first_name",
        "student__last_name",
        "parent_contact__full_name",
        "booth_reference",
    )

    list_filter = ("status", "started_at")

    readonly_fields = (
        "student",
        "parent_contact",
        "booth_reference",
        "started_at",
        "duration_seconds",
        "cost",
        "status",
        "credit_transaction",
        "notes",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False