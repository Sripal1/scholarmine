"""Google Scholar scraper using Tor for IP rotation."""

import csv
import json
import logging
import os
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from stem import Signal
from stem.control import Controller

logger = logging.getLogger(__name__)

# Configuration constants
TOR_SOCKS_PROXY = "socks5h://127.0.0.1:9050"
TOR_CONTROL_PORT = 9051
TOR_IDENTITY_WAIT_SECONDS = 10
TOR_PROFILE_TIMEOUT_SECONDS = 20
TOR_PAPER_TIMEOUT_SECONDS = 15
TOR_IP_CHECK_TIMEOUT_SECONDS = 15
IP_CHECK_URL = "http://httpbin.org/ip"
DEFAULT_PAGE_SIZE = 50
CONSECUTIVE_PAPER_FAILURES_THRESHOLD = 2


class TorScholarSearch:
    """Google Scholar scraping using Tor for rotating IPs with Tor circuits."""

    def __init__(self, output_dir: str | None = None, max_retries: int = 3):
        """Initialize the Tor-based Scholar scraper.

        Args:
            output_dir: Directory to save scraped profiles. Defaults to "Researcher_Profiles".
            max_retries: Max retries per paper page fetch before giving up. Defaults to 3.
        """
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.proxies = {
            "http": TOR_SOCKS_PROXY,
            "https": TOR_SOCKS_PROXY,
        }
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/91.0.4472.124 Safari/537.36"
                )
            }
        )

        self.output_dir = output_dir

        self.get_new_identity()
        logger.info(f"Initial Tor IP: {self.get_current_ip()}")

    def get_new_identity(self) -> None:
        """Request new Tor circuit (new IP)."""
        try:
            with Controller.from_port(port=TOR_CONTROL_PORT) as controller:
                controller.authenticate()
                controller.signal(Signal.NEWNYM)
                time.sleep(TOR_IDENTITY_WAIT_SECONDS)
            logger.info("Requested new Tor identity")
        except Exception as e:
            logger.error(f"Failed to get new Tor identity: {e}")

    def get_current_ip(self) -> str:
        """Check current exit node IP."""
        try:
            response = self.session.get(IP_CHECK_URL, timeout=TOR_IP_CHECK_TIMEOUT_SECONDS)
            return response.json()["origin"]
        except Exception as e:
            logger.error(f"Failed to get current IP: {e}")
            return "Errored IP"

    def visit_author_profile_with_more_papers(
        self, profile_url: str, num_papers: int = 50
    ) -> str | None:
        """Visit author profile and try to load more papers.

        Args:
            profile_url: Google Scholar profile URL.
            num_papers: Number of papers to retrieve. Defaults to 50.

        Returns:
            HTML content of the profile page, or None on failure.
        """
        try:
            if "citations?user=" in profile_url:
                enhanced_url = (
                    f"{profile_url}&cstart=0&pagesize={num_papers}&sortby=citedby"
                )

                logger.info(f"Loading {num_papers} papers from: {enhanced_url}")
                response = self.session.get(enhanced_url, timeout=TOR_PROFILE_TIMEOUT_SECONDS)
                response.raise_for_status()

                logger.info("Successfully loaded author profile with more papers")
                return response.text
            else:
                response = self.session.get(profile_url, timeout=TOR_PROFILE_TIMEOUT_SECONDS)
                response.raise_for_status()
                return response.text

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to visit enhanced author profile: {e}")
            return None

    def visit_paper_page(self, paper_url: str) -> str | None:
        """Visit a researcher's paper page.

        Args:
            paper_url: URL of the paper citation page.

        Returns:
            HTML content of the paper page, or None on failure.
        """
        try:
            response = self.session.get(paper_url, timeout=TOR_PAPER_TIMEOUT_SECONDS)
            response.raise_for_status()

            logger.info("Successfully visited paper page")
            return response.text

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to visit paper page: {e}")
            return None

    def extract_paper_description(self, html_content: str) -> str:
        """Extract the Abstract/description from a paper's citation page.

        Args:
            html_content: HTML content of the paper page.

        Returns:
            Paper description or "Description not available".
        """
        soup = BeautifulSoup(html_content, "html.parser")

        description = None

        desc_rows = soup.find_all("div", class_="gs_scl")
        for row in desc_rows:
            if "Description" in row.get_text():
                text = row.get_text()
                if "Description" in text:
                    description = text.split("Description", 1)[-1].strip()
                    description = " ".join(description.split())
                    break

        return description if description else "Description not available"

    def parse_author_profile(self, html_content: str) -> list[dict] | None:
        """Parse author profile page to extract top cited papers.

        Args:
            html_content: HTML content of the profile page.

        Returns:
            List of paper dictionaries, or None if no papers found.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        papers = []

        paper_rows = soup.find_all("tr", {"class": "gsc_a_tr"})

        if not paper_rows:
            paper_rows = soup.find_all("tr", {"class": "gsc_tr"}) or soup.find_all(
                "a", {"class": "gsc_a_at"}
            )

        total_papers = min(len(paper_rows), DEFAULT_PAGE_SIZE)
        consecutive_failures = 0
        for i, row in enumerate(paper_rows[:DEFAULT_PAGE_SIZE]):
            try:
                title_link = row.find("a", {"class": "gsc_a_at"})
                if not title_link:
                    title_link = row.find("a")

                if title_link:
                    title = title_link.get_text().strip()
                    paper_url = title_link.get("href")

                    if paper_url and paper_url.startswith("/"):
                        paper_url = urljoin("https://scholar.google.com", paper_url)

                    citation_cell = row.find("a", {"class": "gsc_a_ac"})
                    citations = "0"
                    if citation_cell and citation_cell.get_text().strip():
                        citations = citation_cell.get_text().strip()

                    year_cell = row.find("span", {"class": "gsc_a_h"})
                    year = "Unknown"
                    if year_cell:
                        year = year_cell.get_text().strip()

                    description = "Description not available"
                    fetched = False
                    if paper_url and paper_url != "No URL available":
                        logger.info(
                            f"Fetching description for paper {i+1}: {title[:50]}..."
                        )
                        for attempt in range(self.max_retries):
                            paper_content = self.visit_paper_page(paper_url)
                            if paper_content:
                                description = self.extract_paper_description(paper_content)
                                fetched = True
                                break
                            logger.warning(
                                f"Paper page fetch failed (attempt {attempt + 1}/{self.max_retries}), "
                                "rotating IP and retrying..."
                            )
                            self.get_new_identity()

                    if fetched:
                        consecutive_failures = 0
                    elif paper_url and paper_url != "No URL available":
                        consecutive_failures += 1
                        if consecutive_failures >= CONSECUTIVE_PAPER_FAILURES_THRESHOLD:
                            logger.warning(
                                f"{consecutive_failures} consecutive paper fetches failed "
                                f"(paper {i+1}/{total_papers}) — likely rate-limited, aborting"
                            )
                            return None

                    papers.append(
                        {
                            "rank": i + 1,
                            "title": title,
                            "url": paper_url,
                            "citations": citations,
                            "year": year,
                            "description": description,
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to parse paper {i+1}: {e}")
                continue

        return papers if papers else None

    def extract_research_keywords(self, html_content: str) -> str:
        """Extract research keywords from the researcher's profile.

        Args:
            html_content: HTML content of the profile page.

        Returns:
            Comma-separated keywords or status message.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        meta_desc = soup.find("meta", {"name": "description"})
        if not meta_desc:
            meta_desc = soup.find("meta", {"property": "og:description"})

        if meta_desc and meta_desc.get("content"):
            content = meta_desc.get("content")
            parts = content.split(" - ")
            keywords = []

            for part in parts[2:]:
                keyword = part.strip().replace("\u202a", "").replace("\u202c", "")
                if keyword and not keyword.startswith(
                    "Cited by"
                ) and not keyword.startswith("\u202aCited by"):
                    keywords.append(keyword)

            return ", ".join(keywords) if keywords else "Research areas not specified"

        return "Research areas not available"

    def extract_homepage(self, html_content: str) -> str:
        """Extract homepage URL from the author's profile page.

        Args:
            html_content: HTML content of the profile page.

        Returns:
            Homepage URL or "Homepage not specified".
        """
        soup = BeautifulSoup(html_content, "html.parser")

        homepage_div = soup.find("div", {"id": "gsc_prf_ivh"})
        if homepage_div:
            homepage_link = homepage_div.find("a", {"class": "gsc_prf_ila"})
            if homepage_link and homepage_link.get("href"):
                href = homepage_link.get("href")
                if (
                    href.startswith(("http://", "https://"))
                    and "scholar.google" not in href
                    and "google.com" not in href
                ):
                    return href

        return "Homepage not specified"

    def extract_author_name_from_profile(self, html_content: str) -> str:
        """Extract the author's name from their profile page.

        Args:
            html_content: HTML content of the profile page.

        Returns:
            Author name or "Unknown Author".
        """
        soup = BeautifulSoup(html_content, "html.parser")

        name_element = soup.find("div", {"id": "gsc_prf_in"})
        if name_element:
            return name_element.get_text().strip()

        title = soup.find("title")
        if title:
            title_text = title.get_text()
            if " - Google Scholar" in title_text:
                return title_text.replace(" - Google Scholar", "").strip()

        return "Unknown Author"

    def extract_author_affiliation_from_profile(self, html_content: str) -> str:
        """Extract the author's affiliation from their profile page.

        Args:
            html_content: HTML content of the profile page.

        Returns:
            Affiliation or "Unknown affiliation".
        """
        soup = BeautifulSoup(html_content, "html.parser")

        affiliation_element = soup.find("div", {"class": "gsc_prf_il"})
        if affiliation_element:
            return affiliation_element.get_text().strip()

        return "Unknown affiliation"

    def extract_author_citations_from_profile(self, html_content: str) -> str:
        """Extract the author's total citation count from their profile page.

        Args:
            html_content: HTML content of the profile page.

        Returns:
            Citation count or "N/A".
        """
        soup = BeautifulSoup(html_content, "html.parser")

        citation_cells = soup.find_all("td", {"class": "gsc_rsb_std"})
        if citation_cells:
            return citation_cells[0].get_text().strip()

        return "N/A"

    def create_researcher_folder(
        self, folder_name: str, base_output_dir: str | None = None
    ) -> str:
        """Create a folder for the researcher and return the path.

        Args:
            folder_name: Name for the researcher's folder (usually Scholar ID).
            base_output_dir: Base directory for output. Defaults to "Researcher_Profiles".

        Returns:
            Path to the created folder.
        """
        clean_name = folder_name.strip()

        base_folder = base_output_dir or "Researcher_Profiles"
        researcher_folder = os.path.join(base_folder, clean_name)

        os.makedirs(researcher_folder, exist_ok=True)

        return researcher_folder

    def save_profile_json(self, profile_data: dict, folder_path: str) -> bool:
        """Save profile data as JSON file.

        Args:
            profile_data: Dictionary containing profile information.
            folder_path: Path to save the JSON file.

        Returns:
            True if successful, False otherwise.
        """
        json_path = os.path.join(folder_path, "profile.json")

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(profile_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved profile JSON to: {json_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save profile JSON: {e}")
            return False

    def save_papers_csv(self, papers_data: list[dict], folder_path: str) -> bool:
        """Save papers data as CSV file.

        Args:
            papers_data: List of paper dictionaries.
            folder_path: Path to save the CSV file.

        Returns:
            True if successful, False otherwise.
        """
        csv_path = os.path.join(folder_path, "papers.csv")

        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                if papers_data:
                    fieldnames = [
                        "Rank",
                        "Title",
                        "Citations",
                        "Year",
                        "URL",
                        "Description",
                    ]
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()

                    for paper in papers_data:
                        writer.writerow(
                            {
                                "Rank": paper["rank"],
                                "Title": paper["title"],
                                "Citations": paper["citations"],
                                "Year": paper["year"],
                                "URL": paper["url"],
                                "Description": paper["description"],
                            }
                        )
                else:
                    writer = csv.writer(f)
                    writer.writerow(
                        ["Rank", "Title", "Citations", "Year", "URL", "Description"]
                    )

            logger.info(f"Saved papers CSV to: {csv_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save papers CSV: {e}")
            return False

    def scrape_researcher_by_scholar_id(
        self, scholar_id: str, researcher_name: str | None = None
    ) -> dict:
        """Main method to scrape a researcher directly using their Google Scholar ID.

        Args:
            scholar_id: Google Scholar user ID.
            researcher_name: Optional name to use for display.

        Returns:
            Dictionary with scrape results including success status.
        """
        logger.info(
            f"Starting Tor-enabled Scholar scraping for Scholar ID: {scholar_id}"
        )

        try:
            if not scholar_id or len(scholar_id) < 5:
                return {"success": False, "error": "Invalid Scholar ID format"}

            profile_url = (
                f"https://scholar.google.com/citations?user={scholar_id}&hl=en"
            )
            logger.info(f"Direct profile URL: {profile_url}")

            profile_content = self.visit_author_profile_with_more_papers(
                profile_url, num_papers=DEFAULT_PAGE_SIZE
            )
            if not profile_content:
                return {
                    "success": False,
                    "error": (
                        "Failed to access profile page - "
                        "Scholar ID may not exist or be blocked"
                    ),
                }

            author_name = self.extract_author_name_from_profile(profile_content)
            author_affiliation = self.extract_author_affiliation_from_profile(
                profile_content
            )
            author_citations = self.extract_author_citations_from_profile(
                profile_content
            )

            display_name = researcher_name if researcher_name else author_name

            logger.info(f"Found profile: {author_name} ({author_affiliation})")

            research_keywords = self.extract_research_keywords(profile_content)
            homepage = self.extract_homepage(profile_content)

            papers = self.parse_author_profile(profile_content)
            if not papers:
                return {"success": False, "error": "No papers found in author profile"}

            logger.info(f"Found {len(papers)} papers from author profile")

            folder_path = self.create_researcher_folder(scholar_id, self.output_dir)

            profile_data = {
                "scholar_id": scholar_id,
                "profile_url": profile_url,
                "author_name": author_name,
                "author_affiliation": author_affiliation,
                "author_citations": author_citations,
                "research_keywords": research_keywords,
                "homepage": homepage,
                "tor_ip_used": self.get_current_ip(),
                "scrape_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "scrape_method": "direct_scholar_id",
            }

            profile_saved = self.save_profile_json(profile_data, folder_path)
            papers_saved = self.save_papers_csv(papers, folder_path)

            if profile_saved and papers_saved:
                return {
                    "success": True,
                    "researcher_name": display_name,
                    "author_name": author_name,
                    "scholar_id": scholar_id,
                    "affiliation": author_affiliation,
                    "citations": author_citations,
                    "papers_count": len(papers),
                    "folder_path": folder_path,
                    "tor_ip": self.get_current_ip(),
                }
            else:
                return {"success": False, "error": "Failed to save data"}

        except Exception as e:
            logger.error(f"Error scraping researcher by Scholar ID {scholar_id}: {e}")
            return {"success": False, "error": str(e)}
