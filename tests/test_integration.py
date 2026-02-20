"""Integration tests requiring Tor and network access.

Run with:
    pytest -m integration
    pytest -m integration --sample-size 5   # quick check with 5 researchers
    pytest -m integration --max-retries 5   # more retries per researcher

Tor is auto-started if not already running and cleaned up after the session.

These tests hit real Google Scholar through Tor. They are slow and may
fail if Google rate-limits the exit node.

The test URLs are sourced from the ai-map dataset (176 Georgia Tech
CS faculty Scholar profiles) stored in tests/fixtures/test_scholar_urls.txt.
"""

import logging
import os
import re
import subprocess
import tempfile
import time

import pytest

from scholarmine.scraper import TorScholarSearch

logger = logging.getLogger(__name__)

RETRY_WAIT_SECONDS = 20
TOR_CONTROL_PORT = 9051
TOR_STARTUP_TIMEOUT_SECONDS = 30

pytestmark = pytest.mark.integration


def _is_tor_available() -> bool:
    try:
        from stem.control import Controller

        with Controller.from_port(port=TOR_CONTROL_PORT) as controller:
            controller.authenticate()
            return True
    except Exception:
        return False


def _extract_scholar_id(url: str) -> str | None:
    match = re.search(r"user=([^&]+)", url)
    return match.group(1) if match else None


