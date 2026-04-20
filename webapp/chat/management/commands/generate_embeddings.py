"""Generate DocumentChunk records (with embeddings) from WebPage records."""

from django.core.management.base import BaseCommand

from chat.models import WebPage
from chat.services.rag_service import rag_service


class Command(BaseCommand):
    help = "Generate chunks and embeddings from scraped WebPage records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-process already processed pages as well",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Process at most N pages (0 = no limit)",
        )

    def handle(self, *args, **options):
        force = options["force"]
        limit = options["limit"]

        pages_qs = WebPage.objects.all().order_by("id")
        if not force:
            pages_qs = pages_qs.filter(is_processed=False)

        total_pages = pages_qs.count()
        if limit and limit > 0:
            pages_qs = pages_qs[:limit]

        if not pages_qs.exists():
            self.stdout.write(self.style.WARNING("No pages to process."))
            return

        self.stdout.write(
            f"Processing {pages_qs.count()} page(s) out of {total_pages} candidate page(s)..."
        )

        total_chunks = 0
        processed_pages = 0

        for page in pages_qs.iterator():
            created = rag_service.process_webpage(page, force=force)
            total_chunks += created
            processed_pages += 1
            self.stdout.write(
                f"[{processed_pages}] {page.url} -> {created} chunk(s)"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed pages: {processed_pages}, Created chunks: {total_chunks}"
            )
        )
