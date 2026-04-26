"""
Add HNSW index on DocumentChunk.embedding for fast cosine similarity search.
Uses pgvector's hnsw method with vector_cosine_ops.
"""

from django.db import migrations


class Migration(migrations.Migration):

    atomic = False  # CREATE INDEX cannot run inside a transaction

    dependencies = [
        ("chat", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "documentchunk_embedding_hnsw_idx "
                "ON chat_documentchunk USING hnsw (embedding vector_cosine_ops);"
            ),
            reverse_sql="DROP INDEX IF EXISTS documentchunk_embedding_hnsw_idx;",
        ),
    ]
