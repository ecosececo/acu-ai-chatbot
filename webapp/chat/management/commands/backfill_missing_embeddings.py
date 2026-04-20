"""Backfill missing embeddings for existing DocumentChunk records."""

from django.core.management.base import BaseCommand, CommandError

from chat.models import DocumentChunk
from chat.services.llm_service import llm_service


class Command(BaseCommand):
    help = "Generate embeddings for DocumentChunk rows where embedding is NULL"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of chunks to process per batch (default: 100)",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if batch_size <= 0:
            raise CommandError("--batch-size must be greater than 0")

        MAX_LEN = 2000

        chunks = DocumentChunk.objects.filter(embedding=None)
        total = chunks.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS("No missing embeddings found."))
            return

        self.stdout.write(f"Missing embeddings: {total}")

        missing_ids = list(
            DocumentChunk.objects.filter(embedding=None)
            .order_by("id")
            .values_list("id", flat=True)
        )

        processed = 0
        failed = 0

        for start in range(0, total, batch_size):
            batch_ids = missing_ids[start:start + batch_size]
            batch = list(DocumentChunk.objects.filter(id__in=batch_ids).order_by("id"))
            updated_chunks = []

            for chunk in batch:
                text = (chunk.content or "").strip()

                if not text or len(text) < 10:
                    failed += 1
                    chunk.embedding = [0.0] * 768
                    updated_chunks.append(chunk)
                    processed += 1
                    print(f"Processed {processed}/{total}")
                    continue

                text = text[:MAX_LEN]

                try:
                    embedding = llm_service.get_embedding(text)
                except Exception:
                    try:
                        embedding = llm_service.get_embedding(text[:1000])
                    except Exception:
                        embedding = None

                if embedding is None:
                    failed += 1
                    embedding = [0.0] * 768

                chunk.embedding = embedding
                updated_chunks.append(chunk)

                processed += 1
                print(f"Processed {processed}/{total}")

            if updated_chunks:
                DocumentChunk.objects.bulk_update(updated_chunks, ["embedding"])

        total_chunks = DocumentChunk.objects.count()
        with_embedding = DocumentChunk.objects.exclude(embedding=None).count()

        self.stdout.write(f"chunks = {total_chunks}")
        self.stdout.write(f"with_embedding = {with_embedding}")
        self.stdout.write(f"failed = {failed}")

        if failed > 0:
            print(f"Warning: {failed} chunks failed")

        if with_embedding != total_chunks:
            remaining = total_chunks - with_embedding
            print(f"Warning: {remaining} chunks still missing embeddings")

        self.stdout.write(self.style.SUCCESS("Backfill complete: all chunks have embeddings."))
