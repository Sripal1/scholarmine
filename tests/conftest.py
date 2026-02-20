"""Shared test fixtures for ScholarMine."""

import os
import random

import pytest

from scholarmine.scraper import TorScholarSearch
from scholarmine.runner import CSVResearcherRunner

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def pytest_addoption(parser):
    parser.addoption(
        "--sample-size",
        type=int,
        default=None,
        help="Number of random researchers to test (default: all 176)",
    )
    parser.addoption(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries per researcher in integration tests (default: 3)",
    )


def _read_fixture(filename: str) -> str:
    with open(os.path.join(FIXTURES_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def profile_html():
    """Full Google Scholar profile page with 3 papers."""
    return _read_fixture("scholar_profile.html")


@pytest.fixture
def empty_profile_html():
    """Profile page with no papers."""
    return _read_fixture("scholar_profile_empty.html")


@pytest.fixture
def paper_citation_html():
    """Paper citation detail page with a description."""
    return _read_fixture("paper_citation.html")


@pytest.fixture
def test_scholar_urls():
    """All 176 Google Scholar URLs from the ai-map dataset."""
    urls_file = os.path.join(FIXTURES_DIR, "test_scholar_urls.txt")
    with open(urls_file, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


@pytest.fixture
def scraper():
    """TorScholarSearch instance without Tor connectivity (for parsing tests)."""
    instance = object.__new__(TorScholarSearch)
    instance.session = None
    instance.output_dir = None
    instance.max_retries = 3
    return instance


@pytest.fixture
def runner():
    """CSVResearcherRunner instance without Tor/init (for utility tests)."""
    instance = object.__new__(CSVResearcherRunner)
    return instance
