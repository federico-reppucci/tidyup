# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup & Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"
# Fix macOS UF_HIDDEN flag: .venv starts with "." so macOS marks all contents hidden,
# which causes Python 3.12 site.py to skip .pth files → ModuleNotFoundError
chflags -R nohidden venv

# Run all tests
pytest tests/ -v

# Run a single test file or test
pytest tests/test_organizer.py -v
pytest tests/test_organizer.py::test_parse_response_basic -v

# Coverage
pytest tests/ -v --cov=src/tidyup --cov-report=html

# Lint & format
ruff format --check src/ tests/
ruff check src/ tests/

# Type check
mypy src/tidyup/
```

Python 3.12+ required. No runtime dependencies (stdlib only). Dev deps: pytest, ruff, mypy.

ruff config: py312, line-length 100, select E,W,F,I,UP,B,SIM,RUF. mypy: check_untyped_defs, warn_return_any. CI runs on macOS (tests need `textutil`, `mdls`, `osascript`).

## Architecture

### In-place organization (v2)

Files are organized *in-place* within any target folder (defaults to `~/Downloads`). No staging dirs, no review step — just scan, organize, done. The LLM decides everything (no hardcoded rules). Undo is preserved via the journal system.

### End-to-end flow

```
tidyup scan [PATH] [--dry-run]
  1. scan_downloads() — recurse target dir (default ~/Downloads), collect ALL files with relative paths
  2. detect_duplicates() — SHA-256 dedup, extras → Trash/
  3. organizer.organize() — LLM proposes folder structure as JSON
  4. Compute diff — skip files already at correct location (needs_move=False)
  5. execute_moves() — move files, journal each one
  6. cleanup_empty_dirs() — remove empty folders bottom-up
  7. Print summary
```

### LLM organization

`OllamaOrganizer` sends all files in a single LLM call. The LLM sees file relative paths, MIME types, sizes, and content previews. It proposes a folder structure with 3-10 top-level folders. Junk goes to `Trash/`, empty string means root.

`ParallelOllamaOrganizer` splits files into batches for 80+ files, using `ThreadPoolExecutor` for concurrent LLM calls.

Dynamic token limits: `num_ctx = max(4096, len(prompt)//4 + num_predict + 512)`, `num_predict = len(files) * 60 + 200`.

### LLM backends

- `OllamaOrganizer` — single call via Ollama HTTP API (default model: `gemma3:4b`)
- `ParallelOllamaOrganizer` — concurrent batches for large file counts
- `AppleFMClient` — Apple Intelligence via `afm-cli` subprocess (`--model apple`)

All LLM clients expose `generate(prompt, timeout, on_token, options, keep_alive) -> GenerateResult` (dataclass with `.data`, `.token_count`, `.elapsed`).

## Key modules

| Module | Role |
|---|---|
| `config.py` | Dataclass config: `target_dir` (default ~/Downloads), `excluded_dirs`, `parallel_requests=4`, `mini_batch_size=5` |
| `scanner.py` | Recursive file discovery with `relative_path` field, `.app` bundle handling |
| `helpers.py` | `Proposal` dataclass, `build_file_descriptions()`, `precompute_previews()`, `parse_organize_response()`, `sha256_file()` |
| `prompts.py` | `ORGANIZE_PROMPT` template, `build_organize_prompt()` |
| `organizer.py` | `OllamaOrganizer`, `ParallelOllamaOrganizer`, `detect_duplicates()` |
| `mover.py` | `move_file_safely()`, `execute_moves()`, `cleanup_empty_dirs()` |
| `journal.py` | JSONL undo log with `"organize"` operation type |
| `cli.py` | CLI: `scan`, `undo`, `status`, `benchmark` commands |
| `ollama_client.py` | HTTP client with streaming, auto-start, model pull; `GenerateResult` dataclass |
| `apple_fm_client.py` | Apple FM client via `afm-cli` subprocess |
| `content.py` | Content preview extraction (text, PDF via poppler, textutil, mdls metadata fallback) |
| `benchmark.py` | `run_benchmark()`, comparison table, agreement matrix, folder structure summary |

## Config & data paths

- Config override: `~/.config/tidyup/config.json`
- Undo log: `~/.local/share/tidyup/undo_log.jsonl`

## Test fixtures (conftest.py)

- `tmp_config` — isolated Config pointing to temp directories
- `sample_downloads` — pre-populated Downloads dir with root files + nested dirs (`Projects/2024/data.csv`) + hidden dir
- `mock_ollama_response` — factory for mock LLM JSON responses in organize format
