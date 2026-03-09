"""
Models for ACU AI Chatbot.

Includes:
- WebPage: Scraped pages from ACU websites
- DocumentChunk: Text chunks with pgvector embeddings for RAG
- Conversation: Chat sessions
- Message: Individual chat messages
"""

import uuid

from django.db import models
from pgvector.django import VectorField


class WebPage(models.Model):
    """Stores scraped web pages from Acıbadem University websites."""

    class Source(models.TextChoices):
        MAIN_SITE = "main", "Ana Site (acibadem.edu.tr)"
        BOLOGNA = "bologna", "Bologna (obs.acibadem.edu.tr)"

    url = models.URLField(max_length=1024, unique=True, db_index=True)
    title = models.CharField(max_length=512, blank=True, default="")
    content = models.TextField(help_text="Raw text content extracted from the page")
    html = models.TextField(blank=True, default="", help_text="Original HTML (for reference)")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MAIN_SITE)
    category = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
        help_text="Page category (e.g., faculty, department, course, admission)",
    )
    language = models.CharField(max_length=5, default="tr", help_text="Content language (tr/en)")
    scraped_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_processed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether chunks and embeddings have been generated",
    )

    class Meta:
        ordering = ["-scraped_at"]
        verbose_name = "Web Page"
        verbose_name_plural = "Web Pages"

    def __str__(self):
        return f"{self.title or self.url} ({self.source})"


class DocumentChunk(models.Model):
    """Text chunks with vector embeddings for RAG semantic search."""

    web_page = models.ForeignKey(
        WebPage,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_index = models.PositiveIntegerField(help_text="Order of chunk within the page")
    content = models.TextField(help_text="Text content of this chunk")
    embedding = VectorField(
        dimensions=768,
        null=True,
        blank=True,
        help_text="nomic-embed-text vector (768 dims)",
    )
    token_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata (section title, headers, etc.)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["web_page", "chunk_index"]
        verbose_name = "Document Chunk"
        verbose_name_plural = "Document Chunks"
        indexes = [
            models.Index(fields=["web_page", "chunk_index"]),
        ]

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.web_page.title or self.web_page.url}"


class Conversation(models.Model):
    """A chat conversation/session."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, blank=True, default="")
    session_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Anonymous session identifier",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Conversation"
        verbose_name_plural = "Conversations"

    def __str__(self):
        return f"{self.title or 'Untitled'} ({self.created_at:%Y-%m-%d %H:%M})"

    @property
    def message_count(self):
        return self.messages.count()


class Message(models.Model):
    """An individual message in a conversation."""

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    context_used = models.TextField(
        blank=True,
        default="",
        help_text="RAG context that was used to generate this response",
    )
    sources = models.JSONField(
        default=list,
        blank=True,
        help_text="List of source URLs used for the response",
    )
    model_name = models.CharField(max_length=100, blank=True, default="")
    response_time_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="LLM response time in milliseconds",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Message"
        verbose_name_plural = "Messages"

    def __str__(self):
        preview = self.content[:80] + "..." if len(self.content) > 80 else self.content
        return f"[{self.role}] {preview}"
