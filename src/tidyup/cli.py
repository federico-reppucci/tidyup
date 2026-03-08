"""CLI entry point: scan | undo | status."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from tidyup.config import Config
from tidyup.logger_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tidyup",
        description="Local AI-powered download organizer",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug output")
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model to use: an Ollama model name (e.g. gemma3:1b) "
        "or 'apple' for Apple Intelligence on-device model",
    )
    sub = parser.add_subparsers(dest="command")

    # scan
    scan_p = sub.add_parser("scan", help="Organize files in a folder")
    scan_p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Folder to organize (default: ~/Downloads)",
    )
    scan_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed moves without executing them",
    )

    # undo
    sub.add_parser("undo", help="Reverse the last organize operation")

    # status
    sub.add_parser("status", help="Check Ollama status and show last run stats")

    # benchmark
    bench_p = sub.add_parser("benchmark", help="Compare LLM models on file organization")
    bench_p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Folder to scan (default: ~/Downloads)",
    )
    bench_p.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="Models to benchmark (default: gemma3:4b qwen3:4b gemma3:12b qwen3.5:9b qwen3.5:27b)",
    )
    bench_p.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Runs per model for consistency check (default: 1)",
    )

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    config = Config.load()
    if args.model:
        config.ollama_model = args.model

    # Override target_dir if path specified on scan/benchmark command
    if args.command in ("scan", "benchmark") and args.path:
        config.target_dir = Path(args.path).expanduser().resolve()

    setup_logging(config.log_dir, verbose=args.verbose)

    if args.command == "scan":
        return cmd_scan(config, dry_run=args.dry_run)
    elif args.command == "undo":
        return cmd_undo(config)
    elif args.command == "status":
        return cmd_status(config)
    elif args.command == "benchmark":
        return cmd_benchmark(config, models=args.models, runs=args.runs)

    return 0


def _check_ollama_setup(config: Config, dry_run: bool = False):
    """Ensure Ollama is running and the model is available.

    Returns a ready OllamaClient, or None if setup fails.
    """
    from tidyup.ollama_client import OllamaClient, OllamaError

    if not shutil.which("ollama"):
        print(
            "Ollama is not installed.\n\n"
            "  Install:  brew install ollama\n"
            "  Start:    brew services start ollama\n"
            "  Then run: tidyup scan"
        )
        return None

    client = OllamaClient(config.ollama_url, config.ollama_model)

    try:
        client.ensure_running()
    except OllamaError as e:
        print(f"Error: {e}")
        return None

    if not client.is_model_available():
        if dry_run:
            print(f"Warning: model '{config.ollama_model}' not available.")
        else:
            answer = (
                input(f"Model '{config.ollama_model}' not found. Download it? [y/N] ")
                .strip()
                .lower()
            )
            if answer in ("y", "yes"):
                print(f"Pulling {config.ollama_model}...")
                try:
                    client.pull_model()
                except OllamaError as e:
                    print(f"Error: {e}")
                    return None
                print(f"Model '{config.ollama_model}' ready.\n")
            else:
                print("Aborted.")
                return None

    return client


def cmd_scan(config: Config, dry_run: bool = False) -> int:
    from tidyup.apple_fm_client import AppleFMClient
    from tidyup.mover import cleanup_empty_dirs, execute_moves
    from tidyup.organizer import OllamaOrganizer, ParallelOllamaOrganizer, detect_duplicates
    from tidyup.scanner import scan_downloads

    print(f"TidyUp -- Scanning {config.target_dir}...\n")

    # Prepare LLM organizer
    organizer: OllamaOrganizer | ParallelOllamaOrganizer
    if config.ollama_model == "apple":
        apple_client = AppleFMClient()
        if not apple_client.is_available():
            print(
                "Error: Apple Foundation Model not available. "
                "Requires macOS 26+ with Apple Intelligence and afm-cli installed."
            )
            return 1
        organizer = OllamaOrganizer(apple_client)  # type: ignore[arg-type]
    else:
        client = _check_ollama_setup(config, dry_run)
        if client is None:
            return 1
        if config.parallel_requests > 1:
            organizer = ParallelOllamaOrganizer(
                client,
                batch_size=config.mini_batch_size * 8,
                workers=config.parallel_requests,
            )
        else:
            organizer = OllamaOrganizer(client)

    # Scan
    files = scan_downloads(config)
    if not files:
        print("No files to organize.")
        return 0

    print(f"Found {len(files)} files.\n")

    # Detect duplicates
    dup_proposals, unique_files = detect_duplicates(files)
    if dup_proposals:
        print(f"  Duplicates: {len(dup_proposals)} files -> Trash/")

    # Organize via LLM
    if unique_files:
        print(f"  Organizing {len(unique_files)} files via LLM...")
        llm_proposals = organizer.organize(unique_files)
    else:
        llm_proposals = []

    all_proposals = dup_proposals + llm_proposals
    moves = [p for p in all_proposals if p.needs_move]

    if not moves:
        print("\nAll files are already well-organized. Nothing to do.")
        return 0

    # Print proposed moves (first 20)
    print(f"\nProposed moves ({len(moves)} files):")
    for p in moves[:20]:
        folder_display = p.destination_folder or "(root)"
        print(f"  {p.relative_path} -> {folder_display}")
    if len(moves) > 20:
        print(f"  ... and {len(moves) - 20} more")

    # Execute
    print()
    result = execute_moves(all_proposals, config.target_dir, config.undo_log_path, dry_run)

    if not dry_run:
        cleaned = cleanup_empty_dirs(config.target_dir)
        if cleaned:
            print(f"  Cleaned up {cleaned} empty folders.")

    # Summary
    print(f"\nDone! Moved: {result['moved']}, Skipped: {result['skipped']}", end="")
    if result["failed"]:
        print(f", Failed: {result['failed']}")
    else:
        print()

    if not dry_run and result["moved"]:
        print("\nTo undo: tidyup undo")

    return 0


def cmd_undo(config: Config) -> int:
    from tidyup.journal import undo_last
    from tidyup.mover import cleanup_empty_dirs

    print("TidyUp -- Undoing last operation...")

    result = undo_last(config.undo_log_path)

    if result.reversed_count == 0 and not result.failed:
        print("Nothing to undo.")
        return 0

    print(f"  Reversed {result.reversed_count} file moves (scan_id: {result.scan_id})")

    # Clean up empty folders left behind
    cleaned = cleanup_empty_dirs(config.target_dir)
    if cleaned:
        print(f"  Cleaned up {cleaned} empty folders.")

    if result.failed:
        print(f"  Failed to reverse {len(result.failed)} moves:")
        for f in result.failed:
            print(f"    - {f}")
        return 1

    return 0


def cmd_status(config: Config) -> int:
    from tidyup.journal import get_entries
    from tidyup.ollama_client import OllamaClient

    print("TidyUp -- Status\n")

    # Ollama status
    client = OllamaClient(config.ollama_url, config.ollama_model)
    if client.is_serving():
        print(f"  Ollama: running at {config.ollama_url}")
        if client.is_model_available():
            print(f"  Model:  {config.ollama_model} (available)")
        else:
            print(
                f"  Model:  {config.ollama_model} "
                f"(NOT FOUND -- run: ollama pull {config.ollama_model})"
            )
    else:
        print("  Ollama: not running")

    # Journal
    entries = get_entries(config.undo_log_path)
    active = [e for e in entries if not e.undone]
    print(f"\n  Undo log: {len(active)} active entries, {len(entries) - len(active)} undone")

    return 0


def cmd_benchmark(config: Config, models: list[str] | None = None, runs: int = 1) -> int:
    from tidyup.benchmark import (
        print_agreement_matrix,
        print_comparison_table,
        print_folder_structures,
        run_benchmark,
    )
    from tidyup.ollama_client import OllamaError

    if not shutil.which("ollama"):
        print(
            "Ollama is not installed.\n\n"
            "  Install:  brew install ollama\n"
            "  Start:    brew services start ollama"
        )
        return 1

    try:
        results = run_benchmark(config, models=models, runs=runs)
    except OllamaError as e:
        print(f"Error: {e}")
        return 1

    if not results:
        return 0

    print_comparison_table(results)
    print_agreement_matrix(results)
    print_folder_structures(results)
    return 0
