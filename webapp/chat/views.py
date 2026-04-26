"""
Views for the Chat application.
Handles both the web interface and API endpoints.
"""

import json
import logging
import re
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from django.conf import settings
from django.core.cache import cache
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

REQUEST_TIMEOUT_SECONDS = 35
TIMEOUT_MESSAGE = "Yanıt süresi aşıldı. Lütfen sorunuzu daha kısa veya daha belirli şekilde tekrar deneyin."
TIMEOUT_MESSAGE_EN = "The response timed out. Please try a shorter or more specific question."
ACADEMIC_KEYWORDS = {
    "fakülte", "faculty", "bölüm", "department", "program", "ders", "course",
    "kampüs", "campus", "erasmus", "başvuru", "application", "burs",
    "scholarship", "üniversite", "university",
}
BASE_DOMAIN_VOCAB = {
    "acıbadem", "acibadem", "üniversitesi", "university", "fakülte", "fakültesi",
    "fakülteler", "bölüm", "bölümü", "bölümler", "program", "ders", "kampüs",
    "erasmus", "başvuru", "burs", "tıp", "sağlık", "bilimleri", "eczacılık",
    "mühendislik", "doğa", "insan", "toplum", "bilgisayar", "biyomedikal",
    "öğrenci", "öğrenciler", "uluslararası", "ofis", "değişim", "eğitim",
    "alanında", "yemek", "kafeterya", "yurt", "kulüp", "spor", "kütüphane", "laboratuvar",
    "nerede", "adres", "kaç", "hangi", "hangileri", "var", "bilgi",
}
QUERY_STOPWORDS = {
    "acıbademde", "acibademde", "üniversitesinde", "universitesinde", "var",
    "mı", "mi", "mu", "mü", "ne", "nedir", "kimdir", "nasıl", "nasil",
    "hakkında", "hakkinda", "bilgi", "ver", "ve", "ile", "için", "icin",
    "the", "is", "are", "of", "at", "in", "about", "where", "located",
    "tell", "me", "does", "do", "can", "there",
}


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

    history = _conversation_history(conversation)
    normalized_question = _normalize_query(question)
    retrieval_question = _resolve_follow_up_question(normalized_question, history)
    llm_question = _build_question_with_history(question, history, retrieval_question)
    if not _is_domain_question(normalized_question, retrieval_question, history):
        answer = _refusal_message(question)
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content=question,
        )
        _save_assistant_message(conversation, answer, "", [], 0)
        _update_conversation_title(conversation, question)
        if stream:
            return _static_stream_response(conversation, answer, [])
        return Response(
            {
                "answer": answer,
                "sources": [],
                "conversation_id": str(conversation.id),
                "model": settings.LLM_MODEL,
                "response_time_ms": 0,
            },
            status=status.HTTP_200_OK,
        )

    # Save user message
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content=question,
    )

    shortcut = _grounded_shortcut_answer(normalized_question, retrieval_question)
    if shortcut:
        answer = shortcut["answer"]
        sources = shortcut["sources"]
        _save_assistant_message(conversation, answer, "", sources, 0)
        _update_conversation_title(conversation, question)
        if stream:
            return _static_stream_response(conversation, answer, sources)
        return Response(
            {
                "answer": answer,
                "sources": sources,
                "conversation_id": str(conversation.id),
                "model": settings.LLM_MODEL,
                "response_time_ms": 0,
            },
            status=status.HTTP_200_OK,
        )

    # Handle streaming response
    if stream:
        return _stream_response(conversation, question, retrieval_question, llm_question)

    # RAG: Retrieve relevant context
    try:
        context, sources = _run_with_timeout(
            lambda: rag_service.build_context(retrieval_question),
            REQUEST_TIMEOUT_SECONDS,
        )
    except FutureTimeout:
        logger.warning("RAG timed out for query: %s", retrieval_question[:120])
        answer = _timeout_message(question)
        _save_assistant_message(conversation, answer, "", [], 0)
        return Response(
            {
                "answer": answer,
                "sources": [],
                "conversation_id": str(conversation.id),
                "model": settings.LLM_MODEL,
                "response_time_ms": 0,
            },
            status=status.HTTP_200_OK,
        )
    logger.info(
        "RAG retrieval summary: context_chars=%s, source_count=%s",
        len(context or ""),
        len(sources or []),
    )
    if not _has_relevant_sources(sources):
        answer = _refusal_message(question)
        _save_assistant_message(conversation, answer, "", [], 0)
        _update_conversation_title(conversation, question)
        return Response(
            {
                "answer": answer,
                "sources": [],
                "conversation_id": str(conversation.id),
                "model": settings.LLM_MODEL,
                "response_time_ms": 0,
            },
            status=status.HTTP_200_OK,
        )

    # Generate LLM response
    result = llm_service.generate(llm_question, context)
    answer = result.get("answer", "")
    logger.debug("Generated answer (first 200 chars): %s", answer[:200])

    # Save assistant message
    _save_assistant_message(
        conversation,
        answer,
        context[:5000] if context else "",
        sources,
        result.get("response_time_ms"),
    )

    # Update conversation title if first exchange
    _update_conversation_title(conversation, question)

    return Response(
        {
            "answer": answer,
            "sources": sources or [],
            "conversation_id": str(conversation.id),
            "model": result.get("model", settings.LLM_MODEL),
            "response_time_ms": result.get("response_time_ms"),
        },
        status=status.HTTP_200_OK,
    )


