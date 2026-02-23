# TidyDownloads

Local AI-powered download organizer. Scans `~/Downloads`, classifies files using a local LLM (Ollama), and stages them for review.

## How it works

1. **`tidydownloads scan`** — Classifies files in `~/Downloads` using rule-based heuristics + Ollama LLM
   - Obvious files (`.dmg`, `.pkg`, `.crdownload`) are staged instantly
   - Ambiguous files are sent to Ollama for classification with your Documents folder structure as context
   - Low-confidence results stay in Downloads (not staged)
2. **`tidydownloads review`** — Opens a local web UI to accept/reject proposed moves
3. **`tidydownloads undo`** — Reverses the last operation
4. **`tidydownloads status`** — Shows Ollama status and last run stats

## Prerequisites

```bash
brew install python@3.12 ollama poppler
ollama pull llama3.1:8b
```

## Install

```bash
git clone https://github.com/FedericoReppucci/tidydownloads.git
cd tidydownloads
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

```bash
# Scan and classify
tidydownloads scan

# Dry run (no files moved)
tidydownloads scan --dry-run

# Review staged files in browser
tidydownloads review

# Undo last operation
tidydownloads undo

# Check status
tidydownloads status
```

## Architecture

- **Tier 1**: Rule-based classification by file extension (instant, no LLM)
- **Tier 2**: Ollama LLM classification with Documents folder context
- **Confidence filter**: Only files with confidence >= 0.7 are staged
- **Staging folders**: `~/Downloads/to_delete/` and `~/Downloads/to_move/`
- **Undo log**: Every move is journaled for safe reversal

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
