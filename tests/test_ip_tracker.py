"""Unit tests for the IP usage tracker.

No network or Tor required.
"""

import json

from scholarmine.ip_tracker import IPTracker


class TestIPTrackerCounting:
    def test_initial_count_is_zero(self, tmp_path):
        tracker = IPTracker(str(tmp_path / "tracker.json"))
        assert tracker.get_ip_usage_count("1.2.3.4") == 0

    def test_count_increments_after_log(self, tmp_path):
        tracker = IPTracker(str(tmp_path / "tracker.json"))
        tracker.log_successful_scrape("Andrej Karpathy", "1.2.3.4", thread_id=1)
        assert tracker.get_ip_usage_count("1.2.3.4") == 1

    def test_multiple_scrapes_same_ip(self, tmp_path):
        tracker = IPTracker(str(tmp_path / "tracker.json"))
        tracker.log_successful_scrape("Andrej Karpathy", "1.2.3.4", thread_id=1)
        tracker.log_successful_scrape("Geoffrey Hinton", "1.2.3.4", thread_id=2)
        tracker.log_successful_scrape("Yann LeCun", "1.2.3.4", thread_id=1)
        assert tracker.get_ip_usage_count("1.2.3.4") == 3

    def test_different_ips_tracked_separately(self, tmp_path):
        tracker = IPTracker(str(tmp_path / "tracker.json"))
        tracker.log_successful_scrape("Andrej Karpathy", "1.2.3.4", thread_id=1)
        tracker.log_successful_scrape("Geoffrey Hinton", "5.6.7.8", thread_id=2)
        assert tracker.get_ip_usage_count("1.2.3.4") == 1
        assert tracker.get_ip_usage_count("5.6.7.8") == 1

    def test_none_ip_returns_zero(self, tmp_path):
        tracker = IPTracker(str(tmp_path / "tracker.json"))
        assert tracker.get_ip_usage_count(None) == 0


class TestIPTrackerExtraction:
    def test_extract_ip_from_output(self, tmp_path):
        tracker = IPTracker(str(tmp_path / "tracker.json"))
        output = "Author: Andrej Karpathy\nTor IP: 192.168.1.100\nSaved to: /data"
        assert tracker.extract_tor_ip_from_output(output) == "192.168.1.100"

    def test_extract_ip_returns_none_for_no_ip(self, tmp_path):
        tracker = IPTracker(str(tmp_path / "tracker.json"))
        assert tracker.extract_tor_ip_from_output("No IP here") is None

    def test_extract_ip_returns_none_for_none(self, tmp_path):
        tracker = IPTracker(str(tmp_path / "tracker.json"))
        assert tracker.extract_tor_ip_from_output(None) is None


class TestIPTrackerPersistence:
    def test_save_and_reload(self, tmp_path):
        tracker_file = str(tmp_path / "tracker.json")
        tracker = IPTracker(tracker_file)
        tracker.log_successful_scrape("Andrej Karpathy", "1.2.3.4", thread_id=1)
        tracker.log_successful_scrape("Geoffrey Hinton", "1.2.3.4", thread_id=2)
        tracker.save_to_file()

        tracker2 = IPTracker(tracker_file)
        assert tracker2.get_ip_usage_count("1.2.3.4") == 2

    def test_saved_file_is_valid_json(self, tmp_path):
        tracker_file = str(tmp_path / "tracker.json")
        tracker = IPTracker(tracker_file)
        tracker.log_successful_scrape("Andrej Karpathy", "10.0.0.1", thread_id=1)
        tracker.save_to_file()

        with open(tracker_file, "r") as f:
            data = json.load(f)

        assert "ip_usage" in data
        assert "ip_details" in data
        assert data["ip_usage"]["10.0.0.1"] == 1


class TestIPTrackerStats:
    def test_usage_stats(self, tmp_path):
        tracker = IPTracker(str(tmp_path / "tracker.json"))
        tracker.log_successful_scrape("Andrej Karpathy", "1.1.1.1", thread_id=1)
        tracker.log_successful_scrape("Geoffrey Hinton", "2.2.2.2", thread_id=1)
        tracker.log_successful_scrape("Yann LeCun", "1.1.1.1", thread_id=1)

        stats = tracker.get_usage_stats()
        assert stats["total_unique_ips"] == 2
        assert stats["total_successful_scrapes"] == 3
        assert stats["most_used_ip"] == ("1.1.1.1", 2)
