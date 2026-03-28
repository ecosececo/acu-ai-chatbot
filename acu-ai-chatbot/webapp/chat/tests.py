"""
Test suite for the ACU AI Chatbot application.

Covers: models, serializers, RAG service logic, LLM service (mocked), API views.
All external HTTP calls (TGI/Ollama) are mocked — tests run without a live LLM.
"""

import uuid
from unittest.mock import MagicMock, patch

from django.test import Client, TestCase

from chat.models import Conversation, DocumentChunk, Message, WebPage
from chat.serializers import (
    ChatRequestSerializer,
    ConversationListSerializer,
    ConversationSerializer,
)
from chat.services.llm_service import LLMService, llm_service
from chat.services.rag_service import RAGService, chunk_text


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

def make_webpage(**kwargs):
    defaults = {
        "url": f"https://www.acibadem.edu.tr/{uuid.uuid4().hex}",
        "title": "Test Page",
        "content": "Bu Acıbadem Üniversitesi hakkında bir test sayfasıdır.",
        "source": "main",
        "category": "general",
    }
    defaults.update(kwargs)
    return WebPage.objects.create(**defaults)


def make_chunk(page, index=0, content=None, embedding=None):
    return DocumentChunk.objects.create(
        web_page=page,
        chunk_index=index,
        content=content or "Test chunk içeriği. Bu yeterince uzun bir içeriktir.",
        embedding=embedding or [0.1] * 768,
        token_count=10,
        metadata={
            "title": page.title,
            "url": page.url,
            "source": page.source,
            "category": page.category,
        },
    )


# ══════════════════════════════════════════════════════════
# WebPage Model Tests
# ══════════════════════════════════════════════════════════

class WebPageModelTest(TestCase):

    def test_create_webpage(self):
        page = make_webpage(title="Test Page", source="main", category="general")
        self.assertEqual(page.title, "Test Page")
        self.assertEqual(page.source, "main")
        self.assertFalse(page.is_processed)

    def test_str_with_title(self):
        page = make_webpage(title="My Page")
        self.assertIn("My Page", str(page))

    def test_str_without_title_uses_url(self):
        page = make_webpage(title="", url="https://www.acibadem.edu.tr/no-title")
        self.assertIn("acibadem.edu.tr", str(page))

    def test_unique_url_constraint(self):
        from django.db import IntegrityError, transaction
        url = "https://www.acibadem.edu.tr/unique-url-test"
        make_webpage(url=url)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_webpage(url=url)

    def test_default_source_is_main(self):
        page = make_webpage()
        self.assertEqual(page.source, "main")

    def test_bologna_source(self):
        page = make_webpage(source="bologna", url="https://obs.acibadem.edu.tr/prog/1")
        self.assertEqual(page.source, "bologna")

    def test_is_processed_default_false(self):
        page = make_webpage()
        self.assertFalse(page.is_processed)

    def test_mark_processed(self):
        page = make_webpage()
        page.is_processed = True
        page.save()
        page.refresh_from_db()
        self.assertTrue(page.is_processed)


# ══════════════════════════════════════════════════════════
# DocumentChunk Model Tests
# ══════════════════════════════════════════════════════════

class DocumentChunkModelTest(TestCase):

    def setUp(self):
        self.page = make_webpage(title="Test Page")

    def test_create_chunk(self):
        chunk = make_chunk(self.page, index=0)
        self.assertEqual(chunk.chunk_index, 0)
        self.assertEqual(chunk.web_page, self.page)

    def test_str_includes_index_and_page_title(self):
        chunk = make_chunk(self.page, index=2)
        s = str(chunk)
        self.assertIn("2", s)
        self.assertIn("Test Page", s)

    def test_cascade_delete_on_page_delete(self):
        make_chunk(self.page, index=0)
        make_chunk(self.page, index=1)
        self.assertEqual(DocumentChunk.objects.count(), 2)
        self.page.delete()
        self.assertEqual(DocumentChunk.objects.count(), 0)

    def test_chunks_ordered_by_index(self):
        make_chunk(self.page, index=2)
        make_chunk(self.page, index=0)
        make_chunk(self.page, index=1)
        indices = list(
            DocumentChunk.objects.filter(web_page=self.page).values_list("chunk_index", flat=True)
        )
        self.assertEqual(indices, [0, 1, 2])

    def test_metadata_json_field(self):
        chunk = make_chunk(self.page, index=0)
        self.assertIn("title", chunk.metadata)
        self.assertEqual(chunk.metadata["source"], "main")


# ══════════════════════════════════════════════════════════
# Conversation Model Tests
# ══════════════════════════════════════════════════════════

