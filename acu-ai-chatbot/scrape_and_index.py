#!/usr/bin/env python
"""
Script to scrape ACU website and populate the database with embeddings.
Run this inside the Django container.

Usage:
    python scrape_and_index.py                        # Full scrape (main site, clears existing)
    python scrape_and_index.py --source=bologna       # Scrape OBS Bologna only
    python scrape_and_index.py --source=all           # Scrape everything
    python scrape_and_index.py --update               # Incremental update (refreshes stale pages)
    python scrape_and_index.py --update --max-age-days 3
"""
import argparse
import os
import sys
import django
from datetime import timedelta

# Setup Django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone
from chat.models import WebPage, DocumentChunk
from scraper.acu_scraper import ACUScraper
from scraper.bologna_scraper import BolognaScraper
from chat.services.rag_service import rag_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def full_scrape(source: str = "main"):
    """Full scrape: clear relevant data and re-scrape."""
    logger.info(f"Starting FULL web scraping (source: {source})...")

    pages_count = 0
    chunks_count = 0

    # Clear existing data based on source
    if source == "all":
        logger.info("Clearing ALL existing data...")
        DocumentChunk.objects.all().delete()
        WebPage.objects.all().delete()
    elif source == "main":
        logger.info("Clearing main site data...")
        main_pages = WebPage.objects.filter(source="main")
        DocumentChunk.objects.filter(web_page__in=main_pages).delete()
        main_pages.delete()
    elif source == "bologna":
        logger.info("Clearing Bologna/OBS data...")
        bologna_pages = WebPage.objects.filter(source="bologna")
        DocumentChunk.objects.filter(web_page__in=bologna_pages).delete()
        bologna_pages.delete()

    scraped_pages = []

    # Scrape main site
    if source in ("main", "all"):
        logger.info("Scraping main site (acibadem.edu.tr)...")
        scraper = ACUScraper()

        def main_callback(page_data, current_count, urls_remaining):
            logger.info(f"Main site: {current_count} pages scraped, {urls_remaining} URLs in queue")

        main_pages = scraper.scrape_all(callback=main_callback)
        scraped_pages.extend(main_pages)
        logger.info(f"Scraped {len(main_pages)} pages from main site")

    # Scrape Bologna/OBS
    if source in ("bologna", "all"):
        logger.info("Scraping Bologna/OBS (obs.acibadem.edu.tr)...")
        bologna_scraper = BolognaScraper()

        def bologna_callback(page_data, current_count, urls_remaining):
            logger.info(f"Bologna: {current_count} pages scraped")

        bologna_pages = bologna_scraper.scrape_all(callback=bologna_callback)
        scraped_pages.extend(bologna_pages)
        logger.info(f"Scraped {len(bologna_pages)} pages from Bologna/OBS")

    # Save to database and create embeddings
    logger.info("Saving pages and generating embeddings...")
    for i, page_data in enumerate(scraped_pages, 1):
        try:
            webpage, created = WebPage.objects.get_or_create(
                url=page_data['url'],
                defaults={
                    'title': page_data.get('title', ''),
                    'content': page_data.get('content', ''),
                    'html': page_data.get('html', '')[:50000],
                    'category': page_data.get('category', 'general'),
                    'language': page_data.get('language', 'tr'),
                    'source': page_data.get('source', 'main'),
                }
            )

            if created:
                pages_count += 1
                logger.info(f"[{i}/{len(scraped_pages)}] Saved: {page_data.get('title', page_data['url'])[:80]}")

                chunk_count = rag_service.process_webpage(webpage, force=True)
                chunks_count += chunk_count

                logger.info(f"  → Created {chunk_count} chunks with embeddings")
            else:
                logger.info(f"[{i}/{len(scraped_pages)}] Already exists: {page_data['url']}")

        except Exception as e:
            logger.error(f"Error processing {page_data.get('url', '?')}: {e}")
            import traceback
            traceback.print_exc()
            continue

    _print_stats(pages_count, chunks_count, f"Full scrape (source: {source})")


