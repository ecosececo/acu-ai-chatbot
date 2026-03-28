"""
Bologna System Scraper — Scrapes academic data from obs.acibadem.edu.tr

Uses Playwright (headless Chromium) because the OBS system is ASP.NET WebForms
and renders content via JavaScript __doPostBack calls for in-page navigation.

Key discovery: Sub-pages have DIRECT URLs like progAbout.aspx, progCourses.aspx
which return clean content areas without full page chrome. The main index.aspx
page requires JS clicks, but individual content pages can be loaded directly.

Discovery page unitSelection.aspx lists all faculties/programs hierarchically.

Collects: programs, courses, curricula, learning outcomes, ECTS credits,
          admission requirements, graduation conditions, academic staff.
"""

import logging
import re
import time
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# Bologna system base URL
BOLOGNA_BASE = "https://obs.acibadem.edu.tr/oibs/bologna/"

# ── Direct sub-page URLs ─────────────────────────────────────
# These are separate .aspx files that return clean content when loaded directly.
# Pattern: {page}.aspx?lang=tr&curSunit={sunit_id}
SUB_PAGES = [
    {"page": "progGoalsObjectives.aspx", "label": "Eğitim Türü (Amaçlar) ve Hedefler"},
    {"page": "progAbout.aspx", "label": "Program Hakkında"},
    {"page": "progProfile.aspx", "label": "Program Profili"},
    {"page": "progOfficials.aspx", "label": "Program Yetkilileri"},
    {"page": "progDegree.aspx", "label": "Alınacak Derece"},
    {"page": "progAdmissionReq.aspx", "label": "Kabul Koşulları"},
    {"page": "progAccessFurhterStudies.aspx", "label": "Üst Kademeye Geçiş"},  # Note: typo in original
    {"page": "progGraduationReq.aspx", "label": "Mezuniyet Koşulları"},
    {"page": "progRecogPriorLearning.aspx", "label": "Önceki Öğrenmenin Tanınması"},
    {"page": "progQualifyReqReg.aspx", "label": "Yeterlilik Koşulları ve Kuralları"},
    {"page": "progOccupationalProf.aspx", "label": "İstihdam Olanakları"},
    {"page": "progLearnOutcomes.aspx", "label": "Program Yeterlikleri"},
    {"page": "progCourses.aspx", "label": "Dersler"},
    {"page": "progCourseMatrix.aspx", "label": "Ders & Program Yeterlilikleri İlişkisi"},
    {"page": "progTYYCMatrix.aspx", "label": "TYYÇ - Program Yeterlilikleri İlişkisi"},
    {"page": "progAcademicStaff.aspx", "label": "Akademik Personel"},
    {"page": "progContact.aspx", "label": "İletişim"},
]

# ── Program discovery URLs ───────────────────────────────────
# unitSelection.aspx?type=X returns all programs for that education level
UNIT_SELECTION_URLS = [
    {"type": "lis", "label": "Lisans", "level": "lisans"},
    {"type": "onl", "label": "Ön Lisans", "level": "onlisans"},
    {"type": "yls", "label": "Yüksek Lisans", "level": "yuksek_lisans"},
    {"type": "dok", "label": "Doktora", "level": "doktora"},
]

