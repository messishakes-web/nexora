import time
from django.contrib.auth import logout


class StudentInactivityMiddleware:
    TIMEOUT_SECONDS = 300  # 5 minutes

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and hasattr(
            request.user, "student_profile"
        ):
            now = time.time()
            last_activity = request.session.get("student_last_activity")

            if last_activity is not None:
                if now - last_activity > self.TIMEOUT_SECONDS:
                    logout(request)
                    request.session.pop("student_last_activity", None)

            if request.user.is_authenticated:
                request.session["student_last_activity"] = now

        return self.get_response(request)