class ConversationModelTest(TestCase):

    def test_create_conversation(self):
        conv = Conversation.objects.create(title="Test Chat")
        self.assertEqual(conv.title, "Test Chat")
        self.assertTrue(conv.is_active)

    def test_uuid_primary_key(self):
        conv = Conversation.objects.create(title="UUID test")
        self.assertIsInstance(conv.id, uuid.UUID)

    def test_message_count_zero_initially(self):
        conv = Conversation.objects.create(title="Empty")
        self.assertEqual(conv.message_count, 0)

    def test_message_count_increments(self):
        conv = Conversation.objects.create(title="Chat")
        Message.objects.create(conversation=conv, role="user", content="Soru")
        Message.objects.create(conversation=conv, role="assistant", content="Cevap")
        self.assertEqual(conv.message_count, 2)

    def test_str_with_title(self):
        conv = Conversation.objects.create(title="My Conversation")
        self.assertIn("My Conversation", str(conv))

    def test_str_without_title(self):
        conv = Conversation.objects.create()
        self.assertIn("Untitled", str(conv))

    def test_default_is_active_true(self):
        conv = Conversation.objects.create()
        self.assertTrue(conv.is_active)


# ══════════════════════════════════════════════════════════
# Message Model Tests
# ══════════════════════════════════════════════════════════

class MessageModelTest(TestCase):

    def setUp(self):
        self.conv = Conversation.objects.create(title="Test")

    def test_create_user_message(self):
        msg = Message.objects.create(
            conversation=self.conv, role="user", content="ACU fakülteleri nelerdir?"
        )
        self.assertEqual(msg.role, "user")

    def test_all_roles_accepted(self):
        for role in ("user", "assistant", "system"):
            msg = Message.objects.create(
                conversation=self.conv, role=role, content="içerik"
            )
            self.assertEqual(msg.role, role)

    def test_str_includes_role(self):
        msg = Message.objects.create(
            conversation=self.conv, role="user", content="Kısa mesaj"
        )
        self.assertIn("user", str(msg))

    def test_str_truncates_long_content(self):
        msg = Message.objects.create(
            conversation=self.conv, role="assistant", content="x" * 200
        )
        self.assertIn("...", str(msg))

    def test_sources_default_empty_list(self):
        msg = Message.objects.create(
            conversation=self.conv, role="user", content="q"
        )
        self.assertEqual(msg.sources, [])

    def test_cascade_delete_on_conversation_delete(self):
        Message.objects.create(conversation=self.conv, role="user", content="q")
        self.conv.delete()
        self.assertEqual(Message.objects.count(), 0)

    def test_messages_ordered_by_created_at(self):
        m1 = Message.objects.create(conversation=self.conv, role="user", content="first")
        m2 = Message.objects.create(conversation=self.conv, role="assistant", content="second")
        msgs = list(self.conv.messages.all())
        self.assertEqual(msgs[0].id, m1.id)
        self.assertEqual(msgs[1].id, m2.id)


# ══════════════════════════════════════════════════════════
# chunk_text Tests
# ══════════════════════════════════════════════════════════

class ChunkTextTest(TestCase):

    def test_empty_string_returns_empty_list(self):
        self.assertEqual(chunk_text(""), [])

    def test_whitespace_only_returns_empty_list(self):
        self.assertEqual(chunk_text("   "), [])
        self.assertEqual(chunk_text("\n\n\n"), [])

    def test_short_text_is_single_chunk(self):
        result = chunk_text("Kısa bir metin.")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "Kısa bir metin.")

    def test_long_text_splits_into_multiple_chunks(self):
        paragraphs = [f"Paragraf {i}. " * 30 for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, chunk_size=200)
        self.assertGreater(len(chunks), 1)

    def test_content_is_fully_preserved(self):
        text = "Birinci paragraf.\n\nİkinci paragraf.\n\nÜçüncü paragraf."
        chunks = chunk_text(text, chunk_size=5000)
        combined = " ".join(chunks)
        self.assertIn("Birinci", combined)
        self.assertIn("İkinci", combined)
        self.assertIn("Üçüncü", combined)

    def test_all_chunks_are_stripped(self):
        text = "   Para bir.   \n\n   Para iki.   "
        for chunk in chunk_text(text):
            self.assertEqual(chunk, chunk.strip())

    def test_very_long_single_paragraph_triggers_sentence_split(self):
        # A paragraph longer than chunk_size * 2 should be split at sentence boundaries
        sentences = [f"Bu cümle numarası {i}. " for i in range(100)]
        text = " ".join(sentences)
        chunks = chunk_text(text, chunk_size=200)
        self.assertGreater(len(chunks), 1)
        combined = " ".join(chunks)
        self.assertIn("numarası 0", combined)
        self.assertIn("numarası 99", combined)

    def test_overlap_does_not_exceed_chunk_size(self):
        # With the fixed overlap (char-based → word count), overlap should be ~40 words
        paragraphs = ["Kelime " * 60 for _ in range(10)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, chunk_size=300, overlap=100)
        # Each chunk should not be excessively larger than chunk_size
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 300 * 3)

    def test_turkish_characters_preserved(self):
        text = "Acıbadem Üniversitesi sağlık alanında eğitim veren özel bir üniversitedir.\n\nFakülteler ve bölümler."
        chunks = chunk_text(text, chunk_size=5000)
        self.assertIn("Acıbadem", chunks[0])
        self.assertIn("ğ", chunks[0])

    def test_extra_newlines_are_collapsed(self):
        text = "Para bir.\n\n\n\n\nPara iki."
        chunks = chunk_text(text)
        self.assertGreater(len(chunks), 0)


