# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup & Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"
# Fix macOS UF_HIDDEN flag: .venv starts with "." so macOS marks all contents hidden,
# which causes Python 3.12 site.py to skip .pth files → ModuleNotFoundError
chflags -R nohidden .venv

# Run all tests
pytest tests/ -v

# Run a single test file or test
pytest tests/test_classifier.py -v
pytest tests/test_classifier.py::test_tier1_dmg -v

# Coverage
pytest tests/ -v --cov=src/tidydownloads --cov-report=html

# Lint & format
ruff format --check src/ tests/
ruff check src/ tests/

# Type check
mypy src/tidydownloads/

# Run benchmark (requires Ollama running)
PYTHONPATH=src .venv/bin/python -m tidydownloads benchmark --model gemma3:4b --files 20 --seed 42
```

Python 3.12+ required. Runtime dependency: Flask 3.0+. Dev deps: pytest, ruff, mypy.

ruff config: py312, line-length 100, select E,W,F,I,UP,B,SIM,RUF. mypy: check_untyped_defs, warn_return_any. CI runs on macOS (tests need `textutil`, `mdls`, `osascript`).

## Architecture

### Two-tier classification pipeline

1. **Tier 1 (rules)**: Extension-based — `.dmg`, `.pkg`, `.torrent`, etc. get instant delete classification. Defined in `classifier.py` via `TIER1_DELETE` dict.
2. **Tier 2 (LLM)**: Remaining files go to an LLM using a midsize taxonomy format (`taxonomy.to_midsize_text()`) that shows destination paths with sample filenames. `validate_destination()` in `helpers.py` fuzzy-matches LLM output against valid taxonomy paths (exact → case-insensitive → stripped numeric prefix → top-folder).

### Parallel mini-batch classification

`ParallelOllamaBackend` in `classifier.py` splits files into mini-batches (default 5) and submits them concurrently via `ThreadPoolExecutor` (default 4 workers), leveraging Ollama's `OLLAMA_NUM_PARALLEL` for concurrent KV caches.

- `as_completed()` collects results as batches finish
- Per-future try/except — a failed batch yields `unsorted` without losing other batches
- `num_predict = batch_size * 60 + 50` — dynamic output token limit to prevent JSON truncation
- `num_ctx=4096`, `keep_alive="10m"`, `PREVIEW_CHARS=150`
- When `config.parallel_requests > 1`, `cmd_scan()` automatically uses `ParallelOllamaBackend`

### Pluggable LLM backends

`ClassifierBackend` protocol in `classifier.py`:
- `ParallelOllamaBackend` — concurrent mini-batches (default for Ollama)
- `OllamaBackend` — sequential fallback
- `AppleFMClient` — Apple Intelligence via `afm-cli` subprocess (`--model apple`)
- `RulesOnlyBackend` — extension rules only, no LLM

All LLM clients expose `generate(prompt, timeout, on_token, options=None, keep_alive=None) -> dict`. The `_LLM_ERRORS` tuple catches errors from either Ollama or Apple FM.

### End-to-end flow

`cli.cmd_scan()` → `scanner.scan_downloads()` → `taxonomy.discover_taxonomy()` → `classifier.classify_files()` (Tier 1 + Tier 2 parallel) → `stager.stage_files()` moves to `to_delete/`, `to_move/`, `unsorted/` → `cli.cmd_review()` launches Flask web UI → `journal` records moves for undo.

### Benchmarking

`benchmark.py` provides `TimedBackend` (sequential) and `ParallelTimedBackend` (parallel) that wrap any client with per-batch timing. `run_model()` accepts a `parallel` flag. The benchmark copies real files from `~/Documents` to `~/Downloads`, classifies them, and compares destinations against actual file locations.

## Key modules

| Module | Role |
|---|---|
| `helpers.py` | `Classification` dataclass, `validate_destination()`, `build_file_descriptions()`, `precompute_previews()`, `parse_llm_response()` |
| `classifier.py` | Tier 1 rules, `ClassifierBackend` protocol, `OllamaBackend`, `ParallelOllamaBackend`, `RulesOnlyBackend`, `classify_files()`, `refine_subfolders()` |
| `ollama_client.py` | HTTP client with streaming, auto-start, model pull, `check_parallel_support()`, `options`/`keep_alive` passthrough |
| `apple_fm_client.py` | Apple FM client via `afm-cli` subprocess, strips markdown code fences |
| `prompts.py` | LLM prompt templates (`build_classification_prompt`, `build_subfolder_prompt`) |
| `benchmark.py` | `TimedBackend`, `ParallelTimedBackend`, `run_model()`, accuracy scoring |
| `taxonomy.py` | Discovers `~/Documents` folder tree; `to_midsize_text()` for LLM context |
| `content.py` | Content preview extraction (text, PDF via poppler, textutil, mdls metadata fallback) |
| `config.py` | Dataclass config: `parallel_requests=4`, `mini_batch_size=5`, `confidence_threshold=0.45` |
| `stager.py` | Moves files to staging dirs, writes `proposals.json` |
| `journal.py` | JSONL undo log for reversing file operations |
| `web/server.py` | Flask review UI with token auth |

## Config & data paths

- Config override: `~/.config/tidydownloads/config.json`
- Proposals: `~/.local/share/tidydownloads/proposals.json`
- Undo log: `~/.local/share/tidydownloads/undo_log.jsonl`
- Benchmark results: `~/.local/share/tidydownloads/benchmark_results.json`
- Staging dirs: `~/Downloads/to_delete/`, `to_move/`, `unsorted/`

## Test fixtures (conftest.py)

- `tmp_config` — isolated Config pointing to temp directories
- `sample_downloads` — pre-populated Downloads dir with Tier 1 (.dmg, .pkg) and Tier 2 (.pdf, .txt) files
- `sample_documents` — pre-populated Documents structure (Finance, Work, Personal)
- `mock_ollama_response` — factory for mock LLM JSON responses
