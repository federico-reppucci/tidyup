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
  [1/5] Scanning        — scan_downloads(), collect ALL files with relative paths
  [2/5] Deduplicating   — detect_duplicates(), SHA-256 dedup, extras → Trash/
  [3/5] Extracting previews — precompute_previews(), parallel content extraction
  [4/5] Organizing via LLM  — organizer.organize(), LLM proposes folder structure as JSON
  [5/5] Moving files    — execute_moves(), move files + journal each one
  cleanup_empty_dirs()  — remove empty folders bottom-up
  Print summary
```

Each phase shows a `[n/5]` progress indicator with elapsed time. Phase 4 (LLM) displays a live spinner with token count (single mode) or batch progress (parallel mode). All progress output is thread-safe via `ProgressDisplay`.

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
| `organizer.py` | `OllamaOrganizer`, `ParallelOllamaOrganizer`, `detect_duplicates()`; accepts optional `progress` param |
| `mover.py` | `move_file_safely()`, `execute_moves(quiet=)`, `cleanup_empty_dirs()` |
| `journal.py` | JSONL undo log with `"organize"` operation type |
| `cli.py` | CLI: `scan`, `undo`, `status`, `install`, `uninstall` commands |
| `progress.py` | `ProgressDisplay` — thread-safe `[n/5]` phase progress with spinner, elapsed time, batch tracking |
| `install.py` | Finder Quick Action: generates `.workflow` bundle for `~/Library/Services/`, `install_quick_action()`, `uninstall_quick_action()` |
| `ollama_client.py` | HTTP client with streaming, auto-start, model pull; `GenerateResult` dataclass |
| `apple_fm_client.py` | Apple FM client via `afm-cli` subprocess |
| `content.py` | Content preview extraction (text, PDF via poppler, textutil, mdls metadata fallback) |

## Finder Quick Action

`tidyup install` generates a macOS Automator Quick Action (`.workflow` bundle) at `~/Library/Services/tidyup.workflow`. The bundle structure mirrors Apple's system workflows:

```
tidyup.workflow/Contents/
  Info.plist                  (NSServices entry for pbs registration)
  Resources/
    document.wflow            (Automator workflow: Run Shell Script action)
    en.lproj/
      ServicesMenu.strings    (localized menu title)
```

Key details:
- `Info.plist` must include `NSServices` with `NSMessage: runWorkflowAsService` and `NSSendFileTypes` — this is what macOS pbs uses to register the service
- `document.wflow` goes in `Resources/` (not `Contents/` directly)
- The shell script uses `osascript` with `quoted form of` for paths with spaces to open Terminal and run `tidyup scan <folder>`
- After install, the service may need to be enabled in System Settings → Keyboard → Keyboard Shortcuts → Services
- `pbs -flush` or `killall pbs` forces re-registration

## Stress benchmark

`scripts/stress_benchmark.py` generates a reproducible synthetic file set and runs the parallel scan against it.

```bash
python3 scripts/stress_benchmark.py [--count 500] [--model gemma3:4b] [--seed 42] [--keep] [--generate-only] [--dir PATH]
```

Generates ~470 unique + ~30 duplicate files across 9 categories (documents, images, code, media, archives, config, etc.) with realistic filenames, valid magic bytes, and nested subdirectories. Uses stdlib only (`struct.pack`, `zlib`, `zipfile`). Output dir `stress_test_data/` is gitignored.

## Config & data paths

- Config override: `~/.config/tidyup/config.json`
- Undo log: `~/.local/share/tidyup/undo_log.jsonl`
- Quick Action: `~/Library/Services/tidyup.workflow`
- Stress test data: `./stress_test_data/` (gitignored)

## Test fixtures (conftest.py)

- `tmp_config` — isolated Config pointing to temp directories
- `sample_downloads` — pre-populated Downloads dir with root files + nested dirs (`Projects/2024/data.csv`) + hidden dir
- `mock_ollama_response` — factory for mock LLM JSON responses in organize format