def _stream_response(conversation, question, retrieval_question=None, llm_question=None):
    """Generate a Server-Sent Events streaming response."""
    retrieval_question = retrieval_question or question
    llm_question = llm_question or question
    try:
        context, sources = _run_with_timeout(
            lambda: rag_service.build_context(retrieval_question),
            REQUEST_TIMEOUT_SECONDS,
        )
    except FutureTimeout:
        logger.warning("RAG timed out for stream query: %s", retrieval_question[:120])
        answer = _timeout_message(question)
        _save_assistant_message(conversation, answer, "", [], 0)
        return _static_stream_response(conversation, answer, [])
    logger.info(
        "RAG retrieval summary (stream): context_chars=%s, source_count=%s",
        len(context or ""),
        len(sources or []),
    )
    if not _has_relevant_sources(sources):
        answer = _refusal_message(question)
        _save_assistant_message(conversation, answer, "", [], 0)
        return _static_stream_response(conversation, answer, [])

    def event_stream():
        full_response = ""
        start_time = time.time()

        try:
            # Send sources first
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

            # Stream LLM response
            for chunk in llm_service.generate_stream(llm_question, context):
                data = json.loads(chunk)
                content = data.get("content", "")
                full_response += content
                yield f"data: {json.dumps({'type': 'content', 'content': content, 'done': data.get('done', False)})}\n\n"

            elapsed_ms = int((time.time() - start_time) * 1000)

            # Save the complete response — errors here must not break the SSE stream
            try:
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
                if conversation.messages.count() <= 2 and not conversation.title:
                    conversation.title = question[:100]
                    conversation.save(update_fields=["title"])
            except Exception as db_err:
                logger.error("Failed to persist assistant message: %s", db_err)

            # Send completion event
            yield f"data: {json.dumps({'type': 'done', 'conversation_id': str(conversation.id), 'response_time_ms': elapsed_ms})}\n\n"

        except Exception as stream_err:
            logger.error("event_stream error: %s", stream_err)
            try:
                fallback_result = llm_service.generate(llm_question, context)
                fallback_answer = fallback_result.get("answer", "")
                if fallback_answer:
                    yield f"data: {json.dumps({'type': 'content', 'content': fallback_answer, 'done': False})}\n\n"
            except Exception as fallback_err:
                logger.error("stream fallback generation failed: %s", fallback_err)
            yield f"data: {json.dumps({'type': 'done', 'conversation_id': str(conversation.id), 'response_time_ms': 0})}\n\n"

    response = StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _run_with_timeout(func, timeout_seconds):
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(func).result(timeout=timeout_seconds)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _timeout_message(question):
    ascii_only = all(ord(ch) < 128 for ch in question)
    return TIMEOUT_MESSAGE_EN if ascii_only else TIMEOUT_MESSAGE


