"""IP usage tracking for Tor-based scraping."""

import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


class IPTracker:
    """IP Usage Tracker for Tor Researcher Scraper."""

    def __init__(self, tracker_file: str = "ip_usage_tracker.json"):
        self.tracker_file = tracker_file
        self.ip_usage: dict[str, int] = defaultdict(int)
        self.ip_details: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.load_existing_data()

    def load_existing_data(self) -> None:
        """Load existing IP usage data from file."""
        if os.path.exists(self.tracker_file):
            try:
                with open(self.tracker_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.ip_usage = defaultdict(int, data.get("ip_usage", {}))
                    self.ip_details = data.get("ip_details", {})
                logger.info(
                    f"Loaded existing IP tracker data: {len(self.ip_usage)} unique IPs"
                )
            except Exception as e:
                logger.error(f"Error loading IP tracker data: {e}")
                self.ip_usage = defaultdict(int)
                self.ip_details = {}

    def extract_tor_ip_from_output(self, stdout_output: str | None) -> str | None:
        """Extract Tor IP address from scraper output."""
        if not stdout_output:
            return None

        lines = stdout_output.strip().split("\n")
        for line in lines:
            if "Tor IP:" in line:
                ip_part = line.split("Tor IP:")[1].strip()
                ip = ip_part.split()[0] if ip_part else None
                return ip

        return None

    def log_successful_scrape(
        self,
        researcher_name: str,
        ip_address: str,
        thread_id: int | None = None,
    ) -> None:
        """Log a successful scrape with IP address."""
        if not ip_address:
            logger.warning(
                f"No IP address provided for successful scrape of {researcher_name}"
            )
            return

        with self.lock:
            self.ip_usage[ip_address] += 1

            if ip_address not in self.ip_details:
                self.ip_details[ip_address] = {
                    "first_used": datetime.now().isoformat(),
                    "usage_history": [],
                }

            self.ip_details[ip_address]["usage_history"].append(
                {
                    "researcher": researcher_name,
                    "timestamp": datetime.now().isoformat(),
                    "thread_id": thread_id,
                }
            )

            self.ip_details[ip_address]["last_used"] = datetime.now().isoformat()
            self.ip_details[ip_address]["total_usage"] = self.ip_usage[ip_address]

        logger.info(
            f"IP {ip_address} used for {researcher_name} "
            f"(total uses: {self.ip_usage[ip_address]})"
        )

    def save_to_file(self) -> None:
        """Save current IP usage data to file."""
        data = {
            "last_updated": datetime.now().isoformat(),
            "total_unique_ips": len(self.ip_usage),
            "total_successful_scrapes": sum(self.ip_usage.values()),
            "ip_usage": dict(self.ip_usage),
            "ip_details": self.ip_details,
        }

        try:
            with self.lock:
                with open(self.tracker_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"IP tracker data saved to {self.tracker_file}")
        except Exception as e:
            logger.error(f"Error saving IP tracker data: {e}")

    def get_usage_stats(self) -> dict:
        """Get IP usage statistics."""
        with self.lock:
            stats = {
                "total_unique_ips": len(self.ip_usage),
                "total_successful_scrapes": sum(self.ip_usage.values()),
                "most_used_ip": (
                    max(self.ip_usage.items(), key=lambda x: x[1])
                    if self.ip_usage
                    else None
                ),
                "ip_usage_distribution": dict(self.ip_usage),
            }
        return stats

    def print_usage_summary(self) -> None:
        """Print a summary of IP usage."""
        stats = self.get_usage_stats()

        print(f"\n{'='*60}")
        print("IP USAGE STATISTICS")
        print("=" * 60)
        print(f"Total unique Tor IPs used: {stats['total_unique_ips']}")
        print(f"Total successful scrapes: {stats['total_successful_scrapes']}")

        if stats["most_used_ip"]:
            ip, count = stats["most_used_ip"]
            print(f"Most used IP: {ip} ({count} times)")

        if stats["total_unique_ips"] > 0:
            avg_usage = stats["total_successful_scrapes"] / stats["total_unique_ips"]
            print(f"Average uses per IP: {avg_usage:.1f}")

        print(f"\nIP USAGE BREAKDOWN:")

        sorted_ips = sorted(self.ip_usage.items(), key=lambda x: x[1], reverse=True)

        for ip, count in sorted_ips[:10]:
            print(f"  {ip}: {count}")

        if len(sorted_ips) > 10:
            print(f"  ... and {len(sorted_ips) - 10} more IPs")

        print(f"\nIP tracking data saved in: {self.tracker_file}")

    def get_ip_usage_count(self, ip_address: str | None) -> int:
        """Get the current usage count for an IP address."""
        if not ip_address:
            return 0
        with self.lock:
            return self.ip_usage.get(ip_address, 0)