# ── Fallback: Known program unit IDs ─────────────────────────
# Used if dynamic discovery fails
FALLBACK_PROGRAMS = [
    # Lisans - Fakülteler
    {"curSunit": "6", "name": "Tıp Fakültesi", "level": "lisans", "category": "faculty"},
    {"curSunit": "62", "name": "Eczacılık Fakültesi", "level": "lisans", "category": "faculty"},
    {"curSunit": "63", "name": "Sağlık Bilimleri Fakültesi", "level": "lisans", "category": "faculty"},
    {"curSunit": "64", "name": "Mühendislik ve Doğa Bilimleri Fakültesi", "level": "lisans", "category": "faculty"},
    {"curSunit": "65", "name": "İnsan ve Toplum Bilimleri Fakültesi", "level": "lisans", "category": "faculty"},
    # Lisans - Bölümler
    {"curSunit": "6246", "name": "Bilgisayar Mühendisliği", "level": "lisans", "category": "department"},
    {"curSunit": "6247", "name": "Biyomedikal Mühendisliği", "level": "lisans", "category": "department"},
    {"curSunit": "6410", "name": "Yazılım Mühendisliği", "level": "lisans", "category": "department"},
    {"curSunit": "6411", "name": "Yapay Zeka Mühendisliği", "level": "lisans", "category": "department"},
    {"curSunit": "6205", "name": "Hemşirelik", "level": "lisans", "category": "department"},
    {"curSunit": "6206", "name": "Fizyoterapi ve Rehabilitasyon", "level": "lisans", "category": "department"},
    {"curSunit": "6207", "name": "Beslenme ve Diyetetik", "level": "lisans", "category": "department"},
    {"curSunit": "6208", "name": "Sağlık Yönetimi", "level": "lisans", "category": "department"},
    {"curSunit": "6209", "name": "Odyoloji", "level": "lisans", "category": "department"},
    {"curSunit": "6210", "name": "Dil ve Konuşma Terapisi", "level": "lisans", "category": "department"},
    {"curSunit": "6211", "name": "Ergoterapi", "level": "lisans", "category": "department"},
    {"curSunit": "6245", "name": "Moleküler Biyoloji ve Genetik", "level": "lisans", "category": "department"},
    {"curSunit": "6248", "name": "Endüstri Mühendisliği", "level": "lisans", "category": "department"},
    {"curSunit": "6244", "name": "Psikoloji", "level": "lisans", "category": "department"},
    {"curSunit": "6412", "name": "Gastronomi ve Mutfak Sanatları", "level": "lisans", "category": "department"},
    # Ön Lisans
    {"curSunit": "7", "name": "Sağlık Hizmetleri MYO", "level": "onlisans", "category": "faculty"},
    {"curSunit": "7101", "name": "Ağız ve Diş Sağlığı", "level": "onlisans", "category": "department"},
    {"curSunit": "7102", "name": "Ameliyathane Hizmetleri", "level": "onlisans", "category": "department"},
    {"curSunit": "7103", "name": "Anestezi", "level": "onlisans", "category": "department"},
    {"curSunit": "7104", "name": "Diyaliz", "level": "onlisans", "category": "department"},
    {"curSunit": "7105", "name": "Fizyoterapi", "level": "onlisans", "category": "department"},
    {"curSunit": "7106", "name": "İlk ve Acil Yardım", "level": "onlisans", "category": "department"},
    {"curSunit": "7107", "name": "Optisyenlik", "level": "onlisans", "category": "department"},
    {"curSunit": "7108", "name": "Odyometri", "level": "onlisans", "category": "department"},
    {"curSunit": "7109", "name": "Patoloji Laboratuvar Teknikleri", "level": "onlisans", "category": "department"},
    {"curSunit": "7110", "name": "Radyoterapi", "level": "onlisans", "category": "department"},
    {"curSunit": "7111", "name": "Tıbbi Görüntüleme Teknikleri", "level": "onlisans", "category": "department"},
    {"curSunit": "7112", "name": "Tıbbi Laboratuvar Teknikleri", "level": "onlisans", "category": "department"},
    # Lisansüstü
    {"curSunit": "8", "name": "Lisansüstü Eğitim Enstitüsü", "level": "lisansustu", "category": "faculty"},
]


def _clean_rendered_text(raw_text: str) -> str:
    """Clean text extracted from a rendered Bologna page."""
    if not raw_text:
        return ""

    lines = raw_text.split("\n")
    cleaned = []
    seen = set()

    # Navigation/menu items to skip
    skip_patterns = re.compile(
        r"^(Kurumsal Bilgiler|Akademik Birimler|Bilgi Paketi|"
        r"Öğrenciler İçin Genel Bilgiler|Erasmus Beyannamesi|Bologna Süreci|"
        r"Yönetim|AKTS Kataloğu|"
        r"Şehir Hakkında|Kampüs$|Yemek$|Sağlık Hizmetleri$|Spor ve Sosyal Yaşam$|"
        r"Öğrenci Kulüpleri|Konaklama$|Engelli Öğrenci|"
        r"^\s*EN\s*$|^\s*TR\s*$|^\s*English\s*$|©|Tüm Hakları|"
        r"Acıbadem Mehmet Ali Aydınlar)",
        re.IGNORECASE,
    )

    for line in lines:
        line = line.strip()
        if not line or len(line) < 4:
            continue
        if skip_patterns.search(line):
            continue
        if line in seen:
            continue
        seen.add(line)
        cleaned.append(line)

    return "\n".join(cleaned)


