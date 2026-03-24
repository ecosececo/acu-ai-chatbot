"""
URL configuration for the Chat REST API.
"""

from django.urls import path

from . import views

urlpatterns = [
    # Main chat endpoint
    path("chat/", views.api_chat, name="api-chat"),

    # Conversations
    path("conversations/", views.api_conversations, name="api-conversations"),
    path("conversations/<uuid:conversation_id>/", views.api_conversation_detail, name="api-conversation-detail"),
    path("conversations/<uuid:conversation_id>/delete/", views.api_conversation_delete, name="api-conversation-delete"),

    # System
    path("stats/", views.api_stats, name="api-stats"),
    path("health/", views.api_health, name="api-health"),
]
