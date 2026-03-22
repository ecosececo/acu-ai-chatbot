"""
Views for the Chat application.
Handles both the web interface and API endpoints.
"""

import json
import logging
import time
import uuid

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .models import Conversation, Message, WebPage, DocumentChunk
from .serializers import (
    ChatRequestSerializer,
    ChatResponseSerializer,
    ConversationListSerializer,
    ConversationSerializer,
    StatsSerializer,
    WebPageSerializer,
)
from .services.llm_service import llm_service
from .services.rag_service import rag_service

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  Web Interface Views
# ══════════════════════════════════════════════════════════

def index(request):
    """Main chat interface."""
    # Create or retrieve session-based conversation
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    conversations = Conversation.objects.filter(
        session_key=session_key, is_active=True
    ).order_by("-updated_at")[:20]

    return render(request, "chat/index.html", {
        "conversations": conversations,
        "session_key": session_key,
    })


# ══════════════════════════════════════════════════════════
#  REST API Views
# ══════════════════════════════════════════════════════════

@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_chat(request):
    """
    POST /api/chat/
    Main chat endpoint. Accepts a question, retrieves context via RAG,
    and returns an AI-generated answer.
    """
    logger.info(f"Chat request - Content-Type: {request.content_type}, Data: {request.data}")
    serializer = ChatRequestSerializer(data=request.data)
    if not serializer.is_valid():
        logger.warning(f"Chat validation failed: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    question = serializer.validated_data["question"]
    conversation_id = serializer.validated_data.get("conversation_id")
    stream = serializer.validated_data.get("stream", False)

    # Check LLM availability
    if not llm_service.is_available():
        return Response(
            {
                "error": "AI servisi şu anda kullanılamıyor. Lütfen birkaç dakika sonra tekrar deneyin.",
                "detail": "The LLM service is not available. It may still be loading.",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Get or create conversation
    if conversation_id:
        try:
            conversation = Conversation.objects.get(id=conversation_id)
        except Conversation.DoesNotExist:
            conversation = _create_conversation(request, question)
    else:
        conversation = _create_conversation(request, question)

    # Save user message
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content=question,
    )

    # Handle streaming response
    if stream:
        return _stream_response(conversation, question)

    # RAG: Retrieve relevant context
    context, sources = rag_service.build_context(question)

    # Generate LLM response
    result = llm_service.generate(question, context)

    # Save assistant message
    source_urls = [s["url"] for s in sources] if sources else []
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=result["answer"],
        context_used=context[:5000] if context else "",
        sources=source_urls,
        model_name=result.get("model", settings.LLM_MODEL),
        response_time_ms=result.get("response_time_ms"),
    )

    # Update conversation title if first exchange
    if conversation.messages.count() <= 2 and not conversation.title:
        conversation.title = question[:100]
        conversation.save(update_fields=["title"])

    response_data = {
        "answer": result["answer"],
        "conversation_id": str(conversation.id),
        "sources": sources or [],
        "model": result.get("model", settings.LLM_MODEL),
        "response_time_ms": result.get("response_time_ms", 0),
    }

    return Response(response_data, status=status.HTTP_200_OK)


def _stream_response(conversation, question):
    """Generate a Server-Sent Events streaming response."""
    context, sources = rag_service.build_context(question)

    def event_stream():
        full_response = ""
        start_time = time.time()

        # Send sources first
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        # Stream LLM response
        for chunk in llm_service.generate_stream(question, context):
            data = json.loads(chunk)
            content = data.get("content", "")
            full_response += content
            yield f"data: {json.dumps({'type': 'content', 'content': content, 'done': data.get('done', False)})}\n\n"

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Save the complete response
        source_urls = [s["url"] for s in sources] if sources else []
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content=full_response,
            context_used=context[:5000] if context else "",
            sources=source_urls,
            model_name=settings.LLM_MODEL,
            response_time_ms=elapsed_ms,
        )

        # Update conversation title
        if conversation.messages.count() <= 2 and not conversation.title:
            conversation.title = question[:100]
            conversation.save(update_fields=["title"])

        # Send completion event
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': str(conversation.id), 'response_time_ms': elapsed_ms})}\n\n"

    response = StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _create_conversation(request, question):
    """Create a new conversation."""
    session_key = getattr(request, "session", {})
    if hasattr(session_key, "session_key"):
        session_key = session_key.session_key or ""
    else:
        session_key = ""

    return Conversation.objects.create(
        title=question[:100],
        session_key=session_key,
    )


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_conversations(request):
    """
    GET /api/conversations/
    List conversations for the current session.
    """
    session_key = request.session.session_key or ""
    conversations = (
        Conversation.objects
        .filter(session_key=session_key, is_active=True)
        .order_by("-updated_at")[:50]
    )
    serializer = ConversationListSerializer(conversations, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_conversation_detail(request, conversation_id):
    """
    GET /api/conversations/<id>/
    Get a conversation with all messages.
    """
    conversation = get_object_or_404(Conversation, id=conversation_id)
    serializer = ConversationSerializer(conversation)
    return Response(serializer.data)


@api_view(["DELETE"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_conversation_delete(request, conversation_id):
    """
    DELETE /api/conversations/<id>/
    Delete a conversation.
    """
    conversation = get_object_or_404(Conversation, id=conversation_id)
    conversation.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_stats(request):
    """
    GET /api/stats/
    Get system statistics.
    """
    rag_stats = rag_service.get_stats()

    data = {
        "total_pages": rag_stats["total_pages"],
        "processed_pages": rag_stats["processed_pages"],
        "total_chunks": rag_stats["total_chunks"],
        "embedded_chunks": rag_stats["embedded_chunks"],
        "total_conversations": Conversation.objects.count(),
        "total_messages": Message.objects.count(),
        "llm_available": llm_service.is_available(),
        "llm_model": settings.LLM_MODEL,
    }

    serializer = StatsSerializer(data)
    return Response(serializer.data)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_health(request):
    """
    GET /api/health/
    Health check endpoint.
    """
    return Response({
        "status": "healthy",
        "llm_available": llm_service.is_available(),
        "model": settings.LLM_MODEL,
    })
