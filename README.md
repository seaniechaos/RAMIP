# RAMIP — Rude Awakening Morning Intelligence Pipeline

RAMIP pulls items from RSS feeds, scores them against editorial beats, clusters
related stories, formats a morning brief, and emails it over SMTP.

## Project layout

| File | Purpose |
| --- | --- |
| `sources.yaml` | RSS feed list grouped by category |
| `beats.yaml` | Editorial beat definitions and keywords |
| `seen_items.db` | SQLite store of previously seen item URL hashes |
| `fetch.py` | Download feeds defined in `sources.yaml` |
| `score.py` | Rank fetched items against beat definitions |
| `cluster.py` | Group related items into stories |
| `format.py` | Render the brief as HTML/text |
| `send.py` | Deliver the brief over SMTP |
| `run.py` | Orchestrator that runs the full pipeline |
| `.env.template` | Template for required environment variables |
| `requirements.txt` | Python dependencies |

## Setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy the env template and fill in your secrets:

   ```bash
   cp .env.template .env
   # edit .env
   ```

   Required keys:

   - `ANTHROPIC_API_KEY` — Anthropic API key used by `score.py` / `cluster.py`
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` — SMTP credentials for `send.py`
   - `TO_EMAIL` — recipient address for the brief

   `.env` is loaded via `python-dotenv` in `run.py`. Never commit real
   credentials; only `.env.template` belongs in the repo.

4. Edit `sources.yaml` and `beats.yaml` to define your feeds and beats.

## Running

Run the full pipeline:

```bash
python run.py
```

Run a single stage in isolation (useful while developing):

```bash
python fetch.py
python score.py
python cluster.py
python format.py
python send.py
```

## Storage

`seen_items.db` is a SQLite database with a single table:

```sql
CREATE TABLE seen_items (
    url_hash TEXT PRIMARY KEY,
    seen_at  DATETIME
);
```

`fetch.py` is expected to insert URL hashes here so subsequent runs skip items
that have already been processed.
