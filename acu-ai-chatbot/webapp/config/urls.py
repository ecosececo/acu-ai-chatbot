"""
URL configuration for ACU AI Chatbot.
"""

from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse


def health_check(request):
    """Health check endpoint for Docker."""
    return JsonResponse({"status": "healthy"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health-check"),
    path("api/", include("chat.api_urls")),
    path("", include("chat.urls")),
]
