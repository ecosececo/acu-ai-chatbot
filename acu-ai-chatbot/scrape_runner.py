#!/usr/bin/env python
"""
ACU Scraper Runner — Easy scraping without memorizing commands.

Usage:
    python scrape_runner.py main                # Scrape main site
    python scrape_runner.py bologna             # Scrape Bologna system
    python scrape_runner.py all                 # Scrape both
    python scrape_runner.py main --clear        # Clear main + re-scrape
    python scrape_runner.py stats               # Show database stats
    python scrape_runner.py help                # Show this message
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str]) -> int:
    """Run shell command and return exit code."""
    print(f"\n>>> {' '.join(cmd)}\n")
    return subprocess.call(cmd)


def show_help():
    """Show usage information."""
    print(__doc__)


def scrape_main(clear: bool = False):
    """Scrape main ACU website."""
    print("\n" + "=" * 70)
    print("  SCRAPING: Main ACU Website (acibadem.edu.tr)")
    print("=" * 70)
    cmd = ["docker-compose", "exec", "-T", "webapp", "python", "manage.py", "scrape_acu", "--source=main"]
    if clear:
        cmd.append("--clear")
        print("  [MODE] Clearing existing data + fresh scrape\n")
    else:
        print("  [MODE] Incremental (skips already scraped pages)\n")
    return run_command(cmd)


def scrape_bologna(clear: bool = False):
    """Scrape Bologna system."""
    print("\n" + "=" * 70)
    print("  SCRAPING: Bologna System (obs.acibadem.edu.tr)")
    print("  Using Playwright for JavaScript rendering")
    print("=" * 70)
    cmd = ["docker-compose", "exec", "-T", "webapp", "python", "manage.py", "scrape_acu", "--source=bologna"]
    if clear:
        cmd.append("--clear")
        print("  [MODE] Clearing existing data + fresh scrape\n")
    else:
        print("  [MODE] Incremental (skips already scraped pages)\n")
    return run_command(cmd)


def scrape_all(clear: bool = False):
    """Scrape both main and Bologna."""
    print("\n" + "=" * 70)
    print("  SCRAPING: Everything (Main + Bologna)")
    print("=" * 70)
    print("  This will take 30-45 minutes\n")
    cmd = ["docker-compose", "exec", "-T", "webapp", "python", "manage.py", "scrape_acu", "--source=all"]
    if clear:
        cmd.append("--clear")
        print("  [MODE] Clearing existing data + fresh scrape\n")
    else:
        print("  [MODE] Incremental\n")
    return run_command(cmd)


def show_stats():
    """Show database statistics."""
    print("\n" + "=" * 70)
    print("  DATABASE STATISTICS")
    print("=" * 70 + "\n")
    cmd = [
        "docker-compose", "exec", "-T", "webapp", "python", "-c",
        """
from chat.models import WebPage, DocumentChunk
from chat.services.rag_service import rag_service

stats = rag_service.get_stats()
print(f"Total pages:        {stats['total_pages']}")
print(f"Processed pages:    {stats['processed_pages']}")
print(f"Total chunks:       {stats['total_chunks']}")
print(f"Embedded chunks:    {stats['embedded_chunks']}")
print(f"Coverage:           {stats['coverage']}")

print()
main = WebPage.objects.filter(source='main').count()
bologna = WebPage.objects.filter(source='bologna').count()
print(f"Main site pages:    {main}")
print(f"Bologna pages:      {bologna}")

print()
main_chunks = DocumentChunk.objects.filter(web_page__source='main').count()
bologna_chunks = DocumentChunk.objects.filter(web_page__source='bologna').count()
print(f"Main chunks:        {main_chunks}")
print(f"Bologna chunks:     {bologna_chunks}")
"""
    ]
    return run_command(cmd)


def verify_services():
    """Verify Docker services are running."""
    print("\n" + "=" * 70)
    print("  CHECKING SERVICES")
    print("=" * 70 + "\n")
    result = subprocess.call(["docker-compose", "ps"])
    if result != 0:
        print("\n[ERROR] Services not running. Start them with:")
        print("  docker-compose up -d")
        return False
    return True


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)

    cmd = sys.argv[1].lower()
    clear_flag = "--clear" in sys.argv

    if not verify_services():
        sys.exit(1)

    if cmd == "main":
        sys.exit(scrape_main(clear=clear_flag))
    elif cmd == "bologna":
        sys.exit(scrape_bologna(clear=clear_flag))
    elif cmd == "all":
        sys.exit(scrape_all(clear=clear_flag))
    elif cmd == "stats":
        sys.exit(show_stats())
    elif cmd == "help" or cmd == "-h" or cmd == "--help":
        show_help()
        sys.exit(0)
    else:
        print(f"\n[ERROR] Unknown command: {cmd}\n")
        show_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
