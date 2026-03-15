"""
RAG Service — Retrieval-Augmented Generation using pgvector.
Handles document chunking, embedding storage, and semantic search.
"""

import logging
import re
from typing import Optional

from django.conf import settings
from django.db import connection
from pgvector.django import CosineDistance

from ..models import DocumentChunk, WebPage
from .llm_service import llm_service

logger = logging.getLogger(__name__)

# ── Text Chunking ────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """
    Split text into overlapping chunks for embedding.

    Uses a smart splitting strategy:
    1. Try to split on paragraph boundaries
    2. Then on sentence boundaries
    3. Fall back to word boundaries
    """
    if not text or not text.strip():
        return []

    # Clean the text
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = text.strip()

    # Split into paragraphs first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        # If adding this paragraph exceeds chunk_size, finalize current chunk
        if current_chunk and len(current_chunk) + len(para) + 2 > chunk_size:
            chunks.append(current_chunk.strip())
            # Keep overlap from the end of current chunk
            words = current_chunk.split()
            overlap_words = words[-overlap:] if len(words) > overlap else words
            current_chunk = " ".join(overlap_words) + "\n\n" + para
        else:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # Handle case where a single paragraph is too long
    final_chunks = []
    for chunk in chunks:
        if len(chunk) > chunk_size * 2:
            # Split long chunks by sentences
            sentences = re.split(r"(?<=[.!?])\s+", chunk)
            sub_chunk = ""
            for sentence in sentences:
                if sub_chunk and len(sub_chunk) + len(sentence) + 1 > chunk_size:
                    final_chunks.append(sub_chunk.strip())
                    sub_chunk = sentence
                else:
                    sub_chunk = sub_chunk + " " + sentence if sub_chunk else sentence
            if sub_chunk.strip():
                final_chunks.append(sub_chunk.strip())
        else:
            final_chunks.append(chunk)

    return final_chunks


class RAGService:
    """
    Retrieval-Augmented Generation service.
    Handles the full pipeline: chunk → embed → store → retrieve → augment.
    """

    def __init__(self):
        self._ensure_pgvector()

    def _ensure_pgvector(self):
        """Ensure pgvector extension is installed in PostgreSQL."""
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        except Exception as e:
            logger.warning(f"Could not create pgvector extension: {e}")

    # ── Indexing Pipeline ────────────────────────────────

    def process_webpage(self, webpage: WebPage, force: bool = False) -> int:
        """
        Process a webpage: chunk text, generate embeddings, store in DB.

        Returns:
            Number of chunks created
        """
        if webpage.is_processed and not force:
            logger.info(f"Skipping already processed page: {webpage.url}")
            return 0

        if not webpage.content or not webpage.content.strip():
            logger.warning(f"Empty content for page: {webpage.url}")
            return 0

        # Delete existing chunks if reprocessing
        webpage.chunks.all().delete()

        # Chunk the text
        chunks = chunk_text(webpage.content)
        if not chunks:
            return 0

        logger.info(f"Processing {len(chunks)} chunks for: {webpage.title or webpage.url}")

        created_count = 0
        for i, chunk_text_content in enumerate(chunks):
            # Generate embedding
            embedding = llm_service.get_embedding(chunk_text_content)

            DocumentChunk.objects.create(
                web_page=webpage,
                chunk_index=i,
                content=chunk_text_content,
                embedding=embedding,
                token_count=len(chunk_text_content.split()),
                metadata={
                    "title": webpage.title,
                    "url": webpage.url,
                    "source": webpage.source,
                    "category": webpage.category,
                },
            )
            created_count += 1

        # Mark as processed
        webpage.is_processed = True
        webpage.save(update_fields=["is_processed"])

        logger.info(f"Created {created_count} chunks for: {webpage.title or webpage.url}")
        return created_count

    def process_all_unprocessed(self) -> int:
        """Process all unprocessed web pages."""
        pages = WebPage.objects.filter(is_processed=False)
        total = 0
        for page in pages:
            total += self.process_webpage(page)
        return total

    # ── Retrieval ────────────────────────────────────────

    def search(self, query: str, top_k: Optional[int] = None) -> list[dict]:
        """
        Perform semantic search using pgvector cosine similarity.

        Returns:
            List of dicts with keys: content, url, title, source, score
        """
        if top_k is None:
            top_k = settings.RAG_TOP_K

        # Generate query embedding
        query_embedding = llm_service.get_embedding(query)
        if query_embedding is None:
            logger.warning("Could not generate query embedding, falling back to keyword search")
            return self._keyword_search(query, top_k)

        # Semantic search with pgvector
        try:
            results = (
                DocumentChunk.objects
                .filter(embedding__isnull=False)
                .annotate(distance=CosineDistance("embedding", query_embedding))
                .order_by("distance")[:top_k]
            )

            search_results = []
            for chunk in results:
                score = 1 - chunk.distance  # Convert distance to similarity
                if score >= settings.RAG_SIMILARITY_THRESHOLD:
                    search_results.append({
                        "content": chunk.content,
                        "url": chunk.metadata.get("url", ""),
                        "title": chunk.metadata.get("title", ""),
                        "source": chunk.metadata.get("source", ""),
                        "category": chunk.metadata.get("category", ""),
                        "score": round(score, 4),
                    })

            logger.info(f"Semantic search found {len(search_results)} results for: {query[:50]}...")
            return search_results

        except Exception as e:
            logger.error(f"Semantic search failed: {e}, falling back to keyword search")
            return self._keyword_search(query, top_k)

    def _keyword_search(self, query: str, top_k: int = 5) -> list[dict]:
        """Fallback keyword-based search using PostgreSQL full-text search."""
        # Simple LIKE-based search as fallback
        words = query.split()[:5]  # Use first 5 words
        from django.db.models import Q

        q_filter = Q()
        for word in words:
            if len(word) > 2:
                q_filter |= Q(content__icontains=word)

        results = (
            DocumentChunk.objects
            .filter(q_filter)
            .select_related("web_page")[:top_k]
        )

        return [
            {
                "content": chunk.content,
                "url": chunk.metadata.get("url", chunk.web_page.url),
                "title": chunk.metadata.get("title", chunk.web_page.title),
                "source": chunk.metadata.get("source", chunk.web_page.source),
                "category": chunk.metadata.get("category", ""),
                "score": 0.5,  # Default score for keyword results
            }
            for chunk in results
        ]

    def build_context(self, query: str, top_k: Optional[int] = None) -> tuple[str, list[dict]]:
        """
        Build context string for the LLM from search results.

        Returns:
            Tuple of (context_string, source_list)
        """
        results = self.search(query, top_k)

        if not results:
            return "", []

        context_parts = []
        sources = []
        seen_urls = set()

        for i, result in enumerate(results, 1):
            context_parts.append(
                f"### Kaynak {i}: {result['title']}\n"
                f"URL: {result['url']}\n"
                f"Benzerlik Skoru: {result['score']}\n\n"
                f"{result['content']}\n"
            )

            if result["url"] not in seen_urls:
                sources.append({
                    "url": result["url"],
                    "title": result["title"],
                    "score": result["score"],
                })
                seen_urls.add(result["url"])

        context = "\n---\n".join(context_parts)
        return context, sources

    # ── Stats ────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get RAG system statistics."""
        total_pages = WebPage.objects.count()
        processed_pages = WebPage.objects.filter(is_processed=True).count()
        total_chunks = DocumentChunk.objects.count()
        embedded_chunks = DocumentChunk.objects.filter(embedding__isnull=False).count()

        return {
            "total_pages": total_pages,
            "processed_pages": processed_pages,
            "total_chunks": total_chunks,
            "embedded_chunks": embedded_chunks,
            "coverage": f"{processed_pages}/{total_pages}" if total_pages > 0 else "0/0",
        }


# Module-level singleton
rag_service = RAGService()