def incremental_update(max_age_days: int = 7):
    """Incremental update: only refresh pages older than max_age_days."""
    logger.info(f"Starting INCREMENTAL update (refreshing pages older than {max_age_days} days)...")

    scraper = ACUScraper()
    cutoff = timezone.now() - timedelta(days=max_age_days)

    # Find stale pages
    stale_pages = WebPage.objects.filter(updated_at__lt=cutoff)
    stale_count = stale_pages.count()
    logger.info(f"Found {stale_count} stale pages to refresh")

    updated_count = 0
    chunks_count = 0

    for page in stale_pages:
        try:
            page_data = scraper.scrape_page(page.url)
            if page_data:
                page.title = page_data.get('title', page.title)
                page.content = page_data.get('content', page.content)
                page.html = page_data.get('html', page.html)[:50000]
                page.category = page_data.get('category', page.category)
                page.is_processed = False
                page.save()

                chunk_count = rag_service.process_webpage(page, force=True)
                chunks_count += chunk_count
                updated_count += 1

                logger.info(f"Updated: {page.url} → {chunk_count} chunks")

        except Exception as e:
            logger.error(f"Error updating {page.url}: {e}")
            continue

    # Also scrape any new pages from seed URLs not yet in DB
    logger.info("Checking for new pages from seed URLs...")
    new_pages = 0

    def scrape_callback(page_data, current_count, urls_remaining):
        logger.info(f"New pages progress: {current_count} scraped, {urls_remaining} in queue")

    scraped_pages = scraper.scrape_all(callback=scrape_callback)

    for page_data in scraped_pages:
        if not WebPage.objects.filter(url=page_data['url']).exists():
            try:
                webpage = WebPage.objects.create(
                    url=page_data['url'],
                    title=page_data.get('title', ''),
                    content=page_data.get('content', ''),
                    html=page_data.get('html', ''),
                    category=page_data.get('category', 'general'),
                    language=page_data.get('language', 'tr'),
                    source=page_data.get('source', 'main'),
                )
                chunk_count = rag_service.process_webpage(webpage, force=True)
                chunks_count += chunk_count
                new_pages += 1
                logger.info(f"New page: {page_data['url']} → {chunk_count} chunks")
            except Exception as e:
                logger.error(f"Error adding new page {page_data['url']}: {e}")

    _print_stats(updated_count + new_pages, chunks_count,
                 f"Incremental update ({updated_count} refreshed, {new_pages} new)")


def _print_stats(pages_count, chunks_count, mode):
    """Print final statistics."""
    stats = rag_service.get_stats()

    main_count = WebPage.objects.filter(source='main').count()
    bologna_count = WebPage.objects.filter(source='bologna').count()

    logger.info(f"""
    ========================================
    {mode} complete!
    ========================================
    Pages processed this run: {pages_count}
    Chunks created this run:  {chunks_count}

    Database Stats:
    - Total web pages: {stats['total_pages']}
    - Processed pages: {stats['processed_pages']}
    - Total chunks: {stats['total_chunks']}
    - Embedded chunks: {stats['embedded_chunks']}
    - Main site pages: {main_count}
    - Bologna/OBS pages: {bologna_count}
    ========================================
    """)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ACU Chatbot - Scrape and Index')
    parser.add_argument('--update', action='store_true',
                        help='Incremental update mode (only refresh stale pages)')
    parser.add_argument('--max-age-days', type=int, default=7,
                        help='Max age in days before a page is considered stale (default: 7)')
    parser.add_argument('--source', type=str, default='main',
                        choices=['main', 'bologna', 'all'],
                        help='Which source to scrape: main, bologna, or all (default: main)')
    args = parser.parse_args()

    if args.update:
        incremental_update(max_age_days=args.max_age_days)
    else:
        full_scrape(source=args.source)
