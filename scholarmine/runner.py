"""CSV-based batch processing runner for Scholar scraping."""

import atexit
import csv
import json
import logging
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

from .ip_tracker import IPTracker
from .scraper import TorScholarSearch

logger = logging.getLogger(__name__)


class CSVResearcherRunner:
    """Batch processor for scraping multiple researchers from a CSV file."""

    @staticmethod
    def find_latest_log_directory() -> str | None:
        """Find the latest log directory in the logs folder.

        Returns:
            Path to the latest log directory, or None if not found.
        """
        logs_base_dir = "logs"
        if not os.path.exists(logs_base_dir):
            return None

        run_dirs = []
        for item in os.listdir(logs_base_dir):
            item_path = os.path.join(logs_base_dir, item)
            if os.path.isdir(item_path) and item.startswith("run_"):
                run_dirs.append(item_path)

        if not run_dirs:
            return None

        run_dirs.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return run_dirs[0]

    @staticmethod
    def load_progress_from_log(log_dir: str) -> dict | None:
        """Load progress data from existing log directory.

        Args:
            log_dir: Path to the log directory.

        Returns:
            Progress data dictionary, or None if not found.
        """
        progress_file = os.path.join(log_dir, "scraping_progress.json")
        if not os.path.exists(progress_file):
            return None

        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load progress from {progress_file}: {e}")
            return None

    def __init__(
        self,
        csv_file: str,
        max_threads: int = 10,
        max_requests_per_ip: int = 10,
        output_dir: str | None = None,
        continue_from_log: str | None = None,
    ):
        """Initialize the CSV researcher runner.

        Args:
            csv_file: Path to CSV file with researcher data.
            max_threads: Maximum concurrent threads. Defaults to 10.
            max_requests_per_ip: Max requests per IP before rotation. Defaults to 10.
            output_dir: Output directory for profiles. Defaults to "Researcher_Profiles".
            continue_from_log: Path to log directory to continue from.
        """
        self.csv_file = csv_file
        self.max_threads = max_threads
        self.max_requests_per_ip = max_requests_per_ip
        self.output_dir = output_dir or "Researcher_Profiles"
        self.results_lock = threading.Lock()
        self.print_lock = threading.Lock()
        self.continue_mode = continue_from_log is not None

        if continue_from_log:
            self.logs_dir = continue_from_log
            logger.info(f"Continue mode: Using existing log directory: {self.logs_dir}")
        else:
            self.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.logs_dir = os.path.join("logs", f"run_{self.session_timestamp}")
            os.makedirs(self.logs_dir, exist_ok=True)

        ip_tracker_file = os.path.join(self.logs_dir, "ip_usage_tracker.json")
        self.ip_tracker = IPTracker(ip_tracker_file)

        self.tor_process = None
        self.tor_started_by_script = False
        atexit.register(self.cleanup_tor)
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.progress_file = os.path.join(self.logs_dir, "scraping_progress.json")
        self.progress_lock = threading.Lock()

        if self.continue_mode:
            existing_progress = self.load_progress_from_log(self.logs_dir)
            if existing_progress:
                self.progress_data = existing_progress
                logger.info(
                    f"Continue mode: Loaded existing progress - "
                    f"{len(existing_progress.get('success', []))} successful, "
                    f"{len(existing_progress.get('pending', []))} pending"
                )
            else:
                logger.warning(
                    "Continue mode: Could not load existing progress, starting fresh"
                )
                self.progress_data = self._create_empty_progress_data()
        else:
            self.progress_data = self._create_empty_progress_data()

        self.researcher_queue: queue.Queue = queue.Queue()
        self.queue_lock = threading.Lock()

        if not self.start_tor_service():
            raise RuntimeError(
                "Failed to start Tor service. Please ensure Tor is installed "
                "and not already running on port 9051."
            )

    def _create_empty_progress_data(self) -> dict:
        """Create an empty progress data structure."""
        return {
            "session_start": None,
            "last_updated": None,
            "total_researchers": 0,
            "pending": [],
            "success": [],
            "failed_retrying": [],
            "counts": {
                "pending": 0,
                "success": 0,
                "failed_retrying": 0,
            },
        }

    def start_tor_service(self) -> bool:
        """Start Tor service with the required configuration.

        Returns:
            True if Tor is running, False otherwise.
        """
        try:
            if self.check_tor_running():
                logger.info("Tor is already running - skipping startup")
                return True

            logger.info(
                "Starting Tor service with control port 9051 "
                "and cookie authentication disabled..."
            )

            self.tor_process = subprocess.Popen(
                ["tor", "--controlport", "9051", "--cookieauthentication", "0"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.tor_started_by_script = True
            logger.info(f"Tor process started with PID: {self.tor_process.pid}")

            startup_timeout = 30
            for i in range(startup_timeout):
                if self.check_tor_running():
                    logger.info(f"Tor is ready after {i+1} seconds")
                    return True
                time.sleep(1)

            logger.error(f"Tor failed to start within {startup_timeout} seconds")
            self.stop_tor_service()
            return False

        except Exception as e:
            logger.error(f"Failed to start Tor service: {e}")
            if self.tor_process:
                self.stop_tor_service()
            return False

    def stop_tor_service(self) -> None:
        """Stop the Tor service if it was started by this script."""
        if self.tor_process and self.tor_started_by_script:
            try:
                logger.info("Stopping Tor service...")
                self.tor_process.terminate()

                try:
                    self.tor_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "Tor didn't stop gracefully, forcing termination..."
                    )
                    self.tor_process.kill()
                    self.tor_process.wait()

                logger.info("Tor service stopped")
                self.tor_process = None
                self.tor_started_by_script = False

            except Exception as e:
                logger.error(f"Error stopping Tor service: {e}")

    def check_tor_running(self) -> bool:
        """Check if Tor is running and accessible on the control port.

        Returns:
            True if Tor is accessible, False otherwise.
        """
        try:
            from stem.control import Controller

            with Controller.from_port(port=9051) as controller:
                controller.authenticate()
                return True
        except Exception:
            return False

    def cleanup_tor(self) -> None:
        """Cleanup method called on exit."""
        self.stop_tor_service()

    def signal_handler(self, signum: int, frame) -> None:
        """Handle interrupt signals.

        Args:
            signum: Signal number.
            frame: Current stack frame.
        """
        logger.info(f"Received signal {signum}, cleaning up...")
        self.cleanup_tor()
        sys.exit(0)

    def extract_scholar_id_from_url(self, google_scholar_url: str) -> str | None:
        """Extract Google Scholar ID from the URL.

        Args:
            google_scholar_url: Full Google Scholar profile URL.

        Returns:
            Scholar ID or None if not found.
        """
        if not google_scholar_url or "citations?user=" not in google_scholar_url:
            return None

        try:
            match = re.search(r"user=([^&]+)", google_scholar_url)
            if match:
                return match.group(1)
        except Exception as e:
            logger.warning(
                f"Failed to extract Scholar ID from URL {google_scholar_url}: {e}"
            )

        return None

    def read_csv_file(self) -> dict[str, str]:
        """Read researchers from CSV file and extract Scholar IDs.

        Returns:
            Dictionary mapping researcher names to Scholar IDs.
        """
        try:
            researchers_data = {}
            with open(self.csv_file, "r", encoding="utf-8") as f:
                csv_reader = csv.DictReader(f)

                for row in csv_reader:
                    name = row.get("name", "").strip()
                    google_scholar_url = row.get("google_scholar_url", "").strip()

                    if not name or not google_scholar_url:
                        continue

                    scholar_id = self.extract_scholar_id_from_url(google_scholar_url)
                    if scholar_id:
                        researchers_data[name] = scholar_id
                    else:
                        logger.warning(
                            f"Could not extract Scholar ID from URL for {name}: "
                            f"{google_scholar_url}"
                        )

            logger.info(
                f"Read {len(researchers_data)} researchers with valid Scholar IDs "
                f"from {self.csv_file}"
            )
            return researchers_data

        except FileNotFoundError:
            logger.error(f"CSV file not found: {self.csv_file}")
            return {}
        except Exception as e:
            logger.error(f"Error reading CSV file {self.csv_file}: {e}")
            return {}

    def initialize_progress_tracking(self, researchers: list[str]) -> None:
        """Initialize progress tracking with all researchers as pending.

        Args:
            researchers: List of researcher names.
        """
        with self.progress_lock:
            self.progress_data["session_start"] = datetime.now().isoformat()
            self.progress_data["last_updated"] = datetime.now().isoformat()
            self.progress_data["total_researchers"] = len(researchers)
            self.progress_data["pending"] = list(researchers)
            self.progress_data["success"] = []
            self.progress_data["failed_retrying"] = []
            self.progress_data["failed_exhausted"] = []
            self.progress_data["counts"] = {
                "pending": len(researchers),
                "success": 0,
                "failed_retrying": 0,
                "failed_exhausted": 0,
            }
            self._write_progress_file()

    def update_researcher_status(self, researcher_name: str, new_status: str) -> None:
        """Update a researcher's status and write to file immediately.

        Args:
            researcher_name: Name of the researcher.
            new_status: New status ('success', 'failed_retrying', 'failed_exhausted', 'pending').
        """
        with self.progress_lock:
            for status_list in [
                "pending",
                "success",
                "failed_retrying",
                "failed_exhausted",
            ]:
                if researcher_name in self.progress_data.get(status_list, []):
                    self.progress_data[status_list].remove(researcher_name)

            if new_status == "success":
                self.progress_data["success"].append(researcher_name)
            elif new_status == "failed_retrying":
                self.progress_data["failed_retrying"].append(researcher_name)
            elif new_status == "failed_exhausted":
                self.progress_data.setdefault("failed_exhausted", []).append(
                    researcher_name
                )
            elif new_status == "pending":
                self.progress_data["pending"].append(researcher_name)

            self.progress_data["counts"] = {
                "pending": len(self.progress_data.get("pending", [])),
                "success": len(self.progress_data.get("success", [])),
                "failed_retrying": len(self.progress_data.get("failed_retrying", [])),
                "failed_exhausted": len(self.progress_data.get("failed_exhausted", [])),
            }

            self.progress_data["last_updated"] = datetime.now().isoformat()
            self._write_progress_file()

    def _write_progress_file(self) -> None:
        """Write progress data to file (called with lock already held)."""
        try:
            with open(self.progress_file, "w", encoding="utf-8") as f:
                json.dump(self.progress_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write progress file: {e}")

    def print_current_progress(self) -> None:
        """Print current progress status."""
        with self.progress_lock:
            counts = self.progress_data["counts"]
            total = self.progress_data["total_researchers"]
            queue_size = self.researcher_queue.qsize()

            print(f"\n CURRENT PROGRESS:")
            print(f"   Total researchers: {total}")
            print(f"   Successfully scraped: {counts['success']}")
            print(f"   In queue (pending/retrying): {queue_size}")
            print(f"   Currently retrying: {counts['failed_retrying']}")
            print(f"   Success rate: {(counts['success'] / total * 100):.1f}%")
            print(f"   Last updated: {self.progress_data['last_updated']}")

            if queue_size == 0 and counts["failed_retrying"] == 0:
                print("   All researchers completed successfully!")

    def _run_single_researcher_scrape_by_scholar_id(
        self,
        researcher_name: str,
        scholar_id: str,
        thread_id: int | None = None,
    ) -> dict:
        """Run the scraper for a single researcher using Scholar ID with IP limit checking.

        Args:
            researcher_name: Name of the researcher.
            scholar_id: Google Scholar ID.
            thread_id: Thread identifier for logging.

        Returns:
            Dictionary with scrape results.
        """
        thread_info = f"[Thread-{thread_id}]" if thread_id else ""

        ip_retry_attempt = 0
        while True:
            try:
                with self.print_lock:
                    if ip_retry_attempt == 0:
                        logger.info(
                            f"{thread_info} Starting Scholar ID scrape for: "
                            f"{researcher_name} (ID: {scholar_id})"
                        )
                    else:
                        logger.info(
                            f"{thread_info} IP retry #{ip_retry_attempt} for: "
                            f"{researcher_name} (forcing new IP)"
                        )

                searcher = TorScholarSearch(self.output_dir)

                with self.print_lock:
                    logger.info(
                        f"{thread_info} Requesting new Tor identity for fresh IP..."
                    )

                if thread_id:
                    stagger_delay = (thread_id - 1) * 2
                    if stagger_delay > 0:
                        with self.print_lock:
                            logger.info(
                                f"{thread_info} Waiting {stagger_delay}s for "
                                "staggered identity request..."
                            )
                        time.sleep(stagger_delay)

                searcher.get_new_identity()

                current_ip = searcher.get_current_ip()

                if current_ip and current_ip != "Errored IP":
                    current_usage = self.ip_tracker.get_ip_usage_count(current_ip)

                    if current_usage >= self.max_requests_per_ip:
                        with self.print_lock:
                            logger.warning(
                                f"{thread_info} IP {current_ip} has reached/exceeded "
                                f"limit ({current_usage}/{self.max_requests_per_ip})"
                            )
                            logger.info(
                                f"{thread_info} Retrying with new IP to avoid "
                                "over-limit usage"
                            )
                        ip_retry_attempt += 1
                        continue

                scrape_result = searcher.scrape_researcher_by_scholar_id(
                    scholar_id, researcher_name
                )

                if scrape_result and scrape_result.get("success"):
                    result = {
                        "success": True,
                        "stdout": (
                            f"Author: {scrape_result['author_name']}\n"
                            f"Affiliation: {scrape_result['affiliation']}\n"
                            f"Citations: {scrape_result['citations']}\n"
                            f"Papers: {scrape_result['papers_count']}\n"
                            f"Tor IP: {scrape_result['tor_ip']}\n"
                            f"Saved to: {scrape_result['folder_path']}"
                        ),
                        "stderr": "",
                        "researcher": researcher_name,
                        "thread_id": thread_id,
                        "ip_retry_attempt": ip_retry_attempt,
                        "scholar_id": scholar_id,
                    }

                    return result
                else:
                    error_msg = (
                        scrape_result.get("error", "Unknown error")
                        if scrape_result
                        else "Failed to get result"
                    )
                    return {
                        "success": False,
                        "error": error_msg,
                        "stderr": error_msg,
                        "researcher": researcher_name,
                        "thread_id": thread_id,
                        "ip_retry_attempt": ip_retry_attempt,
                        "scholar_id": scholar_id,
                    }

            except Exception as e:
                with self.print_lock:
                    logger.error(
                        f"{thread_info} Error scraping Scholar ID {scholar_id} "
                        f"for {researcher_name}: {e}"
                    )
                return {
                    "success": False,
                    "error": str(e),
                    "stderr": str(e),
                    "researcher": researcher_name,
                    "thread_id": thread_id,
                    "ip_retry_attempt": ip_retry_attempt,
                    "scholar_id": scholar_id,
                }

    def _queue_worker_thread(
        self,
        thread_id: int,
        results: dict,
        successful_researchers: set,
    ) -> None:
        """Continuous worker thread that processes researchers from the queue.

        Args:
            thread_id: Thread identifier.
            results: Shared results dictionary.
            successful_researchers: Set of successfully processed researchers.
        """
        while True:
            try:
                try:
                    researcher_name, scholar_id = self.researcher_queue.get(timeout=5.0)
                except queue.Empty:
                    with self.queue_lock:
                        if self.researcher_queue.empty():
                            with self.print_lock:
                                print(
                                    f"[Thread-{thread_id}] No more researchers "
                                    "in queue, thread exiting"
                                )
                            break
                        else:
                            continue

                with self.results_lock:
                    if researcher_name not in results:
                        results[researcher_name] = []

                attempt_num = 0

                while researcher_name not in successful_researchers:
                    attempt_num += 1

                    with self.print_lock:
                        print(
                            f"\n[Thread-{thread_id}] Starting: {researcher_name} "
                            f"(Scholar ID: {scholar_id}) (Attempt #{attempt_num})"
                        )
                        if attempt_num > 1:
                            print(
                                f"[Thread-{thread_id}] Retrying after failure - "
                                "requesting fresh IP and waiting 20s"
                            )

                    if attempt_num > 1:
                        try:
                            searcher = TorScholarSearch(self.output_dir)
                            searcher.get_new_identity()

                            with self.print_lock:
                                new_ip = searcher.get_current_ip()
                                print(f"[Thread-{thread_id}] Got new Tor IP: {new_ip}")
                                print(
                                    f"[Thread-{thread_id}] Waiting 20 seconds "
                                    "before retry..."
                                )

                            time.sleep(20)

                        except Exception as e:
                            with self.print_lock:
                                logger.warning(
                                    f"[Thread-{thread_id}] Failed to get new IP "
                                    f"for retry: {e}"
                                )
                            time.sleep(20)

                    start_time = time.time()
                    result = self._run_single_researcher_scrape_by_scholar_id(
                        researcher_name, scholar_id, thread_id=thread_id
                    )
                    end_time = time.time()

                    result["duration"] = round(end_time - start_time, 2)
                    result["attempt"] = attempt_num
                    result["timestamp"] = datetime.now().isoformat()
                    result["scholar_id"] = scholar_id

                    with self.results_lock:
                        results[researcher_name].append(result)

                    if result["success"]:
                        with self.results_lock:
                            successful_researchers.add(researcher_name)

                        self.update_researcher_status(researcher_name, "success")

                        ip_address = self.ip_tracker.extract_tor_ip_from_output(
                            result.get("stdout", "")
                        )
                        if ip_address:
                            self.ip_tracker.log_successful_scrape(
                                researcher_name, ip_address, thread_id
                            )

                        with self.print_lock:
                            print(
                                f"[Thread-{thread_id}] SUCCESS: {researcher_name} "
                                f"({result['duration']}s) (Attempt #{attempt_num})"
                            )
                            if result.get("stdout"):
                                lines = result["stdout"].strip().split("\n")
                                for line in lines:
                                    if any(
                                        keyword in line
                                        for keyword in [
                                            "Author:",
                                            "Affiliation:",
                                            "Citations:",
                                            "Papers:",
                                            "Tor IP:",
                                            "Saved to:",
                                        ]
                                    ):
                                        print(f"   {line}")
                        break

                    else:
                        with self.print_lock:
                            print(
                                f"[Thread-{thread_id}] FAILED: {researcher_name} "
                                f"({result['duration']}s) (Attempt #{attempt_num})"
                            )
                            error_info = result.get("error", "Unknown error")
                            if result.get("stderr"):
                                error_info = result["stderr"]
                            print(f"   Error: {error_info}")
                            print(
                                f"[Thread-{thread_id}] Will retry with fresh IP "
                                "after 20s wait..."
                            )

                        self.update_researcher_status(researcher_name, "failed_retrying")

                self.researcher_queue.task_done()

            except Exception as e:
                with self.print_lock:
                    logger.error(f"[Thread-{thread_id}] Unexpected error: {e}")
                try:
                    self.researcher_queue.task_done()
                except Exception:
                    pass
                continue

    def _process_researchers_with_queue(
        self,
        researchers_data: dict[str, str],
        results: dict,
        successful_researchers: set,
    ) -> None:
        """Process researchers using continuous queue-based approach.

        Args:
            researchers_data: Dictionary mapping names to Scholar IDs.
            results: Shared results dictionary.
            successful_researchers: Set of successfully processed researchers.
        """
        print(
            f"\nQUEUE-BASED PROCESSING: Starting {len(researchers_data)} researchers "
            f"with Scholar IDs using {self.max_threads} continuous threads"
        )
        print("Each thread will get a fresh Tor IP for every researcher scrape attempt")
        print(
            "Failed researchers will be immediately retried with fresh IP "
            "and 20s wait until successful"
        )
        print("=" * 60)

        with self.queue_lock:
            for researcher_name, scholar_id in researchers_data.items():
                self.researcher_queue.put((researcher_name, scholar_id))

        threads = []
        for thread_id in range(1, self.max_threads + 1):
            thread = threading.Thread(
                target=self._queue_worker_thread,
                args=(thread_id, results, successful_researchers),
                daemon=True,
            )
            thread.start()
            threads.append(thread)
            print(f"Started worker thread {thread_id}")

        last_progress_time = time.time()
        while True:
            time.sleep(10)

            current_time = time.time()
            if current_time - last_progress_time >= 30:
                self.print_current_progress()
                last_progress_time = current_time

            with self.results_lock:
                if len(successful_researchers) == len(researchers_data):
                    print(
                        f"\nAll {len(researchers_data)} researchers have been "
                        "successfully processed!"
                    )
                    break

            alive_threads = [t for t in threads if t.is_alive()]
            if not alive_threads:
                print("\nAll worker threads have finished")
                break

        print("\nWaiting for worker threads to finish...")
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=30)

        try:
            while not self.researcher_queue.empty():
                self.researcher_queue.get_nowait()
                self.researcher_queue.task_done()
        except queue.Empty:
            pass

        with self.print_lock:
            print("\nQueue processing completed!")
            self.ip_tracker.save_to_file()

    def process_researchers_from_csv(self) -> dict:
        """Process researchers from CSV file using continuous queue-based approach.

        Returns:
            Dictionary of results by researcher name.
        """
        researchers_data = self.read_csv_file()
        if not researchers_data:
            print("No valid researchers with Scholar IDs found in CSV file!")
            return {}

        if self.continue_mode:
            successful_researchers_from_log = set(
                self.progress_data.get("success", [])
            )
            original_count = len(researchers_data)
            researchers_data = {
                name: scholar_id
                for name, scholar_id in researchers_data.items()
                if name not in successful_researchers_from_log
            }

            print(f"\n{'='*80}")
            print("CSV RESEARCHER SCRAPING SESSION (CONTINUE MODE)")
            print(f"Continuing from: {self.logs_dir}")
            print(f"Original researchers in CSV: {original_count}")
            print(f"Already successful: {len(successful_researchers_from_log)}")
            print(f"Remaining to process: {len(researchers_data)}")

            if not researchers_data:
                print("All researchers have already been successfully processed!")
                return self.progress_data
        else:
            print(f"\n{'='*80}")
            print("CSV RESEARCHER SCRAPING SESSION (QUEUE-BASED CONTINUOUS RETRY)")

        print(f"Starting at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"CSV file: {self.csv_file}")
        print(f"Processing {len(researchers_data)} researchers with Scholar IDs")
        print(f"Max threads: {self.max_threads}")
        print(
            "Failed researchers will be immediately retried with fresh IP "
            "and 20s wait until successful"
        )
        print(f"IP request limit: {self.max_requests_per_ip} per IP address")
        print(f"Session logs directory: {self.logs_dir}")
        print("=" * 80)

        if not self.continue_mode:
            researcher_names = list(researchers_data.keys())
            self.initialize_progress_tracking(researcher_names)

        results: dict = {}
        successful_researchers: set = set()

        if self.continue_mode:
            successful_researchers.update(self.progress_data.get("success", []))

        self._process_researchers_with_queue(
            researchers_data, results, successful_researchers
        )

        print(f"\n{'='*80}")
        print("CSV SESSION COMPLETED - FINAL PROGRESS")
        print("=" * 80)
        self.print_current_progress()

        self._print_final_summary(results, successful_researchers)
        self.ip_tracker.print_usage_summary()

        return results

    def _print_final_summary(
        self,
        results: dict,
        successful_researchers: set,
    ) -> None:
        """Print final session summary.

        Args:
            results: Dictionary of results by researcher name.
            successful_researchers: Set of successfully processed researchers.
        """
        total_researchers = len(results)
        successful_count = len(successful_researchers)
        success_rate = 100.0
        total_attempts = sum(len(attempts) for attempts in results.values())

        print(f"\n{'='*80}")
        print("FINAL SESSION SUMMARY")
        print("=" * 80)
        print(f"Total researchers: {total_researchers}")
        print(f"Successful extractions: {successful_count}")
        print(f"Success rate: {success_rate:.1f}% (All researchers completed successfully)")
        print(f"Total attempts made: {total_attempts}")
        print(
            "Immediate retry approach: Failed researchers immediately retried "
            "with fresh IP and 20s wait until successful"
        )

        if successful_count > 0:
            output_folder = getattr(self, "output_dir", "Researcher_Profiles")
            print(f"\nData saved to '{output_folder}' folder")
            print("Each researcher has their own subfolder containing:")
            print("  - profile.json (researcher metadata + Tor IP)")
            print("  - papers.csv (top 50 paper details with descriptions)")

        print("\nATTEMPT STATISTICS:")
        researchers_by_attempts: dict = {}
        for name, attempts in results.items():
            attempt_count = len(attempts)
            if attempt_count not in researchers_by_attempts:
                researchers_by_attempts[attempt_count] = []
            researchers_by_attempts[attempt_count].append(name)

        for attempt_count in sorted(researchers_by_attempts.keys()):
            researchers_list = researchers_by_attempts[attempt_count]
            print(f"  {attempt_count} attempt(s): {len(researchers_list)} researchers")

        retry_successes = []
        for name in successful_researchers:
            if name in results and len(results[name]) > 1:
                retry_successes.append((name, len(results[name])))

        if retry_successes:
            print("\nRESEARCHERS THAT SUCCEEDED AFTER MULTIPLE ATTEMPTS:")
            retry_successes.sort(key=lambda x: x[1], reverse=True)
            for name, attempt_count in retry_successes:
                print(f"  - {name} (succeeded on attempt #{attempt_count})")

        first_try_successes = len(researchers_by_attempts.get(1, []))
        if first_try_successes > 0:
            print(f"\n{first_try_successes} researchers succeeded on first attempt")
            print(
                f"{total_researchers - first_try_successes} researchers required retries"
            )
