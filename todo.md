# ScholarMine TODO

## Bugs

- [x] **Infinite retry loop** — Added `--max-retries N` CLI flag (default 5) and `self.max_retries` in `CSVResearcherRunner`. After N failed attempts, the worker marks the researcher as `failed_exhausted` and moves on. Final summary now computes actual success rate instead of hardcoding 100%.
- [x] **Zero test coverage** — Added 45 unit tests and 5 integration tests. **Needs further review**: integration tests untested against live Tor, edge cases in parsing may need more fixtures, and coverage metrics not yet measured.
- [x] **No HTTP status handling** — On review, `raise_for_status()` is already called after every request in `scraper.py` (lines 97, 103, 121). 4xx/5xx errors raise `RequestException`, the method returns `None`, and the runner retries with a new IP. The remaining gap (CAPTCHA pages that return 200 OK) is tracked under "CAPTCHA/block detection" in Nice to Have.
- [x] **No CSV validation** — Added upfront `fieldnames` check in `read_csv_file()` (`runner.py:240`); logs an error with the missing column names and returns `{}` immediately instead of silently skipping rows.
- [x] **Hardcoded Tor config** — Values are now named constants (`TOR_SOCKS_PROXY`, `TOR_CONTROL_PORT`, `IP_CHECK_URL`). Runtime configurability via CLI flags is tracked under "Configurable Tor settings" in Nice to Have.
- [x] **Magic numbers** — Extracted all raw values into named constants at the top of `scraper.py` and `runner.py` (e.g. `TOR_IDENTITY_WAIT_SECONDS`, `RETRY_WAIT_SECONDS`, `DEFAULT_PAGE_SIZE`). All usages replaced.
- [x] **Ambiguous `author_url` field** — Removed `author_url` from `profile_data` in `scraper.py`; it was a duplicate of `profile_url`. The researcher's personal site is already captured separately as `homepage`.
- [x] **No structured logging** — Added `_setup_file_logging()` in `CSVResearcherRunner.__init__` (`runner.py:136`) that attaches a `FileHandler` writing to `logs/run_<timestamp>/scholarmine.log`. Replaced all ~60 `print()` calls in `runner.py` with `logger.info/warning/error` calls.
- [x] **No rate limit backoff** — Added `time.sleep(min(2 ** ip_retry_attempt, 60))` after incrementing `ip_retry_attempt` in `_run_single_researcher_scrape_by_scholar_id` (`runner.py:358`); caps at 60s.
- [x] **`frame` param untyped** — `signal_handler(signum, frame)` in `runner.py:242` — fixed, now typed as `types.FrameType | None`.
- [x] **Incomplete version pinning** — Pinned all four runtime deps to exact versions in `pyproject.toml`: `requests==2.32.3`, `beautifulsoup4==4.13.3`, `stem==1.8.2`, `PySocks==1.7.1`.

---

## Action Items for Unification

- [ ] **`--max-papers N` flag** — Currently hardcoded to 50 (`DEFAULT_PAGE_SIZE`). Add a CLI flag so `researchmap.config.yaml` can control how many papers are scraped per researcher. Updates `pagesize` URL param and slicing logic in `scraper.py`.
- [ ] **`--dry-run` mode** — Parse the CSV, validate Scholar IDs, and report errors without scraping. Useful for the web form to pre-validate before kicking off a multi-hour GitHub Actions run.
- [ ] **`--tor-socks-port` / `--tor-control-port` flags** — GitHub Actions parallel jobs may run multiple Tor instances on different ports. Currently hardcoded as constants in `scraper.py` and `runner.py`.

---

## Nice to Have

- [ ] **CAPTCHA/block detection** — Detect Google's "unusual traffic" page and trigger identity rotation + longer backoff. MIGHT NOT NEED THIS SINCE HAVENT ENCOUNTERED CAPTCHA DETECTIONS.
- [ ] **Configurable Tor settings** — Support `--tor-socks-port`, `--tor-control-port`, `--ip-check-url` via CLI or config file.
- [ ] **More output formats** — SQLite or JSON Lines output alongside CSV for easier querying of large datasets.
- [ ] **Dashboard/progress UI** — `rich` or `tqdm`-based terminal progress bars instead of raw print statements.
- [ ] **Scholar ID validation** — Pre-validate Scholar IDs before queuing to fail fast on malformed URLs.
- [ ] **`--dry-run` mode** — Parse the CSV and validate IDs without scraping, useful for large batches.
- [ ] **Top recent publications scraping** — Add a `--sort-by recent` mode (using `sortby=pubdate` in the Scholar URL) to scrape the most recently published papers instead of most cited. Output saved alongside or instead of the default cited-sorted results.
- [ ] **Configurable paper count** — Add `--max-papers N` CLI flag (default: 50) to control how many papers are scraped per researcher. Should update the `pagesize` URL parameter and the slicing logic accordingly.
- [ ] **Scholarly features** - Add the cli commands and functionality that scholarly offers
- [x] **Run tor and scholarmine in the same terminal** — Already implemented in `CSVResearcherRunner.start_tor_service()` (`runner.py:183`). Tor is auto-started if not already running and cleaned up on exit via `atexit` and signal handlers.
- [x] **Sometimes the description of a single paper in the scraped data of a paper is in multiple lines, it should be wrapped into one line** — Added `" ".join(description.split())` in `extract_paper_description` (`scraper.py:151`) to collapse all whitespace (newlines, tabs, multiple spaces) into single spaces.
