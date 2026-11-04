from django.urls import path
from . import views

from django.urls import path
from .views import (
    student_parent_contacts,
    my_parent_contacts,
    check_call_readiness,
    booth_lockscreen,
    student_login,
    student_homescreen,
    student_calling,
)

urlpatterns = [
    path(
        "api/students/<str:admission_number>/contacts/",
        student_parent_contacts,
        name="student-parent-contacts",
    ),
    path(
        "api/my-contacts/",
        my_parent_contacts,
        name="my-parent-contacts",
    ),
    path(
        "api/check-call-readiness/",
        check_call_readiness,
        name="check-call-readiness",
    ),
    path(
        "booth/",
        booth_lockscreen,
        name="booth-lockscreen",
    ),
    path(
        "student-login/",
        student_login,
        name="student-login",
    ),
    path(
        "student-homescreen/",
        student_homescreen,
        name="student-homescreen",
    ),
    path(
        "calling/",
        student_calling,
        name="student-calling",
    ),
    path(
        "mpesa/callback/",
        views.mpesa_stk_callback,
        name="mpesa_stk_callback"
    ),
]
