"""
Tests for the ACU AI Chatbot application.
"""

from django.test import TestCase, Client
from django.urls import reverse

from chat.models import Conversation, DocumentChunk, Message, WebPage
from chat.services.rag_service import chunk_text


class WebPageModelTest(TestCase):
    """Tests for the WebPage model."""

    def test_create_webpage(self):
        page = WebPage.objects.create(
            url="https://www.acibadem.edu.tr/test",
            title="Test Page",
            content="This is test content about ACU.",
            source="main",
            category="general",
        )
        self.assertEqual(page.title, "Test Page")
        self.assertEqual(page.source, "main")
        self.assertFalse(page.is_processed)

    def test_webpage_str(self):
        page = WebPage.objects.create(
            url="https://www.acibadem.edu.tr/test",
            title="My Page",
            content="Content",
        )
        self.assertIn("My Page", str(page))


class ConversationModelTest(TestCase):
    """Tests for the Conversation model."""

    def test_create_conversation(self):
        conv = Conversation.objects.create(title="Test Chat")
        self.assertEqual(conv.title, "Test Chat")
        self.assertTrue(conv.is_active)
        self.assertEqual(conv.message_count, 0)

    def test_conversation_with_messages(self):
        conv = Conversation.objects.create(title="Chat")
        Message.objects.create(conversation=conv, role="user", content="Hello")
        Message.objects.create(conversation=conv, role="assistant", content="Hi there!")
        self.assertEqual(conv.message_count, 2)


class MessageModelTest(TestCase):
    """Tests for the Message model."""

    def test_create_message(self):
        conv = Conversation.objects.create()
        msg = Message.objects.create(
            conversation=conv,
            role="user",
            content="What faculties does ACU have?",
        )
        self.assertEqual(msg.role, "user")
        self.assertIn("faculties", msg.content)


class ChunkTextTest(TestCase):
    """Tests for the text chunking function."""

    def test_empty_text(self):
        self.assertEqual(chunk_text(""), [])
        self.assertEqual(chunk_text("   "), [])

    def test_short_text(self):
        chunks = chunk_text("This is a short text.")
        self.assertEqual(len(chunks), 1)

    def test_long_text_chunking(self):
        # Create a long text that should be split into multiple chunks
        paragraphs = ["This is paragraph number {}.".format(i) * 20 for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, chunk_size=200)
        self.assertGreater(len(chunks), 1)

    def test_preserves_content(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = chunk_text(text, chunk_size=5000)
        combined = " ".join(chunks)
        self.assertIn("First", combined)
        self.assertIn("Second", combined)
        self.assertIn("Third", combined)


class APIViewTest(TestCase):
    """Tests for API endpoints."""

    def setUp(self):
        self.client = Client()

    def test_health_endpoint(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)

    def test_api_health(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)

    def test_api_stats(self):
        response = self.client.get("/api/stats/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_pages", data)
        self.assertIn("llm_available", data)

    def test_api_conversations_empty(self):
        response = self.client.get("/api/conversations/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_chat_requires_post(self):
        response = self.client.get("/api/chat/")
        self.assertEqual(response.status_code, 405)

    def test_chat_requires_question(self):
        response = self.client.post(
            "/api/chat/",
            data={},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_index_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ACU")


class ConversationAPITest(TestCase):
    """Tests for conversation API endpoints."""

    def setUp(self):
        self.client = Client()
        self.conv = Conversation.objects.create(title="Test Conv")
        Message.objects.create(
            conversation=self.conv, role="user", content="Test question"
        )

    def test_conversation_detail(self):
        response = self.client.get(f"/api/conversations/{self.conv.id}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["title"], "Test Conv")
        self.assertEqual(len(data["messages"]), 1)

    def test_conversation_delete(self):
        response = self.client.delete(f"/api/conversations/{self.conv.id}/delete/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Conversation.objects.filter(id=self.conv.id).exists())

    def test_conversation_not_found(self):
        import uuid
        response = self.client.get(f"/api/conversations/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, 404)
# Integration tests - final version
