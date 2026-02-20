"""Unit tests for runner utility functions.

Tests CSV validation, Scholar ID extraction, and progress tracking.
No network or Tor required.
"""


class TestExtractScholarId:
    def test_valid_url(self, runner):
        url = "https://scholar.google.com/citations?user=zh8E4voAAAAJ&hl=en"
        assert runner.extract_scholar_id_from_url(url) == "zh8E4voAAAAJ"

    def test_url_with_extra_params(self, runner):
        url = "https://scholar.google.com/citations?user=rWah5GsAAAAJ&hl=en&oi=ao"
        assert runner.extract_scholar_id_from_url(url) == "rWah5GsAAAAJ"

    def test_empty_string(self, runner):
        assert runner.extract_scholar_id_from_url("") is None

    def test_none(self, runner):
        assert runner.extract_scholar_id_from_url(None) is None

    def test_no_user_param(self, runner):
        assert runner.extract_scholar_id_from_url("https://scholar.google.com/") is None

    def test_random_url(self, runner):
        assert runner.extract_scholar_id_from_url("https://example.com") is None

    def test_special_chars_in_id(self, runner):
        url = "https://scholar.google.com/citations?user=-ZqZyP0AAAAJ&hl=en"
        assert runner.extract_scholar_id_from_url(url) == "-ZqZyP0AAAAJ"

    def test_underscore_in_id(self, runner):
        url = "https://scholar.google.com/citations?user=_cAwG4gAAAAJ&hl=en"
        assert runner.extract_scholar_id_from_url(url) == "_cAwG4gAAAAJ"


class TestExtractScholarIdFromUrlFile:
    """Validate that every URL in the test fixture file is parseable."""

    def test_all_urls_have_valid_ids(self, runner, test_scholar_urls):
        assert len(test_scholar_urls) > 0, "URL fixture file is empty"

        for url in test_scholar_urls:
            scholar_id = runner.extract_scholar_id_from_url(url)
            assert scholar_id is not None, f"Failed to extract ID from: {url}"
            assert len(scholar_id) >= 5, f"ID too short for: {url} (got {scholar_id})"


class TestReadCsvFile:
    def test_valid_csv(self, runner, tmp_path):
        csv_file = tmp_path / "researchers.csv"
        csv_file.write_text(
            "name,google_scholar_url\n"
            "Andrej Karpathy,https://scholar.google.com/citations?user=l8WNaJMAAAAJ&hl=en\n"
            "Geoffrey Hinton,https://scholar.google.com/citations?user=JicYPdAAAAAJ&hl=en\n"
        )
        runner.csv_file = str(csv_file)
        result = runner.read_csv_file()

        assert result == {"Andrej Karpathy": "l8WNaJMAAAAJ", "Geoffrey Hinton": "JicYPdAAAAAJ"}

    def test_missing_name_column(self, runner, tmp_path):
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text("full_name,google_scholar_url\nJane,http://example.com\n")
        runner.csv_file = str(csv_file)
        result = runner.read_csv_file()

        assert result == {}

    def test_missing_url_column(self, runner, tmp_path):
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text("name,website\nJane,http://example.com\n")
        runner.csv_file = str(csv_file)
        result = runner.read_csv_file()

        assert result == {}

    def test_file_not_found(self, runner):
        runner.csv_file = "/nonexistent/path/researchers.csv"
        result = runner.read_csv_file()

        assert result == {}

    def test_skips_rows_with_empty_name(self, runner, tmp_path):
        csv_file = tmp_path / "researchers.csv"
        csv_file.write_text(
            "name,google_scholar_url\n"
            ",https://scholar.google.com/citations?user=l8WNaJMAAAAJ&hl=en\n"
            "Andrej Karpathy,https://scholar.google.com/citations?user=WLN3QrAAAAAJ&hl=en\n"
        )
        runner.csv_file = str(csv_file)
        result = runner.read_csv_file()

        assert result == {"Andrej Karpathy": "WLN3QrAAAAAJ"}

    def test_skips_rows_with_bad_url(self, runner, tmp_path):
        csv_file = tmp_path / "researchers.csv"
        csv_file.write_text(
            "name,google_scholar_url\n"
            "Andrej Karpathy,https://example.com/not-scholar\n"
            "Geoffrey Hinton,https://scholar.google.com/citations?user=JicYPdAAAAAJ&hl=en\n"
        )
        runner.csv_file = str(csv_file)
        result = runner.read_csv_file()

        assert result == {"Geoffrey Hinton": "JicYPdAAAAAJ"}
