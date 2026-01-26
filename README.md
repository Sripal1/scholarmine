# ScholarMine

A Python package for scraping Google Scholar profiles and publications using Tor for anonymization and IP rotation.

## Features

- Scrape researcher profiles from Google Scholar using their Scholar ID
- Extract top 50 cited papers with titles, citations, years, and descriptions
- Automatic Tor IP rotation to avoid rate limiting
- Multi-threaded batch processing from CSV files
- Automatic retry with fresh IPs on failure
- Progress tracking with resumable sessions
- IP usage statistics and logging

## Prerequisites

### Install Tor

**macOS (Homebrew):**
```bash
brew install tor
```

**Ubuntu/Debian:**
```bash
sudo apt install tor
```

**Windows:**
Download from [Tor Project](https://www.torproject.org/download/)

## Installation

### From source

```bash
git clone https://github.com/yourusername/scholarmine.git
cd scholarmine
pip install -e .
```

### Using pip (coming soon)

```bash
pip install scholarmine
```

## Usage

### Command Line Interface

Basic usage with a CSV file:
```bash
scholarmine researchers.csv
```

With options:
```bash
scholarmine researchers.csv --max-threads 5 --max-requests-per-ip 6 --output-dir ./output
```

Continue from a previous session:
```bash
scholarmine researchers.csv --continue
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `csv_file` | required | Path to CSV file with researcher data |
| `--max-threads` | 10 | Maximum concurrent scraping threads |
| `--max-requests-per-ip` | 10 | Max requests per Tor IP before rotation |
| `--output-dir` | Researcher_Profiles | Output directory for scraped data |
| `--continue` | false | Resume from latest incomplete session |

### CSV File Format

Your CSV file should have the following columns:

```csv
name,google_scholar_url
John Doe,https://scholar.google.com/citations?user=SCHOLAR_ID&hl=en
Jane Smith,https://scholar.google.com/citations?user=ANOTHER_ID&hl=en
```

### Python API

```python
from scholarmine import TorScholarSearch, CSVResearcherRunner

# Single researcher scrape
scraper = TorScholarSearch(output_dir="./output")
result = scraper.scrape_researcher_by_scholar_id("SCHOLAR_ID", "Researcher Name")
print(result)

# Batch processing from CSV
runner = CSVResearcherRunner(
    csv_file="researchers.csv",
    max_threads=5,
    max_requests_per_ip=6,
    output_dir="./output"
)
results = runner.process_researchers_from_csv()
```

## Output Structure

```
Researcher_Profiles/
├── SCHOLAR_ID_1/
│   ├── profile.json    # Researcher metadata
│   └── papers.csv      # Top 50 papers with details
├── SCHOLAR_ID_2/
│   ├── profile.json
│   └── papers.csv
└── ...

logs/
└── run_YYYYMMDD_HHMMSS/
    ├── scraping_progress.json  # Session progress (for --continue)
    └── ip_usage_tracker.json   # Tor IP usage statistics
```

### Profile JSON Structure

```json
{
  "scholar_id": "SCHOLAR_ID",
  "profile_url": "https://scholar.google.com/citations?user=...",
  "author_name": "Researcher Name",
  "author_affiliation": "University",
  "author_citations": "12345",
  "research_keywords": "Machine Learning, AI, ...",
  "homepage": "https://researcher-website.com",
  "tor_ip_used": "1.2.3.4",
  "scrape_timestamp": "2025-01-26 12:00:00",
  "scrape_method": "direct_scholar_id"
}
```

### Papers CSV Columns

| Column | Description |
|--------|-------------|
| Rank | Citation rank (1-50) |
| Title | Paper title |
| Citations | Number of citations |
| Year | Publication year |
| URL | Google Scholar paper URL |
| Description | Paper abstract/description |

## Development

### Setup development environment

```bash
git clone https://github.com/yourusername/scholarmine.git
cd scholarmine
pip install -e ".[dev]"
```

### Run tests

```bash
pytest
```

### Code formatting

```bash
black scholarmine/
ruff check scholarmine/
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Disclaimer

This tool is intended for academic research purposes. Please use responsibly and respect Google Scholar's terms of service. The authors are not responsible for any misuse of this software.
