"""
Serializers for the Chat API.
"""

from rest_framework import serializers

from .models import Conversation, Message, WebPage


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "role",
            "content",
            "sources",
            "model_name",
            "response_time_ms",
            "created_at",
        ]
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    message_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id",
            "title",
            "message_count",
            "is_active",
            "created_at",
            "updated_at",
            "messages",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ConversationListSerializer(serializers.ModelSerializer):
    """Lighter serializer for listing conversations."""
    message_count = serializers.IntegerField(read_only=True)
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "title", "message_count", "is_active", "created_at", "updated_at", "last_message"]

    def get_last_message(self, obj):
        last = obj.messages.order_by("-created_at").first()
        if last:
            return {
                "role": last.role,
                "content": last.content[:100] + "..." if len(last.content) > 100 else last.content,
                "created_at": last.created_at.isoformat(),
            }
        return None


class ChatRequestSerializer(serializers.Serializer):
    """Serializer for incoming chat requests."""
    question = serializers.CharField(
        max_length=2000,
        help_text="The user's question about Acıbadem University",
    )
    conversation_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional conversation ID to continue an existing conversation",
    )
    stream = serializers.BooleanField(
        default=False,
        help_text="Whether to stream the response (SSE)",
    )


class ChatResponseSerializer(serializers.Serializer):
    """Serializer for chat responses."""
    answer = serializers.CharField()
    conversation_id = serializers.UUIDField()
    sources = serializers.ListField(child=serializers.DictField())
    model = serializers.CharField()
    response_time_ms = serializers.IntegerField()


class WebPageSerializer(serializers.ModelSerializer):
    chunk_count = serializers.SerializerMethodField()

    class Meta:
        model = WebPage
        fields = [
            "id",
            "url",
            "title",
            "source",
            "category",
            "language",
            "is_processed",
            "chunk_count",
            "scraped_at",
        ]

    def get_chunk_count(self, obj):
        return obj.chunks.count()


class StatsSerializer(serializers.Serializer):
    """System statistics."""
    total_pages = serializers.IntegerField()
    processed_pages = serializers.IntegerField()
    total_chunks = serializers.IntegerField()
    embedded_chunks = serializers.IntegerField()
    total_conversations = serializers.IntegerField()
    total_messages = serializers.IntegerField()
    llm_available = serializers.BooleanField()
    llm_model = serializers.CharField()