@pytest.fixture(scope="session")
def ensure_tor():
    """Start Tor if not already running; stop it after the test session."""
    if _is_tor_available():
        logger.info("Tor is already running — reusing existing instance")
        yield
        return

    logger.info("Tor not running — starting it automatically for tests...")
    tor_process = subprocess.Popen(
        ["tor", "--controlport", str(TOR_CONTROL_PORT), "--cookieauthentication", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    for i in range(TOR_STARTUP_TIMEOUT_SECONDS):
        if _is_tor_available():
            logger.info(f"Tor is ready after {i + 1} seconds")
            break
        time.sleep(1)
    else:
        tor_process.terminate()
        tor_process.wait()
        pytest.fail(
            f"Tor failed to start within {TOR_STARTUP_TIMEOUT_SECONDS}s. "
            "Ensure Tor is installed (e.g. `brew install tor`).",
            pytrace=False,
        )

    yield

    logger.info("Stopping Tor process started by tests...")
    tor_process.terminate()
    try:
        tor_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        tor_process.kill()
        tor_process.wait()


@pytest.fixture(scope="module")
def tor_scraper(ensure_tor):
    """A single TorScholarSearch instance reused across the module."""
    return TorScholarSearch()


@pytest.fixture
def max_retries(request):
    """Max retry attempts from --max-retries CLI option."""
    return request.config.getoption("--max-retries")


@pytest.fixture
def sample_urls(request, test_scholar_urls):
    """URLs from the fixture file.

    By default returns all 176 URLs. Pass ``--sample-size N`` to pytest
    to randomly sample N URLs instead.
    """
    sample_size = request.config.getoption("--sample-size", default=None)
    if sample_size is not None:
        import random

        return random.sample(test_scholar_urls, min(sample_size, len(test_scholar_urls)))
    return test_scholar_urls


def _scrape_with_retries(tor_scraper, scholar_id, max_retries):
    """Scrape a profile, retrying with IP rotation on failure."""
    for attempt in range(1, max_retries + 1):
        result = tor_scraper.scrape_researcher_by_scholar_id(scholar_id)
        if result["success"]:
            return result

        if attempt < max_retries:
            tor_scraper.get_new_identity()
            time.sleep(RETRY_WAIT_SECONDS)

    return result


def _fetch_html_with_retries(tor_scraper, profile_url, max_retries):
    """Fetch raw profile HTML, retrying with IP rotation on failure."""
    for attempt in range(1, max_retries + 1):
        html = tor_scraper.visit_author_profile_with_more_papers(profile_url)
        if html is not None:
            return html

        if attempt < max_retries:
            tor_scraper.get_new_identity()
            time.sleep(RETRY_WAIT_SECONDS)

    return None


# ── Tor connectivity ────────────────────────────────────────────────


class TestTorConnectivity:
    def test_tor_connects(self, tor_scraper):
        ip = tor_scraper.get_current_ip()
        assert ip != "Errored IP", "Could not reach IP check service through Tor"
        assert ip, "IP was empty"

    def test_ip_rotation_gives_different_ip(self, tor_scraper):
        ip_before = tor_scraper.get_current_ip()
        tor_scraper.get_new_identity()
        ip_after = tor_scraper.get_current_ip()

        # Not guaranteed to differ (Tor may reuse circuits), but at
        # minimum both calls should succeed.
        assert ip_before != "Errored IP"
        assert ip_after != "Errored IP"


# ── Live scraping ───────────────────────────────────────────────────


class TestLiveScraping:
    """Scrape profiles and validate the output structure."""

    def test_scrape_profiles_from_url_file(self, tor_scraper, sample_urls, max_retries):
        """Core integration test: scrape profiles with retries and check structure."""
        assert len(sample_urls) > 0, "No URLs in fixture file"

        for url in sample_urls:
            scholar_id = _extract_scholar_id(url)
            assert scholar_id, f"Could not parse Scholar ID from {url}"

            result = _scrape_with_retries(tor_scraper, scholar_id, max_retries)
            assert result["success"], (
                f"Failed to scrape {scholar_id} after {max_retries} attempts: "
                f"{result.get('error', 'unknown error')}"
            )
            self._assert_valid_success(result, scholar_id)

    def test_profile_html_contains_expected_elements(self, tor_scraper, sample_urls, max_retries):
        """Verify the raw HTML from Scholar has the CSS classes we parse."""
        url = sample_urls[0]
        scholar_id = _extract_scholar_id(url)
        profile_url = f"https://scholar.google.com/citations?user={scholar_id}&hl=en"

        html = _fetch_html_with_retries(tor_scraper, profile_url, max_retries)
        assert html is not None, (
            f"Could not fetch profile for {scholar_id} after {max_retries} attempts"
        )

        # These are the CSS selectors the parser relies on.
        # If any are missing, the scraper's DOM assumptions are stale.
        assert "gsc_prf_in" in html, "Author name div missing from Scholar HTML"
        assert "gsc_a_tr" in html or "gsc_a_at" in html, (
            "Paper rows missing from Scholar HTML"
        )

    def _assert_valid_success(self, result: dict, scholar_id: str) -> None:
        assert result.get("author_name"), "author_name is empty"
        assert result["author_name"] != "Unknown Author", (
            f"Parser returned Unknown Author for {scholar_id}"
        )
        assert result.get("affiliation"), "affiliation is empty"
        assert result.get("papers_count", 0) > 0, "No papers found"
        assert result.get("folder_path"), "folder_path is empty"
        assert os.path.isdir(result["folder_path"]), (
            f"Output folder not created: {result['folder_path']}"
        )

        # Verify output files exist and are non-empty
        profile_json = os.path.join(result["folder_path"], "profile.json")
        papers_csv = os.path.join(result["folder_path"], "papers.csv")
        assert os.path.isfile(profile_json), "profile.json not created"
        assert os.path.isfile(papers_csv), "papers.csv not created"
        assert os.path.getsize(profile_json) > 10, "profile.json is empty"
        assert os.path.getsize(papers_csv) > 10, "papers.csv is empty"


# ── Full pipeline ───────────────────────────────────────────────────


class TestFullPipeline:
    """End-to-end test: CSV in → scraped profiles out."""

    def test_single_researcher_csv_pipeline(self, ensure_tor, sample_urls, max_retries):
        """Create a 1-researcher CSV and run the full runner pipeline."""
        from scholarmine.runner import CSVResearcherRunner

        url = sample_urls[0]
        scholar_id = _extract_scholar_id(url)

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_researchers.csv")
            output_dir = os.path.join(tmpdir, "output")

            with open(csv_path, "w") as f:
                f.write("name,google_scholar_url\n")
                f.write(f"GT Researcher,{url}\n")

            runner = CSVResearcherRunner(
                csv_file=csv_path,
                max_threads=1,
                max_requests_per_ip=10,
                output_dir=output_dir,
                max_retries=max_retries,
            )
            results = runner.process_researchers_from_csv()

            # Verify the runner produced results
            assert len(results) > 0, "Runner returned no results"

            # Verify output directory was created with researcher data
            researcher_dir = os.path.join(output_dir, scholar_id)
            assert os.path.isdir(researcher_dir), (
                f"Output directory not created for {scholar_id}"
            )
            assert os.path.isfile(os.path.join(researcher_dir, "profile.json"))
            assert os.path.isfile(os.path.join(researcher_dir, "papers.csv"))
