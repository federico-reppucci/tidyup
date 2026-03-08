# TidyUp

[![CI](https://github.com/federico-reppucci/tidydownloads/actions/workflows/ci.yml/badge.svg)](https://github.com/federico-reppucci/tidydownloads/actions/workflows/ci.yml)

Local AI-powered file organizer. Scans any folder (defaults to `~/Downloads`), asks a local LLM to propose a clean folder structure, and moves files in-place. No cloud, no rules — the LLM decides everything.

## How it works

1. Recursively scans the target folder
2. Detects duplicates via SHA-256 (extras go to `Trash/`)
3. Sends file metadata + content previews to a local LLM
4. LLM proposes 3-10 top-level folders as JSON
5. Files are moved in-place, with every move journaled for undo

## Commands

```bash
tidyup scan              # Organize ~/Downloads
tidyup scan ~/Desktop    # Organize a different folder
tidyup scan --dry-run    # Preview without moving
tidyup undo              # Reverse the last operation
tidyup status            # Check Ollama + journal status
tidyup benchmark         # Compare models (speed, quality, agreement)
```

## Install

### Homebrew (recommended)

```bash
brew tap federico-reppucci/tidydownloads https://github.com/federico-reppucci/tidydownloads.git
brew install tidyup
```

On first run, the default model (`gemma3:4b`) is downloaded automatically.

### From source

```bash
brew install python@3.12 ollama poppler
git clone https://github.com/federico-reppucci/tidydownloads.git
cd tidydownloads
python3.12 -m venv venv
source venv/bin/activate
pip install -e .
```

## Usage

```bash
# Default: organize ~/Downloads with gemma3:4b
tidyup scan

# Use a different model
tidyup --model gemma3:12b scan

# Use Apple Intelligence (macOS 26+, no Ollama needed)
tidyup --model apple scan

# Dry run
tidyup scan --dry-run

# Undo last operation
tidyup undo
```

### Benchmarking

Compare models on your actual files:

```bash
# All default models
tidyup benchmark

# Specific folder
tidyup benchmark ~/Desktop

# Pick models and run twice for consistency
tidyup benchmark --models gemma3:4b qwen3:4b gemma3:12b --runs 2
```

### Model recommendations

Benchmarked on 14 files, M4 MacBook Pro (16 GB RAM):

| Model | Params | Type | Time | Tok/s | Folders | Notes |
|---|---|---|---|---|---|---|
| **gemma3:4b** | 4B | non-thinking | 18s | 30 | 6 | Default. Fast, good quality |
| qwen3:4b | 4B | thinking | 16s | 30 | 6 | Similar speed, different grouping |
| gemma3:12b | 12B | non-thinking | 73s | 7 | 6 | Better quality, 4x slower |
| qwen3.5:9b | 9B | thinking | 59s | 9 | 5 | Thinking model, diminishing returns |
| qwen3.5:27b | 27B | thinking | 189s | 3 | 6 | Too slow for 16 GB machines |

All models returned valid JSON and covered 100% of files. Cross-model agreement was 28-50%, suggesting organization is subjective — the 4B models are the sweet spot for speed vs quality.

### Configuration

Override defaults in `~/.config/tidyup/config.json`:

```json
{
  "ollama_model": "gemma3:4b",
  "parallel_requests": 4,
  "mini_batch_size": 5
}
```

Data paths:
- Undo log: `~/.local/share/tidyup/undo_log.jsonl`

## Development

```bash
pip install -e ".[dev]"

pytest tests/ -v
ruff check src/ tests/
mypy src/tidyup/
```

Python 3.12+ required. No runtime dependencies (stdlib only).

## License

MIT
