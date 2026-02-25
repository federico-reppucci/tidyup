# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup & Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run a single test file or test
pytest tests/test_classifier.py -v
pytest tests/test_classifier.py::test_tier1_dmg -v

# Coverage
pytest tests/ -v --cov=src/tidydownloads --cov-report=html
```

No linting tools are configured. Python 3.12+ required.

## Architecture

**Two-tier classification pipeline:**

1. **Tier 1 (rules)**: Extension-based — `.dmg`, `.pkg`, `.torrent`, etc. get instant delete classification
2. **Tier 2 (LLM)**: Files that can't be classified by rules go to an LLM in batches, with a **Stage 2 subfolder refinement** pass that picks the best subfolder within the top-level destination

**Pluggable LLM backends** via `ClassifierBackend` protocol in `classifier.py`:
- `OllamaBackend` — local Ollama HTTP API (default model: `gemma3:1b`)
- `AppleFMClient` — Apple Intelligence on-device model via `afm-cli` subprocess (use `--model apple`)
- `RulesOnlyBackend` — no LLM, extension rules only

Both LLM clients expose the same `generate(prompt, timeout, on_token) -> dict` interface. The `_LLM_ERRORS` tuple in `classifier.py` and `benchmark.py` catches errors from either.

**End-to-end flow:** `scan` → `scanner` discovers files → `taxonomy` reads `~/Documents` structure → `classifier` runs Tier 1 + Tier 2 → `stager` moves files to `to_delete/`, `to_move/`, `unsorted/` → `review` launches Flask web UI → `journal` records moves for undo.

## Key modules

| Module | Role |
|---|---|
| `classifier.py` | Core logic: `classify_files()`, `refine_subfolders()`, `_parse_llm_response()` |
| `ollama_client.py` | Ollama HTTP client with streaming, auto-start, model pull |
| `apple_fm_client.py` | Apple FM client via `afm-cli` subprocess, strips markdown code fences |
| `prompts.py` | LLM prompt templates (`build_classification_prompt`, `build_subfolder_prompt`) |
| `benchmark.py` | `TimedBackend` wraps any client for timing; `run_model()` routes `"apple"` vs Ollama |
| `taxonomy.py` | Discovers `~/Documents` folder tree as LLM context |
| `stager.py` | Moves files to staging dirs, writes `proposals.json` |
| `journal.py` | JSONL undo log for reversing file operations |
| `web/server.py` | Flask review UI with token auth |

## Config & data paths

- Config override: `~/.config/tidydownloads/config.json`
- Proposals: `~/.local/share/tidydownloads/proposals.json`
- Undo log: `~/.local/share/tidydownloads/undo_log.jsonl`
- Staging dirs: `~/Downloads/to_delete/`, `to_move/`, `unsorted/`

## Test fixtures (conftest.py)

- `tmp_config` — isolated Config pointing to temp directories
- `sample_downloads` — pre-populated Downloads dir
- `sample_documents` — pre-populated Documents structure
- `mock_ollama_response` — factory for mock LLM JSON responses