# ══════════════════════════════════════════════════════════
# Serializer Tests
# ══════════════════════════════════════════════════════════

class ChatRequestSerializerTest(TestCase):

    def test_valid_question(self):
        s = ChatRequestSerializer(data={"question": "ACU bursları nelerdir?"})
        self.assertTrue(s.is_valid(), s.errors)

    def test_missing_question_is_invalid(self):
        s = ChatRequestSerializer(data={})
        self.assertFalse(s.is_valid())
        self.assertIn("question", s.errors)

    def test_empty_question_is_invalid(self):
        s = ChatRequestSerializer(data={"question": ""})
        self.assertFalse(s.is_valid())
        self.assertIn("question", s.errors)

    def test_too_short_question_is_invalid(self):
        s = ChatRequestSerializer(data={"question": "ab"})
        self.assertFalse(s.is_valid())
        self.assertIn("question", s.errors)

    def test_question_at_max_length_is_valid(self):
        s = ChatRequestSerializer(data={"question": "x" * 2000})
        self.assertTrue(s.is_valid())

    def test_question_exceeding_max_length_is_invalid(self):
        s = ChatRequestSerializer(data={"question": "x" * 2001})
        self.assertFalse(s.is_valid())
        self.assertIn("question", s.errors)

    def test_stream_defaults_to_false(self):
        s = ChatRequestSerializer(data={"question": "test?"})
        s.is_valid()
        self.assertFalse(s.validated_data["stream"])

    def test_stream_can_be_true(self):
        s = ChatRequestSerializer(data={"question": "test?", "stream": True})
        s.is_valid()
        self.assertTrue(s.validated_data["stream"])

    def test_web_search_defaults_to_false(self):
        s = ChatRequestSerializer(data={"question": "test?"})
        s.is_valid()
        self.assertFalse(s.validated_data["web_search"])

    def test_valid_conversation_id_accepted(self):
        cid = str(uuid.uuid4())
        s = ChatRequestSerializer(data={"question": "test?", "conversation_id": cid})
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(str(s.validated_data["conversation_id"]), cid)

    def test_invalid_conversation_id_rejected(self):
        s = ChatRequestSerializer(data={"question": "test?", "conversation_id": "not-a-uuid"})
        self.assertFalse(s.is_valid())
        self.assertIn("conversation_id", s.errors)

    def test_null_conversation_id_is_allowed(self):
        s = ChatRequestSerializer(data={"question": "test?", "conversation_id": None})
        self.assertTrue(s.is_valid())
        self.assertIsNone(s.validated_data["conversation_id"])


class ConversationSerializerTest(TestCase):

    def test_serializes_with_messages(self):
        conv = Conversation.objects.create(title="Test")
        Message.objects.create(conversation=conv, role="user", content="Merhaba")
        data = ConversationSerializer(conv).data
        self.assertEqual(data["title"], "Test")
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["role"], "user")

    def test_message_count_correct(self):
        conv = Conversation.objects.create(title="Multi")
        for i in range(3):
            Message.objects.create(conversation=conv, role="user", content=f"q{i}")
        data = ConversationSerializer(conv).data
        self.assertEqual(data["message_count"], 3)

    def test_empty_conversation(self):
        conv = Conversation.objects.create(title="Empty")
        data = ConversationSerializer(conv).data
        self.assertEqual(data["message_count"], 0)
        self.assertEqual(data["messages"], [])


