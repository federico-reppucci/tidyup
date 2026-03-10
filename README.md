# TidyUp

[![CI](https://github.com/federico-reppucci/tidyup/actions/workflows/ci.yml/badge.svg)](https://github.com/federico-reppucci/tidyup/actions/workflows/ci.yml)

Local AI-powered file organizer. Scans any folder (defaults to `~/Downloads`), asks a local LLM to propose a clean folder structure, and moves files in-place. No cloud, no rules — the LLM decides everything.

## How it works

```
  [1/5] Scanning.............. 523 files found (0s)
  [2/5] Deduplicating......... 12 duplicates -> Trash/ (1s)
  [3/5] Extracting previews... 340 files (3s)
  [4/5] Organizing via LLM... ⠹ batch 5/13 · 4 active · 312 tokens (42s)
  [5/5] Moving files.......... 418 moved (0s)
```

1. Recursively scans the target folder
2. Detects duplicates via SHA-256 (extras go to `Trash/`)
3. Extracts content previews (text, PDF, metadata)
4. Sends file metadata + previews to a local LLM (parallel batches for 80+ files)
5. LLM proposes 3-10 top-level folders as JSON
6. Files are moved in-place, with every move journaled for undo

Live progress is shown for every phase, with elapsed time and token counts.

## Commands

```bash
tidyup scan              # Organize ~/Downloads
tidyup scan ~/Desktop    # Organize a different folder
tidyup scan --dry-run    # Preview without moving
tidyup undo              # Reverse the last operation
tidyup status            # Check Ollama + journal status
tidyup install           # Add "TidyUp" to Finder's right-click menu
tidyup uninstall         # Remove the Finder integration
```

## Install

### Homebrew (recommended)

```bash
brew tap federico-reppucci/tidyup https://github.com/federico-reppucci/tidyup.git
brew install tidyup
```

On first run, the default model (`gemma3:4b`) is downloaded automatically.

### From source

```bash
brew install python@3.12 ollama poppler  # poppler is optional (PDF text extraction)
git clone https://github.com/federico-reppucci/tidyup.git
cd tidyup
python3.12 -m venv venv
source venv/bin/activate
pip install -e .
brew services start ollama
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

### Stress testing

Generate a synthetic 500-file test folder and scan against it:

```bash
# Full run: generate 500 files + scan + cleanup
python3 scripts/stress_benchmark.py

# Generate only, inspect the files
python3 scripts/stress_benchmark.py --generate-only --keep

# Re-run against existing data
python3 scripts/stress_benchmark.py --dir stress_test_data/ --model gemma3:4b
```

### Finder integration

Organize folders directly from Finder's right-click menu:

```bash
tidyup install
```

This creates a macOS Quick Action. After installing, right-click any folder in Finder → **Services** → **TidyUp**. A Terminal window opens and runs `tidyup scan` on that folder.

To remove it: `tidyup uninstall`.

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
