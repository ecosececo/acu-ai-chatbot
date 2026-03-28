#!/usr/bin/env python
"""
ACU Chatbot Health Check — Verify all systems are operational.

Usage:
    python health_check.py                    # Full health check
    python health_check.py quick              # Quick status only
    python health_check.py repair             # Auto-repair issues
"""

import subprocess
import sys
import time
from typing import Optional


class HealthChecker:
    """Check all system components."""

    def __init__(self):
        self.issues = []
        self.warnings = []

    def check_docker(self) -> bool:
        """Check if Docker is running."""
        try:
            result = subprocess.run(
                ["docker-compose", "ps"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def check_services(self) -> dict[str, bool]:
        """Check if all required services are running."""
        services = {}
        try:
            result = subprocess.run(
                ["docker-compose", "ps", "--format", "{{.Service}}={{.Status}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "=" in line:
                    service, status = line.split("=", 1)
                    services[service] = status.startswith("Up")
        except Exception:
            pass
        return services

    def check_database(self) -> Optional[str]:
        """Check if database is accessible."""
        try:
            result = subprocess.run(
                [
                    "docker-compose",
                    "exec",
                    "-T",
                    "webapp",
                    "python",
                    "-c",
                    "from django.db import connection; connection.ensure_connection()",
                ],
                capture_output=True,
                timeout=10,
            )
            return None if result.returncode == 0 else result.stderr.decode()
        except Exception as e:
            return str(e)

    def check_ollama(self) -> Optional[str]:
        """Check if Ollama and models are available."""
        try:
            result = subprocess.run(
                ["docker-compose", "exec", "-T", "ollama", "ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            models = []
            for line in result.stdout.split("\n"):
                if line.strip() and "NAME" not in line:
                    models.append(line.split()[0] if line.split() else "")
            return "\n".join([m for m in models if m]) if models else "No models"
        except Exception as e:
            return f"Error: {str(e)}"

    def check_tgi(self) -> bool:
        """Check if TGI health endpoint is reachable."""
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "http://localhost:8080/health",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout == "200"
        except Exception:
            return False

    def check_content(self) -> dict:
        """Check database content."""
        try:
            result = subprocess.run(
                [
                    "docker-compose",
                    "exec",
                    "-T",
                    "webapp",
                    "python",
                    "-c",
                    """
from chat.models import WebPage, DocumentChunk
from chat.services.rag_service import rag_service
stats = rag_service.get_stats()
print(f"pages={stats['total_pages']}")
print(f"chunks={stats['total_chunks']}")
print(f"embedded={stats['embedded_chunks']}")
main = WebPage.objects.filter(source='main').count()
bologna = WebPage.objects.filter(source='bologna').count()
print(f"main={main}")
print(f"bologna={bologna}")
""",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            data = {}
            for line in result.stdout.split("\n"):
                if "=" in line:
                    key, val = line.split("=", 1)
                    data[key] = int(val)
            return data
        except Exception:
            return {}

    def check_web_ui(self) -> bool:
        """Check if web UI is responding."""
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost/"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout == "200"
        except Exception:
            return False

    def run_full_check(self):
        """Run complete health check."""
        print("\n" + "=" * 70)
        print("  ACU CHATBOT HEALTH CHECK")
        print("=" * 70 + "\n")

        # Docker
        print("[1/5] Docker & Services...")
        if not self.check_docker():
            print("  ✗ Docker not running")
            self.issues.append("Docker is not running")
            return

        services = self.check_services()
        required_services = ["webapp", "db", "redis", "ollama", "tgi-gemma4"]
        for service in required_services:
            status = "✓" if services.get(service) else "✗"
            print(f"  {status} {service:15} {'Up' if services.get(service) else 'Down'}")
            if not services.get(service):
                self.issues.append(f"Service {service} is not running")

        # Database
        print("\n[2/5] Database...")
        db_error = self.check_database()
        if db_error:
            print(f"  ✗ Database connection failed: {db_error}")
            self.issues.append("Database not accessible")
        else:
            print("  ✓ Database connected")

        # LLM Services
        print("\n[3/5] LLM Services...")
        if self.check_tgi():
            print("  ✓ TGI healthy (Gemma 4 E4B)")
        else:
            print("  ✗ TGI not responding on http://localhost:8080/health")
            self.issues.append("TGI not accessible")

        models = self.check_ollama()
        if models.startswith("Error"):
            print(f"  ✗ {models}")
            self.issues.append("Ollama not accessible")
        else:
            model_list = models.split("\n")
            if not model_list or model_list == [""]:
                self.warnings.append("No Ollama models found (embeddings may fail)")
            for model in model_list[:3]:
                if model:
                    print(f"  ✓ {model}")

        # Content
        print("\n[4/5] Database Content...")
        content = self.check_content()
        if content:
            print(f"  Pages:       {content.get('pages', 0)}")
            print(f"  Chunks:      {content.get('chunks', 0)}")
            print(f"  Embedded:    {content.get('embedded', 0)}")
            print(f"  Main site:   {content.get('main', 0)} pages")
            print(f"  Bologna:     {content.get('bologna', 0)} pages")
            if content.get("pages", 0) == 0:
                self.warnings.append("No pages scraped yet")
        else:
            print("  ✗ Could not query database")
            self.issues.append("Database query failed")

        # Web UI
        print("\n[5/5] Web Interface...")
        if self.check_web_ui():
            print("  ✓ Web UI accessible at http://localhost")
        else:
            self.warnings.append("Web UI not responding (may still be starting)")

        # Summary
        print("\n" + "=" * 70)
        if self.issues:
            print("  ISSUES FOUND:")
            for issue in self.issues:
                print(f"    ✗ {issue}")
        if self.warnings:
            print("\n  WARNINGS:")
            for warn in self.warnings:
                print(f"    ! {warn}")
        if not self.issues and not self.warnings:
            print("  ✓ All systems operational!")
        print("=" * 70 + "\n")

        return len(self.issues) == 0

    def quick_status(self):
        """Quick status summary."""
        services = self.check_services()
        content = self.check_content()

        status = "🟢 OPERATIONAL" if services.get("webapp") else "🔴 DOWN"
        print(f"\nStatus: {status}")
        print(f"Pages:  {content.get('pages', 0)}")
        print(f"Chunks: {content.get('chunks', 0)}\n")

        return len(self.issues) == 0

    def auto_repair(self):
        """Attempt to repair common issues."""
        print("\n" + "=" * 70)
        print("  AUTO-REPAIR")
        print("=" * 70 + "\n")

        services = self.check_services()
        down_services = [s for s, status in services.items() if not status]

        if down_services:
            print("Starting down services...")
            subprocess.run(["docker-compose", "up", "-d"], capture_output=True)
            print("  ✓ Services restarted")
            print("\n  Waiting 30 seconds for startup...")
            for i in range(30):
                print(f"  [{i+1}/30]", end="\r")
                time.sleep(1)

            self.run_full_check()
        else:
            print("  No repairs needed\n")


def main():
    """Main entry point."""
    checker = HealthChecker()

    if len(sys.argv) < 2 or sys.argv[1] == "full":
        success = checker.run_full_check()
        sys.exit(0 if success else 1)
    elif sys.argv[1] == "quick":
        checker.quick_status()
    elif sys.argv[1] == "repair":
        checker.auto_repair()
    else:
        print("Usage: python health_check.py [full|quick|repair]")
        sys.exit(1)


if __name__ == "__main__":
    main()
