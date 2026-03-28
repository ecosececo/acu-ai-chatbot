import os, sys, django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.models import WebPage, DocumentChunk
from django.db.models import Count

print("=" * 40)
print("DATABASE STATS")
print("=" * 40)
print(f"Total Pages:    {WebPage.objects.count()}")
print(f"Processed:      {WebPage.objects.filter(is_processed=True).count()}")
print(f"Total Chunks:   {DocumentChunk.objects.count()}")
print(f"Embedded:       {DocumentChunk.objects.filter(embedding__isnull=False).count()}")
print()
for s in WebPage.objects.values('source').annotate(count=Count('id')).order_by('source'):
    print(f"  Source '{s['source']}': {s['count']} pages")
print("=" * 40)
