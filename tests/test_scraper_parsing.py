"""Unit tests for scraper HTML parsing functions.

These test the core extraction logic against saved HTML fixtures.
No network or Tor required.
"""

from unittest.mock import patch


class TestExtractAuthorName:
    def test_from_profile_div(self, scraper, profile_html):
        assert scraper.extract_author_name_from_profile(profile_html) == "Andrej Karpathy"

    def test_fallback_to_title(self, scraper):
        html = "<html><head><title>Geoffrey Hinton - Google Scholar</title></head><body></body></html>"
        assert scraper.extract_author_name_from_profile(html) == "Geoffrey Hinton"

    def test_unknown_when_nothing(self, scraper):
        html = "<html><head><title>Some Page</title></head><body></body></html>"
        assert scraper.extract_author_name_from_profile(html) == "Unknown Author"


class TestExtractAffiliation:
    def test_from_profile(self, scraper, profile_html):
        result = scraper.extract_author_affiliation_from_profile(profile_html)
        assert result == "Stanford University"

    def test_unknown_when_missing(self, scraper):
        html = "<html><body></body></html>"
        assert scraper.extract_author_affiliation_from_profile(html) == "Unknown affiliation"


class TestExtractCitations:
    def test_from_profile(self, scraper, profile_html):
        assert scraper.extract_author_citations_from_profile(profile_html) == "190954"

    def test_na_when_missing(self, scraper):
        html = "<html><body></body></html>"
        assert scraper.extract_author_citations_from_profile(html) == "N/A"


class TestExtractResearchKeywords:
    def test_from_meta_description(self, scraper, profile_html):
        result = scraper.extract_research_keywords(profile_html)
        assert "Deep Learning" in result
        assert "Computer Vision" in result
        assert "Natural Language Processing" in result

    def test_not_available_when_no_meta(self, scraper):
        html = "<html><head></head><body></body></html>"
        assert scraper.extract_research_keywords(html) == "Research areas not available"

    def test_not_specified_when_meta_has_no_keywords(self, scraper):
        html = '<html><head><meta name="description" content="Andrej Karpathy - Stanford University"></head><body></body></html>'
        assert scraper.extract_research_keywords(html) == "Research areas not specified"


class TestExtractHomepage:
    def test_from_profile(self, scraper, profile_html):
        assert scraper.extract_homepage(profile_html) == "https://karpathy.ai"

    def test_not_specified_when_missing(self, scraper):
        html = "<html><body></body></html>"
        assert scraper.extract_homepage(html) == "Homepage not specified"

    def test_ignores_google_links(self, scraper):
        html = """<html><body>
        <div id="gsc_prf_ivh">
            <a class="gsc_prf_ila" href="https://scholar.google.com/something">Link</a>
        </div>
        </body></html>"""
        assert scraper.extract_homepage(html) == "Homepage not specified"


class TestParseAuthorProfile:
    def test_extracts_papers(self, scraper, profile_html):
        with (
            patch.object(type(scraper), "visit_paper_page", return_value=None),
            patch.object(type(scraper), "get_new_identity"),
        ):
            papers = scraper.parse_author_profile(profile_html)

        assert papers is not None
        assert len(papers) == 3

        assert papers[0]["title"] == "ImageNet large scale visual recognition challenge"
        assert papers[0]["citations"] == "52000"
        assert papers[0]["year"] == "2015"
        assert papers[0]["rank"] == 1
        assert papers[0]["url"].startswith("https://scholar.google.com/")

        assert papers[1]["title"] == "Large-scale video classification with convolutional neural networks"
        assert papers[1]["citations"] == "6800"
        assert papers[1]["year"] == "2014"

        assert papers[2]["title"] == "Visualizing and understanding recurrent networks"
        assert papers[2]["citations"] == "1600"
        assert papers[2]["year"] == "2015"

    def test_returns_none_for_empty_profile(self, scraper, empty_profile_html):
        with (
            patch.object(type(scraper), "visit_paper_page", return_value=None),
            patch.object(type(scraper), "get_new_identity"),
        ):
            papers = scraper.parse_author_profile(empty_profile_html)
        assert papers is None

    def test_descriptions_populated_when_paper_page_available(
        self, scraper, profile_html, paper_citation_html
    ):
        with patch.object(
            type(scraper), "visit_paper_page", return_value=paper_citation_html
        ):
            papers = scraper.parse_author_profile(profile_html)

        assert papers is not None
        assert "ImageNet" in papers[0]["description"]

    def test_descriptions_fallback_when_paper_page_unavailable(
        self, scraper, profile_html
    ):
        with (
            patch.object(type(scraper), "visit_paper_page", return_value=None),
            patch.object(type(scraper), "get_new_identity"),
        ):
            papers = scraper.parse_author_profile(profile_html)

        assert papers is not None
        for paper in papers:
            assert paper["description"] == "Description not available"


    def test_retry_on_failed_paper_page_fetch(
        self, scraper, profile_html, paper_citation_html
    ):
        with (
            patch.object(
                type(scraper),
                "visit_paper_page",
                side_effect=[None, paper_citation_html] * 3,
            ) as mock_visit,
            patch.object(type(scraper), "get_new_identity") as mock_identity,
        ):
            papers = scraper.parse_author_profile(profile_html)

        assert papers is not None
        for paper in papers:
            assert "Description not available" not in paper["description"]
        assert mock_identity.call_count == 3
        assert mock_visit.call_count == 6


class TestExtractPaperDescription:
    def test_extracts_description(self, scraper, paper_citation_html):
        result = scraper.extract_paper_description(paper_citation_html)
        assert "ImageNet" in result
        assert "object category" in result

    def test_not_available_when_missing(self, scraper):
        html = "<html><body><div class='gs_scl'>Authors: Someone</div></body></html>"
        assert scraper.extract_paper_description(html) == "Description not available"