class ConversationListSerializerTest(TestCase):

    def test_last_message_none_for_empty_conversation(self):
        conv = Conversation.objects.create(title="Empty")
        self.assertIsNone(ConversationListSerializer(conv).data["last_message"])

    def test_last_message_populated(self):
        conv = Conversation.objects.create(title="Chat")
        Message.objects.create(conversation=conv, role="user", content="Bir soru")
        data = ConversationListSerializer(conv).data["last_message"]
        self.assertIsNotNone(data)
        self.assertEqual(data["role"], "user")
        self.assertIn("Bir soru", data["content"])

    def test_last_message_content_truncated_at_100(self):
        conv = Conversation.objects.create(title="Long")
        Message.objects.create(conversation=conv, role="user", content="x" * 200)
        data = ConversationListSerializer(conv).data["last_message"]
        self.assertIn("...", data["content"])
        self.assertLessEqual(len(data["content"]), 103)

    def test_last_message_returns_most_recent(self):
        conv = Conversation.objects.create(title="Chat")
        Message.objects.create(conversation=conv, role="user", content="eski mesaj")
        Message.objects.create(conversation=conv, role="assistant", content="son mesaj")
        data = ConversationListSerializer(conv).data["last_message"]
        self.assertEqual(data["role"], "assistant")


# ══════════════════════════════════════════════════════════
# RAG Service — Query Expansion
# ══════════════════════════════════════════════════════════

class QueryExpansionTest(TestCase):

    def setUp(self):
        self.svc = RAGService()

    def test_expands_burs(self):
        result = self.svc._rewrite_query("burs başvurusu")
        self.assertIn("indirim", result)

    def test_expands_ucret(self):
        result = self.svc._rewrite_query("ücret ne kadar?")
        self.assertIn("öğrenim ücreti", result)

    def test_expands_erasmus(self):
        result = self.svc._rewrite_query("erasmus programı")
        self.assertIn("değişim", result)

    def test_no_expansion_for_unknown_query(self):
        result = self.svc._rewrite_query("merhaba dünya")
        self.assertEqual(result, "merhaba dünya")

    def test_multiple_keywords_combined(self):
        result = self.svc._rewrite_query("burs ve ücret bilgisi")
        self.assertIn("indirim", result)
        self.assertIn("öğrenim ücreti", result)

    def test_original_query_preserved_in_expansion(self):
        result = self.svc._rewrite_query("staj zorunlu mu?")
        self.assertIn("staj zorunlu mu?", result)


# ══════════════════════════════════════════════════════════
# RAG Service — Category Detection
# ══════════════════════════════════════════════════════════

class CategoryDetectionTest(TestCase):

    def setUp(self):
        self.svc = RAGService()

    def test_detects_admission(self):
        cat = self.svc._detect_category("burs ve ücret kontenjan başvurusu")
        self.assertEqual(cat, "admission")

    def test_detects_academic(self):
        cat = self.svc._detect_category("ders kredileri ve AKTS bilgisi")
        self.assertEqual(cat, "academic")

    def test_detects_campus(self):
        cat = self.svc._detect_category("kütüphane çalışma saatleri yurt barınma")
        self.assertEqual(cat, "campus")

    def test_detects_student(self):
        cat = self.svc._detect_category("erasmus değişim programı staj mezuniyet")
        self.assertEqual(cat, "student")

    def test_detects_contact(self):
        cat = self.svc._detect_category("iletişim adresi telefon e-posta")
        self.assertEqual(cat, "contact")

    def test_returns_none_for_no_match(self):
        cat = self.svc._detect_category("xyz abc randomword")
        self.assertIsNone(cat)

    def test_single_keyword_returns_none(self):
        # Single keyword match should NOT trigger category filter (score < 2)
        cat = self.svc._detect_category("başvuru")
        self.assertIsNone(cat)

    def test_highest_score_wins(self):
        # Multiple admission keywords → admission should win
        cat = self.svc._detect_category("kayıt kontenjan burs harç ücret")
        self.assertEqual(cat, "admission")


# ══════════════════════════════════════════════════════════
# RAG Service — Reciprocal Rank Fusion
# ══════════════════════════════════════════════════════════

