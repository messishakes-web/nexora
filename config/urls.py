
"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import path, include

from django.http import HttpResponse

def home(request):
    return HttpResponse("Nexora is live 🎉")

urlpatterns = [
    path('', home),
    path('admin/', admin.site.urls),
    path('students/', include('students.urls')),
    # ... your existing routes
]
