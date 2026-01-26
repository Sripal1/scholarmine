"""
ScholarMine - Google Scholar scraper using Tor for IP rotation.

A Python package for scraping Google Scholar profiles and publications
using Tor for anonymization and IP rotation.
"""

__version__ = "0.1.0"
__author__ = "Sri Ranganathan Palaniappan"

from .ip_tracker import IPTracker
from .scraper import TorScholarSearch
from .runner import CSVResearcherRunner

__all__ = [
    "IPTracker",
    "TorScholarSearch",
    "CSVResearcherRunner",
]