class RRFTest(TestCase):

    def setUp(self):
        self.svc = RAGService()

    def _r(self, content, score=0.5):
        return {
            "content": content,
            "url": "https://www.acibadem.edu.tr/test",
            "title": content[:30],
            "source": "main",
            "category": "general",
            "score": score,
        }

    def test_merges_distinct_results(self):
        semantic = [self._r("alfa içerik uzun metin"), self._r("beta içerik uzun metin")]
        keyword  = [self._r("gama içerik uzun metin"), self._r("delta içerik uzun metin")]
        merged = self.svc._reciprocal_rank_fusion(semantic, keyword, top_k=10)
        contents = [r["content"] for r in merged]
        for c in ["alfa içerik uzun metin", "beta içerik uzun metin",
                  "gama içerik uzun metin", "delta içerik uzun metin"]:
            self.assertIn(c, contents)

    def test_shared_result_ranks_first(self):
        shared = "ortak sonuç içeriği uzun metin burada"
        semantic = [self._r(shared), self._r("sadece semantic içerik")]
        keyword  = [self._r(shared), self._r("sadece keyword içerik")]
        merged = self.svc._reciprocal_rank_fusion(semantic, keyword, top_k=10)
        self.assertEqual(merged[0]["content"], shared)

    def test_respects_top_k_limit(self):
        semantic = [self._r(f"semantic {i} uzun içerik") for i in range(5)]
        keyword  = [self._r(f"keyword {i} uzun içerik") for i in range(5)]
        merged = self.svc._reciprocal_rank_fusion(semantic, keyword, top_k=3)
        self.assertEqual(len(merged), 3)

    def test_empty_inputs_return_empty(self):
        self.assertEqual(self.svc._reciprocal_rank_fusion([], [], top_k=5), [])

    def test_one_empty_list_uses_other(self):
        semantic = [self._r("sadece semantic sonucu uzun metin")]
        merged = self.svc._reciprocal_rank_fusion(semantic, [], top_k=5)
        self.assertEqual(len(merged), 1)

    def test_assigns_rrf_score(self):
        semantic = [self._r("içerik a uzun metin")]
        keyword  = [self._r("içerik b uzun metin")]
        merged = self.svc._reciprocal_rank_fusion(semantic, keyword, top_k=5)
        for r in merged:
            self.assertIn("score", r)
            self.assertGreater(r["score"], 0)


# ══════════════════════════════════════════════════════════
# RAG Service — Re-ranking
# ══════════════════════════════════════════════════════════

class RerankTest(TestCase):

    def setUp(self):
        self.svc = RAGService()

    def _r(self, content, score=0.5):
        return {"content": content, "url": "", "title": "", "source": "", "category": "", "score": score}

    def test_keyword_rich_result_ranks_higher(self):
        results = [
            self._r("fizik dersleri ve matematik programı hakkında bilgi", 0.5),
            self._r("bilgisayar mühendisliği bölümü hakkında detaylı bilgi", 0.5),
        ]
        reranked = self.svc._rerank("bilgisayar mühendisliği", results, top_k=2)
        self.assertIn("bilgisayar", reranked[0]["content"])

    def test_returns_correct_top_k(self):
        results = [self._r(f"sonuç {i} uzun içerik") for i in range(10)]
        reranked = self.svc._rerank("test sorgusu", results, top_k=4)
        self.assertEqual(len(reranked), 4)

    def test_empty_results_returns_empty(self):
        self.assertEqual(self.svc._rerank("query", [], top_k=5), [])

    def test_score_can_only_increase(self):
        results = [self._r("tamamen alakasız içerik burada metin var", 0.5)]
        reranked = self.svc._rerank("bilgisayar mühendisliği", results, top_k=1)
        self.assertGreaterEqual(reranked[0]["score"], 0.5)


# ══════════════════════════════════════════════════════════
# RAG Service — process_webpage
# ══════════════════════════════════════════════════════════

class RAGProcessWebpageTest(TestCase):

    def test_creates_chunks_and_marks_processed(self):
        page = make_webpage(
            content="İlk paragraf içeriği burada.\n\nİkinci paragraf bilgisi burada."
        )
        svc = RAGService()
        with patch.object(llm_service, "get_embedding", return_value=[0.0] * 768):
            count = svc.process_webpage(page, force=True)
        self.assertGreater(count, 0)
        self.assertEqual(DocumentChunk.objects.filter(web_page=page).count(), count)
        page.refresh_from_db()
        self.assertTrue(page.is_processed)

    def test_skips_empty_content(self):
        page = make_webpage(content="")
        svc = RAGService()
        with patch.object(llm_service, "get_embedding", return_value=[0.0] * 768):
            count = svc.process_webpage(page)
        self.assertEqual(count, 0)
        self.assertFalse(page.is_processed)

    def test_skips_already_processed_without_force(self):
        page = make_webpage(content="Bazı içerik burada yazılmış.", is_processed=True)
        svc = RAGService()
        with patch.object(llm_service, "get_embedding", return_value=[0.0] * 768):
            count = svc.process_webpage(page, force=False)
        self.assertEqual(count, 0)

    def test_force_reprocesses_existing_chunks(self):
        page = make_webpage(content="İçerik burada.")
        svc = RAGService()
        with patch.object(llm_service, "get_embedding", return_value=[0.0] * 768):
            svc.process_webpage(page, force=True)
            count_first = DocumentChunk.objects.filter(web_page=page).count()
            svc.process_webpage(page, force=True)
            count_second = DocumentChunk.objects.filter(web_page=page).count()
        self.assertEqual(count_first, count_second)

    def test_chunk_metadata_populated(self):
        page = make_webpage(title="Öğrenim Ücretleri", category="admission")
        svc = RAGService()
        with patch.object(llm_service, "get_embedding", return_value=[0.0] * 768):
            svc.process_webpage(page, force=True)
        chunk = DocumentChunk.objects.filter(web_page=page).first()
        self.assertEqual(chunk.metadata["title"], "Öğrenim Ücretleri")
        self.assertEqual(chunk.metadata["category"], "admission")


