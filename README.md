# TidyDownloads

Local AI-powered download organizer. Scans `~/Downloads`, classifies files using a local LLM (Ollama or Apple Intelligence), and stages them for review.

## How it works

1. **`tidydownloads scan`** — Classifies files in `~/Downloads` using rule-based heuristics + LLM
   - Obvious files (`.dmg`, `.pkg`, `.crdownload`) are staged instantly (Tier 1 rules)
   - Ambiguous files are sent to an LLM in parallel mini-batches, using your `~/Documents` folder structure as context
   - Low-confidence results (below 0.45) go to `unsorted/`
2. **`tidydownloads review`** — Opens a local web UI to accept/reject proposed moves
3. **`tidydownloads undo`** — Reverses the last operation
4. **`tidydownloads status`** — Shows Ollama status and last run stats
5. **`tidydownloads benchmark`** — Compares model accuracy and speed on your real files

## Install

### Homebrew (recommended)

```bash
brew tap federico-reppucci/tidydownloads https://github.com/federico-reppucci/tidydownloads.git
brew install tidydownloads
```

This automatically installs Ollama, poppler, and Python. On first run, the default model is downloaded automatically:

```bash
tidydownloads scan
```

### From source

```bash
brew install python@3.12 ollama poppler
git clone https://github.com/federico-reppucci/tidydownloads.git
cd tidydownloads
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Parallel performance

For faster scans on machines with 16+ GB RAM:

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 4
brew services restart ollama
```

## Usage

```bash
# Scan and classify (uses parallel mini-batches by default)
tidydownloads scan

# Use a specific model
tidydownloads --model gemma3:12b scan

# Use Apple Intelligence (macOS 26+)
tidydownloads --model apple scan

# Dry run (no files moved)
tidydownloads scan --dry-run

# Review staged files in browser
tidydownloads review

# Undo last operation
tidydownloads undo

# Check status
tidydownloads status
```

### Benchmarking

Compare models on a random sample of your Documents files:

```bash
# Single model
tidydownloads benchmark --model gemma3:4b --files 20 --seed 42

# Compare multiple models
tidydownloads benchmark --model gemma3:4b --model gemma3:12b --files 20

# Sequential mode (disable parallel mini-batches)
tidydownloads benchmark --model gemma3:4b --files 20 --no-parallel
```

### Model recommendations

| Model | Speed | Accuracy | Notes |
|---|---|---|---|
| gemma3:4b | ~1.0 files/s | ~38% top-folder | Best speed, decent for simple taxonomies |
| llama3.1:8b | ~0.4 files/s | ~40-45% top-folder | Good balance, only model with exact matches |
| gemma3:12b | ~0.3 files/s | ~50-75% top-folder | Best accuracy, fewest wrong destinations |
| qwen2.5:1.5b | ~1.0 files/s | ~29-64% top-folder | Variable accuracy, fast |
| phi4-mini | ~0.5 files/s | ~9% top-folder | Not recommended for this task |

Benchmarked on 48GB M4 Pro with `OLLAMA_NUM_PARALLEL=4`, 20 files, parallel mode.

## Architecture

- **Tier 1**: Rule-based classification by file extension (instant, no LLM)
- **Tier 2**: LLM classification using midsize taxonomy format with content previews
- **Parallel mini-batches**: Files are split into batches of 5 and classified concurrently (4 workers) via `ThreadPoolExecutor` + Ollama's parallel request support
- **Confidence filter**: Files with confidence < 0.45 go to `unsorted/`
- **Staging folders**: `~/Downloads/to_delete/`, `to_move/`, `unsorted/`
- **Undo log**: Every move is journaled for safe reversal

### Configuration

Override defaults in `~/.config/tidydownloads/config.json`:

```json
{
  "ollama_model": "gemma3:12b",
  "parallel_requests": 4,
  "mini_batch_size": 5,
  "confidence_threshold": 0.45,
  "batch_size": 25
}
```

## Development

```bash
pip install -e ".[dev]"

# Tests
pytest tests/ -v
pytest tests/ -v --cov=src/tidydownloads --cov-report=html

# Lint & format
ruff format --check src/ tests/
ruff check src/ tests/

# Type check
mypy src/tidydownloads/
```

## License

MIT
