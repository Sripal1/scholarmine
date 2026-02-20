# Tests

Unit tests run instantly with no external dependencies. Integration tests hit real Google Scholar through Tor (auto-started if not already running).

## Running tests

```bash
# Unit tests only (no Tor needed)
python -m pytest tests/ -v --ignore=tests/test_integration.py

# Integration tests (Tor is auto-started if not already running)
python -m pytest -m integration --sample-size 5   # quick spot check
python -m pytest -m integration                    # all 176 GT researchers
```

## Test files

| File | What it tests | Needs Tor? |
|------|--------------|------------|
| `test_scraper_parsing.py` | HTML parsing — name, affiliation, citations, keywords, homepage, paper list, and description extraction against saved fixture HTML | No |
| `test_runner_utils.py` | Scholar ID extraction from URLs, CSV reading/validation, bulk URL validation against all 176 fixture URLs | No |
| `test_ip_tracker.py` | IP usage counting, Tor IP extraction from stdout, JSON persistence, usage stats | No |
| `test_integration.py` | Live Tor connectivity, profile scraping, DOM structure checks, full CSV-to-output pipeline | Auto-started |

## Fixtures

HTML fixtures live in `tests/fixtures/`. Shared pytest fixtures are in `conftest.py`.

| Fixture | Description |
|---------|-------------|
| `profile_html` | Andrej Karpathy's Scholar profile with 3 papers |
| `empty_profile_html` | Fei-Fei Li profile with empty papers table |
| `paper_citation_html` | ImageNet ILSVRC citation detail page |
| `test_scholar_urls` | 176 GT CS faculty Scholar URLs from the ai-map dataset |
| `scraper` / `runner` | Instances created without `__init__` — no Tor needed, just the methods under test |

## Options

Pass `--sample-size N` to randomly sample N researchers for integration tests instead of running all 176.

## Notes

- Tor is automatically started by the `ensure_tor` session fixture if not already running, and stopped after the test session. You only need Tor **installed** (e.g. `brew install tor`).
- Integration tests are slow and can fail if Google rate-limits the Tor exit node. Use `--sample-size 3` for a quick sanity check.
- The `scraper` and `runner` fixtures bypass `__init__` to avoid needing Tor. If your new method depends on init state, set it manually in the test.
