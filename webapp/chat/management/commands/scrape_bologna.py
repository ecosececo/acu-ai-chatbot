"""
Management command: scrape_bologna
Scrapes academic program data from the ACU Bologna/OBS system (obs.acibadem.edu.tr).
"""

import time

from django.core.management.base import BaseCommand

from chat.models import WebPage
from scraper.bologna_scraper import BolognaScraper


class Command(BaseCommand):
    help = "Scrape academic data from the ACU Bologna system (obs.acibadem.edu.tr)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-scrape pages that already exist in the database",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=None,
            help="Delay between requests in seconds (overrides settings)",
        )

    def handle(self, *args, **options):
        force = options["force"]
        delay = options.get("delay")

        self.stdout.write(self.style.NOTICE("Starting Bologna system scrape..."))

        scraper = BolognaScraper()
        if delay is not None:
            scraper.delay = delay

        # Pre-populate visited set with existing URLs (unless --force)
        if not force:
            existing_urls = set(WebPage.objects.filter(source="bologna").values_list("url", flat=True))
            scraper.visited.update(existing_urls)
            self.stdout.write(f"  Skipping {len(existing_urls)} already-scraped Bologna URLs.")

        start = time.time()
        saved = 0

        def progress_callback(page_data, current, remaining):
            nonlocal saved
            url = page_data.get("url", "")
            title = page_data.get("title", "")
            content = page_data.get("content", "")

            _, created = WebPage.objects.update_or_create(
                url=url,
                defaults={
                    "title": title,
                    "content": content,
                    "html": page_data.get("html", "")[:50000],
                    "source": "bologna",
                    "category": page_data.get("category", "academic"),
                    "language": page_data.get("language", "tr"),
                    "is_processed": False,
                },
            )
            if created:
                saved += 1
            self.stdout.write(f"  [{current}] {'Created' if created else 'Updated'}: {title or url[:60]}")

        results = scraper.scrape_all(callback=progress_callback)

        # Save any results not yet saved by the callback
        for page_data in results:
            url = page_data.get("url", "")
            if not url:
                continue
            WebPage.objects.update_or_create(
                url=url,
                defaults={
                    "title": page_data.get("title", ""),
                    "content": page_data.get("content", ""),
                    "html": page_data.get("html", "")[:50000],
                    "source": "bologna",
                    "category": page_data.get("category", "academic"),
                    "language": page_data.get("language", "tr"),
                    "is_processed": False,
                },
            )

        elapsed = time.time() - start
        total_bologna = WebPage.objects.filter(source="bologna").count()
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! Scraped {len(results)} Bologna pages in {elapsed:.1f}s. "
                f"Total Bologna pages in DB: {total_bologna}"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "Next step: run 'python manage.py generate_embeddings' to index the new pages."
            )
        )
