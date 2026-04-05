"""
Web Search Service — DuckDuckGo-based web search with content fetching.
Used when RAG doesn't return sufficient results or when user enables web search.
Now fetches ACTUAL page content from URLs for rich LLM context.
"""

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)

# Timeout for fetching individual web pages
PAGE_FETCH_TIMEOUT = 8.0


class WebSearchService:
    """
    Performs web searches using DuckDuckGo and fetches actual page content.
    Returns rich context for the LLM instead of just snippets.
    """

    def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        site_restricted: bool = True,
    ) -> list[dict]:
        """
        Search the web using DuckDuckGo, then fetch actual page content.

        Args:
            query: User's search query
            max_results: Maximum number of results (default from settings)
            site_restricted: If True, prioritize acibadem.edu.tr

        Returns:
            List of dicts with keys: title, url, snippet, content, source
        """
        if max_results is None:
            max_results = getattr(settings, "WEB_SEARCH_MAX_RESULTS", 5)

        try:
            from duckduckgo_search import DDGS

            raw_results = []

            with DDGS() as ddgs:
                # PASS 1: site-restricted to acibadem.edu.tr for best relevance
                if site_restricted:
                    search_query_site = f"site:acibadem.edu.tr {query}"
                    raw_results = list(ddgs.text(
                        search_query_site,
                        max_results=max_results,
                        region="tr-tr",
                    ))

                # PASS 2: Broader search with university name
                if not raw_results:
                    search_query = f"Acıbadem Üniversitesi {query}"
                    raw_results = list(ddgs.text(
                        search_query,
                        max_results=max_results,
                        region="tr-tr",
                    ))

                # PASS 3: If still nothing, try generic query
                if not raw_results:
                    raw_results = list(ddgs.text(
                        query,
                        max_results=max_results,
                        region="tr-tr",
                    ))

            results = []
            for r in raw_results:
                url = r.get("href", r.get("link", ""))
                title = r.get("title", "")
                snippet = r.get("body", r.get("snippet", ""))

                # Fetch actual page content
                page_content = self._fetch_page_content(url)

                results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "content": page_content or snippet,  # Fallback to snippet
                    "source": "web_search",
                })

            logger.info(
                f"Web search: query='{query[:50]}' "
                f"results={len(results)} "
                f"with_content={sum(1 for r in results if r.get('content') != r.get('snippet'))}"
            )
            return results

        except ImportError:
            logger.error("duckduckgo_search package not installed")
            return []
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return []

    def _fetch_page_content(self, url: str, max_chars: int = 3000) -> str:
        """
        Fetch and extract clean text content from a web page URL.

        Args:
            url: The URL to fetch
            max_chars: Maximum characters to extract

        Returns:
            Cleaned text content from the page, or empty string on failure
        """
        if not url:
            return ""

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            }

            with httpx.Client(
                timeout=PAGE_FETCH_TIMEOUT,
                follow_redirects=True,
                verify=False,
            ) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # Remove script, style, nav, footer, header elements
            for tag in soup(["script", "style", "nav", "footer", "header",
                             "aside", "form", "iframe", "noscript", "meta",
                             "link", "button", "img", "svg"]):
                tag.decompose()

            # Try to get main content area first
            main_content = (
                soup.find("main")
                or soup.find("article")
                or soup.find(class_=re.compile(r"content|main|body|article|post", re.I))
                or soup.find("div", class_=re.compile(r"content|main|body", re.I))
                or soup.body
            )

            if not main_content:
                return ""

            # Extract text
            text = main_content.get_text(separator="\n", strip=True)

            # Clean up whitespace
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            # Remove very short lines (likely navigation/buttons)
            lines = [line for line in lines if len(line) > 15]
            text = "\n".join(lines)

            # Truncate to max_chars
            if len(text) > max_chars:
                text = text[:max_chars] + "..."

            return text

        except Exception as e:
            logger.debug(f"Failed to fetch page content from {url}: {e}")
            return ""

    def build_web_context(self, results: list[dict]) -> str:
        """
        Build a context string from web search results for the LLM.
        Uses actual page content instead of just snippets.

        Returns:
            Formatted context string
        """
        if not results:
            return ""

        parts = []
        for i, r in enumerate(results, 1):
            # Use full content if available, otherwise use snippet
            content = r.get("content", "") or r.get("snippet", "")
            if not content:
                continue

            parts.append(
                f"### Web Kaynak {i}: {r['title']}\n"
                f"URL: {r['url']}\n\n"
                f"{content}\n"
            )

        return "\n---\n".join(parts)

    def should_web_search(self, rag_results: list[dict], threshold: Optional[float] = None) -> bool:
        """
        Determine if web search should be triggered based on RAG result quality.

        Args:
            rag_results: Results from RAG search
            threshold: Minimum score threshold (default from settings)

        Returns:
            True if web search should be performed
        """
        if threshold is None:
            threshold = getattr(settings, "WEB_SEARCH_THRESHOLD", 0.15)

        # No RAG results at all
        if not rag_results:
            return True

        # Check if best result is below threshold
        best_score = max(r.get("score", 0) for r in rag_results)
        if best_score < threshold:
            logger.info(
                f"Web search triggered: best RAG score {best_score:.4f} "
                f"< threshold {threshold}"
            )
            return True

        return False


# Module-level singleton
web_search_service = WebSearchService()
