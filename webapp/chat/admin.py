"""
Admin configuration for ACU AI Chatbot.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Conversation, DocumentChunk, Message, WebPage


# ── Inline for Messages ──────────────────────────────────
class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("role", "content", "model_name", "response_time_ms", "sources", "created_at")
    fields = ("role", "content", "model_name", "response_time_ms", "created_at")
    ordering = ("created_at",)

    def has_add_permission(self, request, obj=None):
        return False


# ── Inline for Document Chunks ───────────────────────────
class DocumentChunkInline(admin.TabularInline):
    model = DocumentChunk
    extra = 0
    readonly_fields = ("chunk_index", "content_preview", "token_count", "has_embedding")
    fields = ("chunk_index", "content_preview", "token_count", "has_embedding")

    def content_preview(self, obj):
        return obj.content[:200] + "..." if len(obj.content) > 200 else obj.content
    content_preview.short_description = "Content Preview"

    def has_embedding(self, obj):
        return obj.embedding is not None
    has_embedding.boolean = True
    has_embedding.short_description = "Has Embedding"

    def has_add_permission(self, request, obj=None):
        return False


# ── WebPage Admin ────────────────────────────────────────
@admin.register(WebPage)
class WebPageAdmin(admin.ModelAdmin):
    list_display = (
        "title_display",
        "source",
        "category",
        "language",
        "is_processed",
        "chunk_count",
        "scraped_at",
    )
    list_filter = ("source", "category", "language", "is_processed")
    search_fields = ("title", "url", "content")
    readonly_fields = ("scraped_at", "updated_at")
    list_per_page = 50
    inlines = [DocumentChunkInline]

    def title_display(self, obj):
        title = obj.title or "Untitled"
        return format_html('<a href="{}" target="_blank">{}</a>', obj.url, title[:60])
    title_display.short_description = "Title"

    def chunk_count(self, obj):
        return obj.chunks.count()
    chunk_count.short_description = "Chunks"


# ── DocumentChunk Admin ──────────────────────────────────
@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("__str__", "token_count", "has_embedding", "created_at")
    list_filter = ("web_page__source",)
    search_fields = ("content", "web_page__title")
    readonly_fields = ("created_at",)
    list_per_page = 50

    def has_embedding(self, obj):
        return obj.embedding is not None
    has_embedding.boolean = True
    has_embedding.short_description = "Has Embedding"


# ── Conversation Admin ───────────────────────────────────
@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title_display", "message_count", "session_key_short", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("title", "session_key")
    readonly_fields = ("id", "created_at", "updated_at")
    list_per_page = 50
    inlines = [MessageInline]

    def title_display(self, obj):
        return obj.title or "Untitled Conversation"
    title_display.short_description = "Title"

    def session_key_short(self, obj):
        return obj.session_key[:12] + "..." if len(obj.session_key) > 12 else obj.session_key
    session_key_short.short_description = "Session"


# ── Message Admin ────────────────────────────────────────
@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("content_preview", "role", "conversation", "model_name", "response_time_display", "created_at")
    list_filter = ("role", "model_name", "created_at")
    search_fields = ("content", "conversation__title")
    readonly_fields = ("created_at",)
    list_per_page = 100

    def content_preview(self, obj):
        return obj.content[:100] + "..." if len(obj.content) > 100 else obj.content
    content_preview.short_description = "Content"

    def response_time_display(self, obj):
        if obj.response_time_ms:
            return f"{obj.response_time_ms / 1000:.1f}s"
        return "-"
    response_time_display.short_description = "Response Time"


# ── Admin Site Customization ─────────────────────────────
admin.site.site_header = "ACU AI Chatbot - Admin"
admin.site.site_title = "ACU Chatbot Admin"
admin.site.index_title = "Dashboard"
