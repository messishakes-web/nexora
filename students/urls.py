from django.urls import path

# We import the views module here. 
# If views.py imports something from urls.py, we will use string references 
# for reverse() inside views.py, not import them.
from . import views

urlpatterns = [
    path("", views.student_login, name="home"),
    path(
        "api/students/<str:admission_number>/contacts/",
        views.student_parent_contacts,
        name="student-parent-contacts",
    ),
    path(
        "api/my-contacts/",
        views.my_parent_contacts,
        name="my-parent-contacts",
    ),
    path(
        "api/check-call-readiness/",
        views.check_call_readiness,
        name="check-call-readiness",
    ),
    path(
        "booth/",
        views.booth_lockscreen,
        name="booth-lockscreen",
    ),
    path(
        "student-login/",
        views.student_login,
        name="student-login",
    ),
    path(
        "student-homescreen/",
        views.student_homescreen,
        name="student-homescreen",
    ),
    path(
        "calling/",
        views.student_calling,
        name="student-calling",
    ),
    path(
        "mpesa/pay/",
        views.initiate_calling_credit_payment,
        name="mpesa-payment",
    ),
    path(
        "mpesa/payments/<uuid:payment_reference>/status/",
        views.check_mpesa_payment_status,
        name="mpesa-payment-status",
    ),
    path(
        "mpesa/callback/",
        views.mpesa_stk_callback,
        name="mpesa_stk_callback",
    ),
]