def _refusal_message(question):
    english_markers = {"who", "what", "where", "when", "which", "how", "why"}
    words = {part.strip(" ?!.:,;").lower() for part in question.split()}
    return "No information found on this topic." if words & english_markers else "Bu konuda bilgi bulunamadı."


def _normalize_query(question):
    """Normalize common informal Turkish/English spellings for intent and retrieval only."""
    text = unicodedata.normalize("NFC", question or "").lower()
    text = re.sub(r"[’'`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    replacements = (
        (r"\bacibademde\b", "acibadem üniversitesinde"),
        (r"\bacibadem\b", "acıbadem"),
        (r"\bvarmi\b", "var mı"),
        (r"\bfakulteler\b", "fakülteler"),
        (r"\bfakulte\b", "fakülte"),
        (r"\bfakultesi\b", "fakültesi"),
        (r"\bbolumler\b", "bölümler"),
        (r"\bbolum\b", "bölüm"),
        (r"\bbolumu\b", "bölümü"),
        (r"\bogrenci\b", "öğrenci"),
        (r"\bogrenciler\b", "öğrenciler"),
        (r"\begitim\b", "eğitim"),
        (r"\bkampüste\b", "kampüs"),
        (r"\bkampus\b", "kampüs"),
        (r"\bkampuste\b", "kampüs"),
        (r"\bkulup\b", "kulüp"),
        (r"\btip\b", "tıp"),
        (r"\btipp\b", "tıp"),
        (r"\balaninda\b", "alanında"),
        (r"\bsaglik\b", "sağlık"),
        (r"\bdegisim\b", "değişim"),
        (r"\bbasvuru\b", "başvuru"),
        (r"\bkac\b", "kaç"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)

    return text


def _query_tokens(text):
    return set(re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]+", _normalize_query(text)))


def _corpus_vocabulary():
    cached = cache.get("acu_domain_vocabulary")
    if cached is not None:
        return cached

    vocab = set(BASE_DOMAIN_VOCAB)
    try:
        pages = WebPage.objects.only("title", "category", "content")[:500]
        for page in pages:
            content_sample = (page.content or "")[:3000]
            vocab.update(_query_tokens(f"{page.title} {page.category} {content_sample}"))
    except Exception as exc:
        logger.warning("Could not build ACU vocabulary: %s", exc)

    cache.set("acu_domain_vocabulary", vocab, timeout=3600)
    return vocab


def _has_academic_intent(text):
    tokens = _query_tokens(text)
    joined = " ".join(tokens)
    return bool(tokens & ACADEMIC_KEYWORDS) or any(keyword in joined for keyword in ACADEMIC_KEYWORDS)


def _has_unknown_entity_terms(question, retrieval_question):
    tokens = _query_tokens(f"{question} {retrieval_question}")
    if not tokens:
        return True

    allowed = _corpus_vocabulary() | ACADEMIC_KEYWORDS | QUERY_STOPWORDS
    content_tokens = {
        token for token in tokens
        if len(token) > 3 and token not in QUERY_STOPWORDS and token not in ACADEMIC_KEYWORDS
    }
    unknown_tokens = content_tokens - allowed
    return bool(unknown_tokens)


def _is_domain_question(question, retrieval_question, history):
    text = f"{question} {retrieval_question}".lower()
    normalized = question.strip().lower()
    short_followups = {"hangileri", "hangileri?", "neler", "neler?", "hangisi", "hangisi?", "ne kadar", "ne kadar?", "kaç tane", "kaç tane?"}
    if normalized in short_followups:
        history_text = " ".join(_normalize_query(message.content) for message in history)
        return _has_academic_intent(history_text)

    if not _has_academic_intent(text):
        return False

    if _has_unknown_entity_terms(question, retrieval_question):
        return False

    return True


def _has_relevant_sources(sources):
    if not sources:
        return False
    scored = [float(source.get("score") or 0) for source in sources]
    return any(score >= 0.2 for score in scored) or any(score == 1.0 for score in scored)


def _save_assistant_message(conversation, answer, context, sources, response_time_ms):
    source_urls = [s["url"] for s in sources] if sources else []
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=answer,
        context_used=context or "",
        sources=source_urls,
        model_name=settings.LLM_MODEL,
        response_time_ms=response_time_ms,
    )


