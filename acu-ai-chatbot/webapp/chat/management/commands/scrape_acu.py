"""
Django management command to scrape ACU website and build RAG database.

Usage:
    python manage.py scrape_acu                      # Scrape main site only
    python manage.py scrape_acu --source=bologna     # Scrape OBS Bologna only
    python manage.py scrape_acu --source=all         # Scrape everything
    python manage.py scrape_acu --clear              # Clear all data first
    python manage.py scrape_acu --source=bologna --clear  # Clear and re-scrape Bologna
"""
from django.core.management.base import BaseCommand

from chat.models import WebPage, DocumentChunk
from chat.services.rag_service import rag_service
from scraper.acu_scraper import ACUScraper
from scraper.bologna_scraper import BolognaScraper


class Command(BaseCommand):
    help = 'Scrape ACU website and build RAG database with embeddings'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing data before scraping',
        )
        parser.add_argument(
            '--max-pages',
            type=int,
            default=500,
            help='Maximum number of pages to scrape (default: 500)',
        )
        parser.add_argument(
            '--reprocess',
            action='store_true',
            help='Reprocess already scraped pages (regenerate embeddings)',
        )
        parser.add_argument(
            '--source',
            type=str,
            choices=['main', 'bologna', 'all'],
            default='main',
            help='Which source to scrape: main (acibadem.edu.tr), bologna (OBS), or all (default: main)',
        )

    def handle(self, *args, **options):
        source = options['source']
        self.stdout.write(self.style.SUCCESS(
            f'Starting ACU website scraping (source: {source})...'
        ))

        # Stats
        total_pages = 0
        total_chunks = 0
        total_skipped = 0

        # Clear existing data if requested
        if options['clear']:
            self._clear_data(source)

        # Scrape main site
        if source in ('main', 'all'):
            pages, chunks, skipped = self._scrape_main(options)
            total_pages += pages
            total_chunks += chunks
            total_skipped += skipped

        # Scrape Bologna/OBS
        if source in ('bologna', 'all'):
            pages, chunks, skipped = self._scrape_bologna(options)
            total_pages += pages
            total_chunks += chunks
            total_skipped += skipped

        # Print final stats
        self._print_stats(total_pages, total_chunks, total_skipped)

    def _clear_data(self, source: str):
        """Clear existing data based on source."""
        if source == 'all':
            self.stdout.write('Clearing ALL existing data...')
            DocumentChunk.objects.all().delete()
            WebPage.objects.all().delete()
        elif source == 'main':
            self.stdout.write('Clearing main site data...')
            main_pages = WebPage.objects.filter(source='main')
            DocumentChunk.objects.filter(web_page__in=main_pages).delete()
            main_pages.delete()
        elif source == 'bologna':
            self.stdout.write('Clearing Bologna/OBS data...')
            bologna_pages = WebPage.objects.filter(source='bologna')
            DocumentChunk.objects.filter(web_page__in=bologna_pages).delete()
            bologna_pages.delete()

        self.stdout.write(self.style.WARNING(f'Data cleared for source: {source}'))

    def _scrape_main(self, options) -> tuple[int, int, int]:
        """Scrape the main acibadem.edu.tr website."""
        self.stdout.write(self.style.HTTP_INFO(
            '\n═══════════════════════════════════════════'
            '\n  Scraping: Main Site (acibadem.edu.tr)'
            '\n═══════════════════════════════════════════'
        ))

        scraper = ACUScraper()
        scraper.max_pages = options['max_pages']

        def scrape_callback(page_data, current_count, urls_remaining):
            self.stdout.write(
                f"  Progress: {current_count} pages scraped, {urls_remaining} URLs in queue"
            )

        scraped_pages = scraper.scrape_all(callback=scrape_callback)
        self.stdout.write(self.style.SUCCESS(f'  Scraped {len(scraped_pages)} pages from main site'))

        return self._save_pages(scraped_pages, options, "main")

    def _scrape_bologna(self, options) -> tuple[int, int, int]:
        """Scrape the OBS Bologna system using Playwright."""
        self.stdout.write(self.style.HTTP_INFO(
            '\n═══════════════════════════════════════════'
            '\n  Scraping: Bologna/OBS (obs.acibadem.edu.tr)'
            '\n  Using Playwright headless browser'
            '\n═══════════════════════════════════════════'
        ))

        scraper = BolognaScraper()

        def scrape_callback(page_data, current_count, urls_remaining):
            self.stdout.write(
                f"  Progress: {current_count} Bologna pages scraped"
            )

        scraped_pages = scraper.scrape_all(callback=scrape_callback)
        self.stdout.write(self.style.SUCCESS(
            f'  Scraped {len(scraped_pages)} pages from Bologna/OBS'
        ))

        return self._save_pages(scraped_pages, options, "bologna")

    def _save_pages(
        self, scraped_pages: list[dict], options: dict, source_label: str
    ) -> tuple[int, int, int]:
        """Save scraped pages to database and generate embeddings."""
        pages_count = 0
        chunks_count = 0
        skipped_count = 0

        self.stdout.write(f'  Saving {source_label} pages and generating embeddings...')
        self.stdout.write(self.style.WARNING(
            '  This may take a while. Each page needs to be chunked and embedded.'
        ))

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
                        'source': page_data.get('source', source_label),
                    }
                )

                if created or options['reprocess']:
                    # If reprocessing an existing page, update its content
                    if not created and options['reprocess']:
                        webpage.title = page_data.get('title', webpage.title)
                        webpage.content = page_data.get('content', webpage.content)
                        webpage.html = page_data.get('html', webpage.html)[:50000]
                        webpage.category = page_data.get('category', webpage.category)
                        webpage.is_processed = False
                        webpage.save()

                    pages_count += 1
                    self.stdout.write(
                        f"  [{i}/{len(scraped_pages)}] Processing: {page_data.get('title', page_data['url'])[:80]}"
                    )

                    chunk_count = rag_service.process_webpage(webpage, force=True)
                    chunks_count += chunk_count

                    self.stdout.write(
                        self.style.SUCCESS(f"    ✓ Created {chunk_count} chunks")
                    )
                else:
                    skipped_count += 1
                    if i % 10 == 0:
                        self.stdout.write(
                            f"  [{i}/{len(scraped_pages)}] Skipping (already exists): {page_data['url'][:60]}"
                        )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"  Error processing {page_data.get('url', '?')}: {e}")
                )
                import traceback
                traceback.print_exc()
                continue

        return pages_count, chunks_count, skipped_count

    def _print_stats(self, pages_count: int, chunks_count: int, skipped_count: int):
        """Print final statistics."""
        stats = rag_service.get_stats()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('═' * 60))
        self.stdout.write(self.style.SUCCESS('  Scraping and indexing complete!'))
        self.stdout.write(self.style.SUCCESS('═' * 60))
        self.stdout.write(f"  Pages processed this run: {pages_count}")
        self.stdout.write(f"  Pages skipped (already exist): {skipped_count}")
        self.stdout.write(f"  Total chunks created: {chunks_count}")
        self.stdout.write('')
        self.stdout.write('  Database Stats:')
        self.stdout.write(f"    - Total web pages: {stats['total_pages']}")
        self.stdout.write(f"    - Processed pages: {stats['processed_pages']}")
        self.stdout.write(f"    - Total chunks: {stats['total_chunks']}")
        self.stdout.write(f"    - Embedded chunks: {stats['embedded_chunks']}")

        # Show breakdown by source
        main_count = WebPage.objects.filter(source='main').count()
        bologna_count = WebPage.objects.filter(source='bologna').count()
        self.stdout.write(f"    - Main site pages: {main_count}")
        self.stdout.write(f"    - Bologna/OBS pages: {bologna_count}")
        self.stdout.write(self.style.SUCCESS('═' * 60))