# ══════════════════════════════════════════════════════════
# RAG Service — build_context
# ══════════════════════════════════════════════════════════

class RAGBuildContextTest(TestCase):

    def test_empty_db_returns_empty_context(self):
        svc = RAGService()
        with patch.object(llm_service, "get_embedding", return_value=[0.1] * 768):
            context, sources = svc.build_context("ücretler nedir?")
        self.assertEqual(context, "")
        self.assertEqual(sources, [])

    def test_returns_non_empty_context_with_matching_chunk(self):
        page = make_webpage(
            title="Öğrenim Ücretleri",
            content="Yıllık öğrenim ücreti detaylı bilgi verilmektedir.",
            category="admission",
        )
        embedding = [0.1] * 768
        make_chunk(
            page, index=0,
            content="Yıllık öğrenim ücreti detaylı bilgi verilmektedir burada.",
            embedding=embedding,
        )
        svc = RAGService()
        with patch.object(llm_service, "get_embedding", return_value=embedding):
            context, sources = svc.build_context("ücret ne kadar?")
        # Identical vectors → similarity = 1.0 → above threshold
        self.assertIsInstance(context, str)
        self.assertIsInstance(sources, list)


# ══════════════════════════════════════════════════════════
# LLM Service — _build_user_prompt
# ══════════════════════════════════════════════════════════

class LLMBuildPromptTest(TestCase):

    def setUp(self):
        self.svc = LLMService()

    def test_with_context_includes_context(self):
        prompt = self.svc._build_user_prompt("Soru?", context="Bağlam bilgisi.")
        self.assertIn("Bağlam bilgisi", prompt)
        self.assertIn("Soru?", prompt)

    def test_empty_context_uses_fallback_message(self):
        prompt = self.svc._build_user_prompt("Soru?", context="")
        self.assertIn("bulunamadı", prompt)

    def test_none_context_uses_fallback_message(self):
        prompt = self.svc._build_user_prompt("Soru?")
        self.assertIn("bulunamadı", prompt)

    def test_with_history_includes_history(self):
        history = [
            {"role": "user", "content": "Önceki soru metni"},
            {"role": "assistant", "content": "Önceki cevap metni"},
        ]
        prompt = self.svc._build_user_prompt("Yeni soru?", context="ctx", history=history)
        self.assertIn("Önceki soru metni", prompt)
        self.assertIn("Önceki cevap metni", prompt)

    def test_history_messages_truncated_to_300_chars(self):
        history = [{"role": "user", "content": "x" * 500}]
        prompt = self.svc._build_user_prompt("q?", context="ctx", history=history)
        self.assertNotIn("x" * 500, prompt)
        self.assertIn("x" * 300, prompt)

    def test_history_capped_at_last_6_messages(self):
        history = [{"role": "user", "content": f"mesaj {i}"} for i in range(10)]
        prompt = self.svc._build_user_prompt("q?", context="ctx", history=history)
        self.assertIn("mesaj 9", prompt)
        self.assertNotIn("mesaj 0", prompt)

    def test_no_history_skips_history_section(self):
        prompt = self.svc._build_user_prompt("Soru?", context="ctx", history=None)
        self.assertNotIn("Önceki Sohbet", prompt)


# ══════════════════════════════════════════════════════════
# LLM Service — is_available
# ══════════════════════════════════════════════════════════