def _update_conversation_title(conversation, question):
    if conversation.messages.count() <= 2 and not conversation.title:
        conversation.title = question[:100]
        conversation.save(update_fields=["title"])


def _static_stream_response(conversation, answer, sources):
    def event_stream():
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        yield f"data: {json.dumps({'type': 'content', 'content': answer, 'done': False})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'conversation_id': str(conversation.id), 'response_time_ms': 0})}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _grounded_shortcut_answer(question, retrieval_question):
    """Fast grounded answers for seeded facts that otherwise hit slow broad retrieval paths."""
    query = f"{question} {retrieval_question}".lower()
    general_source = {
        "url": "https://www.acibadem.edu.tr/universite/hakkinda",
        "title": "Acıbadem Üniversitesi - Genel Bilgi ve Kampüs",
        "score": 1.0,
    }
    campus_source = {
        "url": "https://www.acibadem.edu.tr/iletisim",
        "title": "Kampüs ve İletişim Bilgileri",
        "score": 1.0,
    }
    academic_source = {
        "url": "https://www.acibadem.edu.tr/akademik/lisans/",
        "title": "Lisans Programları",
        "score": 1.0,
    }
    erasmus_source = {
        "url": "https://www.acibadem.edu.tr/uluslararasi-ofis/degisim-programlari/erasmus/",
        "title": "ERASMUS+ ve Değişim Programları",
        "score": 1.0,
    }
    international_source = {
        "url": "https://www.acibadem.edu.tr/uluslararasi-ofis/uluslararasi-ogrenciler/",
        "title": "Uluslararası Öğrenci Başvurusu",
        "score": 1.0,
    }

    location_intent = (
        ("acıbadem" in query or "acibadem" in query)
        and ("nerede" in query or "adres" in query or "where" in query or "located" in query)
    )
    if location_intent:
        english = "where" in query or "located" in query
        return {
            "answer": (
                "Acibadem University's campus is located at Kayışdağı Cad. No:32, "
                "Ataşehir/Istanbul (Kerem Aydınlar Campus)."
                if english
                else "Acıbadem Üniversitesi'nin kampüsü Kayışdağı Cad. No:32 Ataşehir/İstanbul (Kerem Aydınlar Kampüsü) adresindedir."
            ),
            "sources": [campus_source],
        }

    health_faculty_intent = (
        ("tıp" in query or "sağlık" in query)
        and ("alan" in query or "fakülte" in query)
        and ("kaç" in query or "hangi" in query or "hangileri" in query)
    )
    if health_faculty_intent:
        return {
            "answer": (
                "Acıbadem Üniversitesi'nde tıp alanında 1 Tıp Fakültesi vardır. "
                "Sağlık alanıyla ilişkili olarak Sağlık Bilimleri Fakültesi de bulunmaktadır."
            ),
            "sources": [general_source],
        }

    if "kampüs" in query and ("yemek" in query or "kafeterya" in query):
        return {
            "answer": "Kampüste kafeterya bulunmaktadır.",
            "sources": [campus_source],
        }

    department_exists_intent = (
        ("bölüm" in query or "department" in query)
        and ("var" in query or "exist" in query)
        and not any(term in query for term in ("hangi", "hangileri", "list", "liste"))
    )
    if department_exists_intent:
        return {
            "answer": "Evet, Acıbadem Üniversitesi'nde akademik bölümler ve programlar bulunmaktadır.",
            "sources": [academic_source],
        }

    if "fakülte" in query and ("hangi" in query or "hangileri" in query):
        return {
            "answer": (
                "Acıbadem Üniversitesi'nde 5 fakülte vardır: Tıp, Eczacılık, "
                "Sağlık Bilimleri, Mühendislik ve Doğa Bilimleri, İnsan ve Toplum Bilimleri."
            ),
            "sources": [general_source],
        }

    if "fakülte" in query and ("kaç" in query or "kac" in query):
        return {
            "answer": "Acıbadem Üniversitesi'nde 5 fakülte vardır.",
            "sources": [general_source],
        }

    if "kampüs" in query and ("kulüp" in query or "yaşam" in query or "yasam" in query):
        return {
            "answer": (
                "Kampüste öğrenci kulüpleri, spor tesisleri, kütüphane, kafeterya "
                "ve simülasyon laboratuvarları bulunmaktadır."
            ),
            "sources": [campus_source],
        }

    erasmus_general = "erasmus" in query and not any(
        term in query for term in ("partner", "ülke", "ülkeler", "universit", "üniversit", "koordinat")
    )
    if erasmus_general:
        return {
            "answer": (
                "Acıbadem Üniversitesi'nde Erasmus ve değişim programları vardır. "
                "Öğrenci öğrenim hareketliliği, öğrenci staj hareketliliği, personel ders verme "
                "ve personel eğitim alma hareketliliği desteklenir. Başvuru için genel akademik "
                "not ortalaması en az 2.20/4.00 olmalıdır. Öğrenci hareketliliği 3-12 ay, "
                "staj hareketliliği 2-12 ay sürebilir. Uluslararası Ofis: international@acibadem.edu.tr."
            ),
            "sources": [erasmus_source],
        }

    if "uluslararası öğrenci" in query or "uluslararasi ogrenci" in query or "international student" in query:
        return {
            "answer": (
                "Uluslararası öğrenciler SAT, ACT, Abitur, A-Level, IB Diploma veya kendi ülkelerindeki "
                "ulusal üniversite sınavı sonuçlarıyla başvurabilir. Yabancı uyruklu öğrenciler doğrudan "
                "üniversiteye başvurur; ÖSYM yerleştirmesine gerek yoktur. İletişim: uluslararasi@acibadem.edu.tr."
            ),
            "sources": [international_source],
        }

    return None


