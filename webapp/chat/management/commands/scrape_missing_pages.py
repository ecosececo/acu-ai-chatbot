"""Scrape specific high-priority pages that are missing or have poor content."""

import time
import logging

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand

from chat.models import WebPage
from chat.services.rag_service import rag_service

logger = logging.getLogger(__name__)

PRIORITY_URLS = [
    # Founding / about
    "https://www.acibadem.edu.tr/hakkimizda",
    "https://www.acibadem.edu.tr/hakkimizda/tarihce",
    "https://www.acibadem.edu.tr/hakkimizda/misyon-vizyon",
    # Contact / address
    "https://www.acibadem.edu.tr/iletisim",
    # Engineering faculty + departments
    "https://www.acibadem.edu.tr/muhendislik-ve-doga-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/muhendislik-ve-doga-bilimleri-fakultesi/bolumler",
    "https://www.acibadem.edu.tr/bilgisayar-muhendisligi",
    "https://www.acibadem.edu.tr/yazilim-muhendisligi",
    "https://www.acibadem.edu.tr/biyomedikal-muhendisligi",
    "https://www.acibadem.edu.tr/endustri-muhendisligi",
    # Pharmacy faculty
    "https://www.acibadem.edu.tr/eczacilik-fakultesi",
    "https://www.acibadem.edu.tr/eczacilik-fakultesi/hakkinda",
    # Campus
    "https://www.acibadem.edu.tr/kampus-yasami",
    "https://www.acibadem.edu.tr/kampus-yasami/kampus-olanaklari",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ACU-Chatbot-Research/1.0; "
        "+https://www.acibadem.edu.tr)"
    )
}


def _scrape_url(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
            tag.decompose()
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id="content")
            or soup.find(class_="content")
            or soup.body
        )
        if not main:
            return None
        text = " ".join(main.get_text(separator=" ").split())
        return text if len(text) > 100 else None
    except Exception as exc:
        logger.warning("Failed to scrape %s: %s", url, exc)
        return None


class Command(BaseCommand):
    help = "Scrape high-priority missing pages and generate their embeddings"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-scrape even if URL already exists in DB",
        )

    def handle(self, *args, **options):
        force = options["force"]
        scraped = 0
        skipped = 0

        for url in PRIORITY_URLS:
            if not force and WebPage.objects.filter(url=url).exists():
                self.stdout.write(f"  SKIP (exists): {url}")
                skipped += 1
                continue

            self.stdout.write(f"  Scraping: {url}")
            content = _scrape_url(url)
            if not content:
                self.stdout.write(self.style.WARNING(f"  No content: {url}"))
                time.sleep(1)
                continue

            # Derive title from last path segment
            path = url.rstrip("/").split("/")[-1]
            title = path.replace("-", " ").title() or "Acıbadem Üniversitesi"

            page, created = WebPage.objects.update_or_create(
                url=url,
                defaults={
                    "title": title,
                    "content": content,
                    "is_processed": False,
                },
            )
            chunks_created = rag_service.process_webpage(page, force=True)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {'CREATED' if created else 'UPDATED'}: {url} → {chunks_created} chunks"
                )
            )
            scraped += 1
            time.sleep(1.5)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {scraped} scraped, {skipped} skipped."
            )
        )