def _extract_tables_from_html(html: str) -> str:
    """Extract table data from HTML and format as structured text."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        table_texts = []

        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = []
                for td in tr.find_all(["th", "td"]):
                    cell_text = td.get_text(strip=True)
                    if cell_text:
                        cells.append(cell_text)
                if cells:
                    rows.append(" | ".join(cells))

            if rows:
                table_texts.append("\n".join(rows))

        return "\n\n".join(table_texts)
    except Exception:
        return ""


class BolognaScraper:
    """
    Scraper for the ACU Bologna/OBS system using Playwright.

    Uses headless Chromium to render ASP.NET WebForms pages.
    Leverages direct sub-page URLs (progAbout.aspx, progCourses.aspx, etc.)
    for efficient content extraction, and unitSelection.aspx for program discovery.
    """

    def __init__(self):
        self.delay = getattr(settings, "SCRAPE_DELAY", 2.0)
        self.visited = set()
        self._playwright = None
        self._browser = None
        self._context = None

    def _start_browser(self):
        """Start Playwright browser instance."""
        if self._browser:
            return

        try:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--disable-translate",
                    "--mute-audio",
                    "--no-first-run",
                ],
            )
            self._context = self._browser.new_context(
                locale="tr-TR",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            logger.info("Playwright browser started successfully")
        except Exception as e:
            logger.error(f"Failed to start Playwright browser: {e}")
            raise

    def _stop_browser(self):
        """Stop Playwright browser instance."""
        try:
            if self._context:
                self._context.close()
                self._context = None
            if self._browser:
                self._browser.close()
                self._browser = None
            if self._playwright:
                self._playwright.stop()
                self._playwright = None
            logger.info("Playwright browser stopped")
        except Exception as e:
            logger.warning(f"Error stopping browser: {e}")

    def _build_subpage_url(self, cur_sunit: str, page_name: str) -> str:
        """Build a direct sub-page URL."""
        return f"{BOLOGNA_BASE}{page_name}?lang=tr&curSunit={cur_sunit}"

    def _build_index_url(self, cur_sunit: str) -> str:
        """Build the main index page URL for a program."""
        return (
            f"{BOLOGNA_BASE}index.aspx?"
            f"lang=tr&curOp=showPac&curUnit=14&curSunit={cur_sunit}"
        )

    def scrape_subpage(
        self, url: str, name: str = "", category: str = "academic"
    ) -> Optional[dict]:
        """
        Scrape a single Bologna sub-page (progAbout.aspx, progCourses.aspx, etc.).

        These pages return clean content areas without navigation chrome,
        making extraction much cleaner than the main index.aspx page.

        Returns:
            dict with keys: url, title, content, html, category, language, source
            or None if scraping failed or content is empty
        """
        if url in self.visited:
            return None

        self.visited.add(url)

        try:
            self._start_browser()

            page = self._context.new_page()
            page.set_default_timeout(30000)

            logger.info(f"Scraping Bologna: {name or url}")

            # Navigate and wait for content to render
            page.goto(url, wait_until="networkidle")

            # Wait for tables or content to appear
            try:
                page.wait_for_selector("table, .content, p, div", timeout=10000)
            except Exception:
                pass

            # Additional wait for ASP.NET dynamic content
            page.wait_for_timeout(1000)

            # Get rendered HTML for table extraction
            html = page.content()

            # Get rendered text content from body
            try:
                raw_text = page.inner_text("body")
            except Exception:
                raw_text = ""

            # Also extract structured table data
            table_text = _extract_tables_from_html(html)

            page.close()

            # Combine text and table data
            cleaned_text = _clean_rendered_text(raw_text)

            if table_text:
                # Prefer table data if available (courses, credits, etc.)
                if cleaned_text:
                    content = f"{cleaned_text}\n\n--- Tablo Verileri ---\n{table_text}"
                else:
                    content = table_text
            else:
                content = cleaned_text

            if len(content.strip()) < 30:
                logger.debug(f"Skipping low-content Bologna page: {url}")
                return None

            title = name if name else "Bologna Bilgi Paketi"

            return {
                "url": url,
                "title": title,
                "content": content,
                "html": html[:50000],
                "category": category,
                "language": "tr",
                "source": "bologna",
            }

        except Exception as e:
            logger.warning(f"Failed to scrape Bologna page {url}: {e}")
            return None

    def scrape_index_page(
        self, cur_sunit: str, name: str = "", category: str = "academic"
    ) -> Optional[dict]:
        """
        Scrape the main index.aspx page for a program.
        This page shows the default info (Eğitim Türü ve Hedefler).
        """
        url = self._build_index_url(cur_sunit)
        return self.scrape_subpage(url, name=name, category=category)

    def scrape_program(
        self, unit: dict, callback=None
    ) -> list[dict]:
        """
        Scrape all info package pages for a single program/department.

        Uses direct sub-page URLs for efficient content extraction.

        Args:
            unit: Dict with curSunit, name, level, category
            callback: Optional progress callback

        Returns:
            List of scraped page data dicts
        """
        results = []
        cur_sunit = unit["curSunit"]
        program_name = unit["name"]

        logger.info(f"Scraping program: {program_name} (sunit={cur_sunit})")

        # First scrape the main index page (general info)
        index_data = self.scrape_index_page(
            cur_sunit,
            name=f"{program_name} - Genel Bilgiler",
            category=unit["category"],
        )
        if index_data:
            results.append(index_data)
            if callback:
                callback(index_data, len(results), 0)

        time.sleep(self.delay * 0.5)  # Shorter delay for sub-pages

        # Then scrape each sub-page via direct URLs
        for sub in SUB_PAGES:
            url = self._build_subpage_url(cur_sunit, sub["page"])
            page_name = f"{program_name} - {sub['label']}"

            if url in self.visited:
                continue

            page_data = self.scrape_subpage(
                url, name=page_name, category=unit["category"]
            )

            if page_data:
                results.append(page_data)

                if callback:
                    callback(page_data, len(results), 0)

                logger.info(
                    f"  ✓ {sub['label']}: {len(page_data['content'])} chars"
                )
            else:
                logger.debug(f"  ✗ {sub['label']}: no content")

            # Short delay between sub-pages (same session)
            time.sleep(self.delay * 0.5)

        return results

    def discover_programs(self) -> list[dict]:
        """
        Discover all programs by scraping unitSelection.aspx pages.

        The unitSelection.aspx page lists all faculties/programs hierarchically
        for each education level (lisans, onlisans, yuksek lisans, doktora).

        Falls back to FALLBACK_PROGRAMS if discovery fails.

        Returns:
            List of dicts with curSunit, name, level, category
        """
        discovered = []

        try:
            self._start_browser()

            for unit_type in UNIT_SELECTION_URLS:
                url = f"{BOLOGNA_BASE}unitSelection.aspx?type={unit_type['type']}&lang=tr"
                logger.info(f"Discovering {unit_type['label']} programs from {url}")

                page = self._context.new_page()
                page.set_default_timeout(20000)

                try:
                    page.goto(url, wait_until="networkidle")
                    page.wait_for_timeout(2000)

                    # Find all links with curSunit parameters
                    links = page.query_selector_all("a[href*='curSunit']")

                    for link in links:
                        try:
                            href = link.get_attribute("href") or ""
                            text = link.inner_text().strip()

                            match = re.search(r"curSunit=(\d+)", href)
                            if match and text and len(text) > 2:
                                sunit = match.group(1)
                                # Avoid duplicates
                                if not any(d["curSunit"] == sunit for d in discovered):
                                    discovered.append({
                                        "curSunit": sunit,
                                        "name": text,
                                        "level": unit_type["level"],
                                        "category": "department",
                                    })
                        except Exception:
                            continue

                    logger.info(
                        f"  Found {len([d for d in discovered if d['level'] == unit_type['level']])} "
                        f"{unit_type['label']} programs"
                    )

                except Exception as e:
                    logger.warning(f"  Discovery failed for {unit_type['label']}: {e}")
                finally:
                    page.close()

                time.sleep(self.delay)

        except Exception as e:
            logger.warning(f"Program discovery failed: {e}")

        if discovered:
            logger.info(f"Discovered {len(discovered)} total programs dynamically")
            return discovered

        logger.info(f"Using {len(FALLBACK_PROGRAMS)} fallback program definitions")
        return FALLBACK_PROGRAMS

    def scrape_all(self, callback=None) -> list[dict]:
        """
        Scrape all Bologna program pages and their info packages.

        Strategy:
        1. Discover all programs via unitSelection.aspx
        2. For each program, scrape the index page and all sub-pages
        3. Use direct sub-page URLs for clean content extraction

        Args:
            callback: Optional function called with (page_data, current_count, total_urls)

        Returns:
            List of scraped page data dicts
        """
        results = []
        max_pages = getattr(settings, "SCRAPE_MAX_PAGES", 500)

        try:
            self._start_browser()

            # Step 1: Discover programs
            programs = self.discover_programs()
            if not programs:
                programs = FALLBACK_PROGRAMS

            total_programs = len(programs)
            logger.info(f"Starting Bologna scrape for {total_programs} programs")

            # Step 2: Scrape each program
            for i, unit in enumerate(programs, 1):
                if len(results) >= max_pages:
                    logger.info(f"Reached max pages limit ({max_pages})")
                    break

                logger.info(
                    f"[{i}/{total_programs}] Scraping: {unit['name']} ({unit['level']})"
                )

                program_results = self.scrape_program(unit, callback)
                results.extend(program_results)

                logger.info(
                    f"  → Got {len(program_results)} pages for {unit['name']}"
                )

        except Exception as e:
            logger.error(f"Bologna scraping error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._stop_browser()

        logger.info(f"Bologna scraping complete. Total pages: {len(results)}")
        return results