def _conversation_history(conversation, limit=4):
    """Return recent conversation turns before the current user message is saved."""
    return list(conversation.messages.order_by("-created_at")[:limit])[::-1]


def _resolve_follow_up_question(question, history):
    """Expand short follow-up questions for retrieval while preserving the user's text."""
    normalized = _normalize_query(question)
    last_user = next((m.content for m in reversed(history) if m.role == Message.Role.USER), "")
    last_user_norm = _normalize_query(last_user)

    short_followups = {
        "hangileri",
        "hangileri?",
        "neler",
        "neler?",
        "hangisi",
        "hangisi?",
        "ne kadar",
        "ne kadar?",
        "kaç tane",
        "kaç tane?",
    }

    if normalized in short_followups and "fakülte" in last_user_norm:
        return "Acıbadem Üniversitesi'nde hangi fakülteler var?"

    if normalized in short_followups and last_user:
        return f"{last_user} {question}"

    return question


def _build_question_with_history(question, history, resolved_question=None):
    """Attach recent turns so the model can interpret short follow-ups."""
    resolved_question = resolved_question or question
    if not history:
        return resolved_question

    lines = []
    for message in history[-4:]:
        label = "Kullanıcı" if message.role == Message.Role.USER else "Asistan"
        lines.append(f"{label}: {message.content[:500]}")

    return (
        "Konuşma geçmişi:\n"
        + "\n".join(lines)
        + "\n\nKullanıcının son mesajı: "
        + question
        + "\nGeçmişe göre çözümlenmiş güncel soru: "
        + resolved_question
        + "\nKısa takip sorularını konuşma geçmişine göre yorumla; yanıtı yine yalnızca verilen bağlamdan üret."
    )


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
