"""
Views for the Chat application.
Handles both the web interface and API endpoints.
"""

import json
import logging
import re
import time

from django.conf import settings
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Conversation, Message, WebPage
from .serializers import (
    ChatRequestSerializer,
    ConversationListSerializer,
    ConversationSerializer,
    StatsSerializer,
)
from .services.llm_service import llm_service
from .services.rag_service import rag_service
from .services.web_search_service import web_search_service

logger = logging.getLogger(__name__)


def _is_course_plan_question(question: str) -> bool:
    question_lower = question.lower()
    return any(term in question_lower for term in ("ders program", "dersler", "mÃ¼fredat", "müfredat"))


def _build_course_plan_answer(sources: list[dict]) -> str:
    course_source = next(
        (
            source
            for source in sources
            if "progCourses" in source.get("url", "") or "Dersler" in source.get("title", "")
        ),
        None,
    )
    if not course_source:
        return ""

    page = WebPage.objects.filter(url=course_source["url"]).first()
    if not page or not page.content:
        return ""

    lines = [line.strip() for line in page.content.splitlines() if line.strip()]
    answer_lines = [
        f"{page.title} sayfasindaki ders planina gore:",
        "",
    ]
    current_semester = None
    course_count = 0
    seen_semesters = set()

    for line in lines:
        semester_match = re.match(r"^(\d+)\.Yar[ıi]y[ıi]l Ders Plan[ıi]", line, re.I)
        if semester_match:
            semester_number = semester_match.group(1)
            if semester_number in seen_semesters:
                break
            seen_semesters.add(semester_number)
            current_semester = f"{semester_number}. Yariyil"
            answer_lines.extend(["", f"### {current_semester}"])
            continue

        if not current_semester:
            continue

        if line.startswith("Toplam AKTS"):
            answer_lines.append(f"- {line}")
            continue

        parts = [part.strip() for part in line.split("\t") if part.strip()]
        if len(parts) < 2:
            continue

        code = parts[0]
        if not re.match(r"^[A-Z]{2,5}\s?\d{3,4}$", code):
            continue

        name = parts[1]
        t_ul = parts[2] if len(parts) > 2 else ""
        requirement = parts[3] if len(parts) > 3 else ""
        akts = parts[4] if len(parts) > 4 else ""

        detail = f"{code} - {name}"
        extras = []
        if akts:
            extras.append(f"AKTS {akts}")
        if t_ul:
            extras.append(f"T+U+L {t_ul}")
        if requirement:
            extras.append(requirement)
        if extras:
            detail += f" ({', '.join(extras)})"
        answer_lines.append(f"- {detail}")
        course_count += 1

    if course_count == 0:
        return ""

    answer_lines.extend(["", f"Kaynak: {course_source['title']} - {course_source['url']}"])
    return "\n".join(answer_lines)


def _prioritize_course_plan_context(question: str, context: str, sources: list[dict]) -> str:
    if not _is_course_plan_question(question):
        return context

    course_context = _build_course_plan_answer(sources)
    if not course_context:
        return context

    prompt_context = (
        "ONCELIKLI DERS PROGRAMI TABLOSU\n"
        "Bu tablo tek kaynaktir. Cevabi qwen3.5 uretecek, ancak ders kodu, ders adi, "
        "AKTS, T+U+L ve zorunlu/secimlik bilgileri yalnizca bu tablodan alinmalidir.\n\n"
        f"{course_context}"
    )
    return prompt_context


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
    web_search_enabled = serializer.validated_data.get("web_search", False)

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
        return _stream_response(conversation, question, web_search_enabled)

    # RAG: Retrieve relevant context
    context, sources = rag_service.build_context(question)

    # Web search: always run alongside RAG when enabled
    if web_search_enabled and getattr(settings, 'WEB_SEARCH_ENABLED', True):
        web_results = web_search_service.search(question)
        if web_results:
            web_context = web_search_service.build_web_context(web_results)
            context = f"{context}\n\n--- WEB ARAMA SONUÇLARI ---\n{web_context}" if context else web_context
            for wr in web_results:
                sources.append({
                    "url": wr["url"],
                    "title": f"🌐 {wr['title']}",
                    "score": 0,
                    "source": "web_search",
                })

    context = _prioritize_course_plan_context(question, context, sources)

    # Fetch conversation history for context
    history = _get_conversation_history(conversation)

    # Generate LLM response
    result = llm_service.generate(question, context, history=history)
    if not result.get("answer"):
        result["answer"] = "Üzgünüm, şu an yanıt oluşturulamadı. Lütfen soruyu tekrar deneyin."

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
        "web_search_used": web_search_enabled and settings.WEB_SEARCH_ENABLED,
    }

    return Response(response_data, status=status.HTTP_200_OK)


def _get_conversation_history(conversation, max_messages: int = 6) -> list[dict]:
    """Fetch recent conversation history for context."""
    messages = (
        conversation.messages
        .exclude(role=Message.Role.SYSTEM)
        .order_by("-created_at")[:max_messages]
    )
    return [
        {"role": msg.role, "content": msg.content}
        for msg in reversed(messages)
    ]


def _stream_response(conversation, question, web_search_enabled=False):
    """Generate a Server-Sent Events streaming response."""
    context = ""
    sources = []

    # Web search is handled inside event_stream after the conversation event.
    if False:
        web_results = web_search_service.search(question)
        if web_results:
            web_context = web_search_service.build_web_context(web_results)
            context = f"{context}\n\n--- WEB ARAMA SONUÇLARI ---\n{web_context}" if context else web_context
            for wr in web_results:
                sources.append({
                    "url": wr["url"],
                    "title": f"🌐 {wr['title']}",
                    "score": 0,
                    "source": "web_search",
                })

    history = _get_conversation_history(conversation)

    def event_stream():
        full_response = ""
        start_time = time.time()

        # Send the conversation id immediately so the UI can show the new
        # conversation in the sidebar before the model finishes responding.
        yield f"data: {json.dumps({'type': 'conversation', 'conversation_id': str(conversation.id), 'title': conversation.title})}\n\n"

        context, sources = rag_service.build_context(question)
        if web_search_enabled and getattr(settings, 'WEB_SEARCH_ENABLED', True):
            web_results = web_search_service.search(question)
            if web_results:
                web_context = web_search_service.build_web_context(web_results)
                context = f"{context}\n\n--- WEB ARAMA SONUÃ‡LARI ---\n{web_context}" if context else web_context
                for wr in web_results:
                    sources.append({
                        "url": wr["url"],
                        "title": f"ðŸŒ {wr['title']}",
                        "score": 0,
                        "source": "web_search",
                    })

        # Send sources first
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        context = _prioritize_course_plan_context(question, context, sources)

        # Stream LLM response
        for chunk in llm_service.generate_stream(question, context, history=history):
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
    session = getattr(request, "session", None)
    if session is not None and not session.session_key:
        session.create()
    session_key = session.session_key if session is not None else ""

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
    if not request.session.session_key:
        request.session.create()
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