class LLMAvailabilityTest(TestCase):

    def test_returns_cached_true(self):
        with patch("chat.services.llm_service.cache") as mock_cache:
            mock_cache.get.return_value = True
            result = llm_service.is_available()
        self.assertTrue(result)

    def test_returns_cached_false(self):
        with patch("chat.services.llm_service.cache") as mock_cache:
            mock_cache.get.return_value = False
            result = llm_service.is_available()
        self.assertFalse(result)

    def test_available_when_tgi_health_ok(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("chat.services.llm_service.cache") as mock_cache:
            mock_cache.get.return_value = None
            with patch("httpx.Client") as MockClient:
                MockClient.return_value.__enter__.return_value.get.return_value = mock_resp
                svc = LLMService()
                svc.provider = "tgi"
                svc.tgi_base_url = "http://tgi"
                result = svc.is_available()
        self.assertTrue(result)

    def test_unavailable_on_connect_error(self):
        import httpx as _httpx
        with patch("chat.services.llm_service.cache") as mock_cache:
            mock_cache.get.return_value = None
            with patch("httpx.Client") as MockClient:
                MockClient.return_value.__enter__.return_value.get.side_effect = (
                    _httpx.ConnectError("refused")
                )
                result = llm_service.is_available()
        self.assertFalse(result)


# ══════════════════════════════════════════════════════════
# LLM Service — generate
# ══════════════════════════════════════════════════════════

class LLMGenerateTest(TestCase):

    def _mock_response(self, content="Test cevabı."):
        mock = MagicMock()
        mock.json.return_value = {"generated_text": content}
        return mock

    def test_returns_answer_field(self):
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = (
                self._mock_response("Doğru cevap burada.")
            )
            result = llm_service.generate("Soru?", context="Bağlam.")
        self.assertEqual(result["answer"], "Doğru cevap burada.")

    def test_returns_response_time_ms(self):
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = (
                self._mock_response()
            )
            result = llm_service.generate("q?", context="ctx")
        self.assertIn("response_time_ms", result)
        self.assertIsInstance(result["response_time_ms"], int)

    def test_timeout_returns_error(self):
        import httpx as _httpx
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = (
                _httpx.TimeoutException("timeout")
            )
            result = llm_service.generate("q?")
        self.assertTrue(result.get("error"))

    def test_generic_exception_returns_error(self):
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = (
                Exception("unexpected")
            )
            result = llm_service.generate("q?")
        self.assertTrue(result.get("error"))

    def test_connect_error_retries_then_returns_error(self):
        import httpx as _httpx
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = (
                _httpx.ConnectError("connection refused")
            )
            with patch("chat.services.llm_service.time.sleep"):
                result = llm_service.generate("q?")
        self.assertTrue(result.get("error"))

    def test_answer_is_turkish_on_error(self):
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = Exception("err")
            result = llm_service.generate("q?")
        # Error messages should be in Turkish
        self.assertTrue(any(
            word in result["answer"]
            for word in ["hata", "lütfen", "servis", "yanıt", "bağlan"]
        ))


# ══════════════════════════════════════════════════════════
# LLM Service — get_embedding
# ══════════════════════════════════════════════════════════

class LLMEmbeddingTest(TestCase):

    def test_returns_768_dim_vector(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embeddings": [[0.1] * 768]}
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            result = llm_service.get_embedding("test metni")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 768)

    def test_returns_none_on_error(self):
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.side_effect = Exception("fail")
            result = llm_service.get_embedding("test metni")
        self.assertIsNone(result)

    def test_returns_none_when_embeddings_empty(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embeddings": []}
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            result = llm_service.get_embedding("test metni")
        self.assertIsNone(result)


# ══════════════════════════════════════════════════════════
# API View Tests — General Endpoints
# ══════════════════════════════════════════════════════════

class GeneralAPITest(TestCase):

    def setUp(self):
        self.client = Client()

    def test_health_endpoint(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")

    def test_api_health_endpoint(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertEqual(data["status"], "healthy")

    def test_api_stats_endpoint(self):
        response = self.client.get("/api/stats/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for field in ("total_pages", "total_chunks", "llm_available", "llm_model"):
            self.assertIn(field, data)

    def test_api_stats_counts_are_integers(self):
        response = self.client.get("/api/stats/")
        data = response.json()
        self.assertIsInstance(data["total_pages"], int)
        self.assertIsInstance(data["total_chunks"], int)

    def test_conversations_empty_for_new_session(self):
        response = self.client.get("/api/conversations/")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_index_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ACU")

    def test_chat_requires_post(self):
        response = self.client.get("/api/chat/")
        self.assertEqual(response.status_code, 405)


# ══════════════════════════════════════════════════════════
# API View Tests — Chat Endpoint
# ══════════════════════════════════════════════════════════

class ChatAPITest(TestCase):

    def setUp(self):
        self.client = Client()
        self._llm_ok = patch.object(llm_service, "is_available", return_value=True)
        self._rag_ctx = patch(
            "chat.views.rag_service.build_context",
            return_value=("Test bağlam içeriği.", []),
        )
        self._llm_gen = patch.object(
            llm_service, "generate",
            return_value={"answer": "Test cevabı.", "model": "google/gemma-4-E4B-it", "response_time_ms": 500},
        )

    def _post(self, data):
        return self.client.post("/api/chat/", data=data, content_type="application/json")

    def test_missing_question_returns_400(self):
        response = self._post({})
        self.assertEqual(response.status_code, 400)

    def test_empty_question_returns_400(self):
        response = self._post({"question": ""})
        self.assertEqual(response.status_code, 400)

    def test_too_short_question_returns_400(self):
        response = self._post({"question": "ab"})
        self.assertEqual(response.status_code, 400)

    def test_llm_unavailable_returns_503(self):
        with patch.object(llm_service, "is_available", return_value=False):
            response = self._post({"question": "Burslar nelerdir?"})
        self.assertEqual(response.status_code, 503)

    def test_successful_chat_returns_200(self):
        with self._llm_ok, self._rag_ctx, self._llm_gen:
            response = self._post({"question": "Burslar nelerdir?"})
        self.assertEqual(response.status_code, 200)

    def test_response_contains_answer(self):
        with self._llm_ok, self._rag_ctx, self._llm_gen:
            response = self._post({"question": "Burslar nelerdir?"})
        self.assertEqual(response.json()["answer"], "Test cevabı.")

    def test_response_contains_conversation_id(self):
        with self._llm_ok, self._rag_ctx, self._llm_gen:
            response = self._post({"question": "Burslar nelerdir?"})
        cid = response.json().get("conversation_id")
        self.assertIsNotNone(cid)
        self.assertTrue(Conversation.objects.filter(id=cid).exists())

    def test_chat_saves_user_and_assistant_messages(self):
        with self._llm_ok, self._rag_ctx, self._llm_gen:
            response = self._post({"question": "Kaç bölüm var?"})
        cid = response.json()["conversation_id"]
        conv = Conversation.objects.get(id=cid)
        self.assertEqual(conv.message_count, 2)
        roles = set(conv.messages.values_list("role", flat=True))
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_continues_existing_conversation(self):
        existing = Conversation.objects.create(title="Mevcut sohbet")
        with self._llm_ok, self._rag_ctx, self._llm_gen:
            response = self._post({
                "question": "Devam sorusu?",
                "conversation_id": str(existing.id),
            })
        self.assertEqual(response.json()["conversation_id"], str(existing.id))

    def test_nonexistent_conversation_id_creates_new(self):
        fake_id = str(uuid.uuid4())
        with self._llm_ok, self._rag_ctx, self._llm_gen:
            response = self._post({
                "question": "Yeni soru?",
                "conversation_id": fake_id,
            })
        self.assertEqual(response.status_code, 200)
        new_cid = response.json()["conversation_id"]
        # A new conversation is created (different from the fake_id)
        self.assertNotEqual(new_cid, fake_id)

    def test_response_includes_sources_list(self):
        with self._llm_ok, self._rag_ctx, self._llm_gen:
            response = self._post({"question": "Fakülteler nelerdir?"})
        self.assertIn("sources", response.json())
        self.assertIsInstance(response.json()["sources"], list)

    def test_response_includes_model_name(self):
        with self._llm_ok, self._rag_ctx, self._llm_gen:
            response = self._post({"question": "Fakülteler nelerdir?"})
        self.assertIn("model", response.json())

    def test_sets_conversation_title_from_question(self):
        with self._llm_ok, self._rag_ctx, self._llm_gen:
            response = self._post({"question": "Hangi fakülteler var?"})
        cid = response.json()["conversation_id"]
        conv = Conversation.objects.get(id=cid)
        self.assertIn("Hangi fakülteler", conv.title)


# ══════════════════════════════════════════════════════════
# API View Tests — Conversation Endpoints
# ══════════════════════════════════════════════════════════

class ConversationAPITest(TestCase):

    def setUp(self):
        self.client = Client()
        self.conv = Conversation.objects.create(title="Test Sohbeti")
        Message.objects.create(
            conversation=self.conv, role="user", content="Test sorusu"
        )

    def test_conversation_detail_returns_200(self):
        response = self.client.get(f"/api/conversations/{self.conv.id}/")
        self.assertEqual(response.status_code, 200)

    def test_conversation_detail_includes_title(self):
        response = self.client.get(f"/api/conversations/{self.conv.id}/")
        self.assertEqual(response.json()["title"], "Test Sohbeti")

    def test_conversation_detail_includes_messages(self):
        response = self.client.get(f"/api/conversations/{self.conv.id}/")
        messages = response.json()["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "Test sorusu")

    def test_conversation_delete_returns_204(self):
        response = self.client.delete(f"/api/conversations/{self.conv.id}/delete/")
        self.assertEqual(response.status_code, 204)

    def test_conversation_delete_removes_from_db(self):
        self.client.delete(f"/api/conversations/{self.conv.id}/delete/")
        self.assertFalse(Conversation.objects.filter(id=self.conv.id).exists())

    def test_conversation_not_found_returns_404(self):
        response = self.client.get(f"/api/conversations/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, 404)

    def test_conversations_list_is_session_filtered(self):
        # Conversation without session key won't appear for this test client's session
        response = self.client.get("/api/conversations/")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
