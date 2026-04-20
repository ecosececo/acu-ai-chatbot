"""
Management command: scrape_acu
Crawls the main Acibadem University website and stores pages in the database.
"""

import time

from django.core.management.base import BaseCommand

from chat.models import WebPage
from scraper.acu_scraper import ACUScraper


class Command(BaseCommand):
    help = "Scrape the main Acibadem University website (acibadem.edu.tr)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-pages",
            type=int,
            default=150,
            help="Maximum number of pages to scrape (default: 150)",
        )
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
        max_pages = options["max_pages"]
        force = options["force"]
        delay = options.get("delay")

        self.stdout.write(self.style.NOTICE(f"Starting ACU website scrape (max {max_pages} pages)..."))

        scraper = ACUScraper()
        if delay is not None:
            scraper.delay = delay
        scraper.max_pages = max_pages

        # Pre-populate visited set with existing URLs to skip them (unless --force)
        if not force:
            existing_urls = set(WebPage.objects.values_list("url", flat=True))
            scraper.visited.update(existing_urls)
            self.stdout.write(f"  Skipping {len(existing_urls)} already-scraped URLs.")

        count = [0]
        start = time.time()

        def progress_callback(page_data, current, remaining):
            count[0] = current
            self.stdout.write(f"  [{current}] Scraped: {page_data['url'][:80]}")

        results = scraper.scrape_all(callback=progress_callback)

        elapsed = time.time() - start
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! Scraped {len(results)} pages in {elapsed:.1f}s. "
                f"Total in DB: {WebPage.objects.count()}"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "Next step: run 'python manage.py generate_embeddings' to index the new pages."
            )
        )
