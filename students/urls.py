from django.urls import path

# We do NOT import views directly here. 
# We use string references to prevent circular imports.

urlpatterns = [
    path(
        "", 
        "students.views.student_login", 
        name="home"
    ),
    path(
        "api/students/<str:admission_number>/contacts/",
        "students.views.student_parent_contacts",
        name="student-parent-contacts",
    ),
    path(
        "api/my-contacts/",
        "students.views.my_parent_contacts",
        name="my-parent-contacts",
    ),
    path(
        "api/check-call-readiness/",
        "students.views.check_call_readiness",
        name="check-call-readiness",
    ),
    path(
        "booth/",
        "students.views.booth_lockscreen",
        name="booth-lockscreen",
    ),
    path(
        "student-login/",
        "students.views.student_login",
        name="student-login",
    ),
    path(
        "student-homescreen/",
        "students.views.student_homescreen",
        name="student-homescreen",
    ),
    path(
        "calling/",
        "students.views.student_calling",
        name="student-calling",
    ),
    path(
        "mpesa/pay/",
        "students.views.initiate_calling_credit_payment",
        name="mpesa-payment",
    ),
    path(
        "mpesa/payments/<uuid:payment_reference>/status/",
        "students.views.check_mpesa_payment_status",
        name="mpesa-payment-status",
    ),
    path(
        "mpesa/callback/",
        "students.views.mpesa_stk_callback",
        name="mpesa_stk_callback",
    ),
]