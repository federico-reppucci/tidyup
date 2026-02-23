"""CLI entry point: scan | review | undo | status."""

from __future__ import annotations

import argparse
import sys
import webbrowser

from tidydownloads.config import Config
from tidydownloads.logger_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tidydownloads",
        description="Local AI-powered download organizer",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug output"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Ollama model to use (e.g. llama3.1:8b, gemma2:9b)",
    )
    sub = parser.add_subparsers(dest="command")

    # scan
    scan_p = sub.add_parser("scan", help="Classify and stage files from Downloads")
    scan_p.add_argument(
        "--dry-run", action="store_true",
        help="Print classifications without moving files",
    )

    # review
    sub.add_parser("review", help="Start web UI to review staged files")

    # undo
    undo_p = sub.add_parser("undo", help="Reverse the last scan or review operation")
    undo_group = undo_p.add_mutually_exclusive_group()
    undo_group.add_argument(
        "--last-scan", action="store_true", help="Undo last scan staging"
    )
    undo_group.add_argument(
        "--last-review", action="store_true", help="Undo last review operation"
    )

    # status
    sub.add_parser("status", help="Check Ollama status and show last run stats")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    config = Config.load()
    if args.model:
        config.ollama_model = args.model
    setup_logging(config.log_dir, verbose=args.verbose)

    if args.command == "scan":
        return cmd_scan(config, dry_run=args.dry_run)
    elif args.command == "review":
        return cmd_review(config)
    elif args.command == "undo":
        op_filter = None
        if args.last_scan:
            op_filter = "scan"
        elif args.last_review:
            op_filter = "review"
        return cmd_undo(config, op_filter)
    elif args.command == "status":
        return cmd_status(config)

    return 0


def cmd_scan(config: Config, dry_run: bool = False) -> int:
    from tidydownloads.classifier import classify_files
    from tidydownloads.ollama_client import OllamaClient, OllamaError
    from tidydownloads.scanner import scan_downloads
    from tidydownloads.stager import check_stale_staging, stage_files
    from tidydownloads.taxonomy import discover_taxonomy

    print("TidyDownloads — Scanning...")

    # Check for stale staging folders
    warnings = check_stale_staging(config)
    if warnings:
        print("\nWarning: leftover files from previous run:")
        for w in warnings:
            print(w)
        print("  Run 'tidydownloads review' to handle them, or 'tidydownloads undo' to reverse.\n")

    # Ensure Ollama is running (unless dry-run could work without)
    if not dry_run:
        client = OllamaClient(config.ollama_url, config.ollama_model)
        try:
            client.ensure_running()
            if not client.is_model_available():
                answer = input(
                    f"Model '{config.ollama_model}' not found. Download it? [y/N] "
                ).strip().lower()
                if answer in ("y", "yes"):
                    print(f"Pulling {config.ollama_model}...")
                    client.pull_model()
                    print(f"Model '{config.ollama_model}' ready.\n")
                else:
                    print("Aborted.")
                    return 1
        except OllamaError as e:
            print(f"Error: {e}")
            return 1

    # Scan
    files = scan_downloads(config)
    if not files:
        print("No files to classify in Downloads.")
        return 0

    print(f"Found {len(files)} files to classify.\n")

    # Discover taxonomy
    taxonomy = discover_taxonomy(config.documents_dir)

    # Classify
    classifications = classify_files(files, taxonomy, config)

    # Stage
    print()
    result = stage_files(classifications, config, dry_run=dry_run)

    # Summary
    print(f"\nDone! Summary:")
    print(f"  Staged for deletion: {result['delete_count']}")
    print(f"  Staged for move:     {result['move_count']}")
    print(f"  Skipped (unsure):    {result['skip_count']}")

    if not dry_run and (result["delete_count"] or result["move_count"]):
        print(f"\nNext: run 'tidydownloads review' to review proposals.")

    return 0


def cmd_review(config: Config) -> int:
    from tidydownloads.web.server import create_app

    app, token = create_app(config)
    url = f"http://127.0.0.1:{config.web_port}/?token={token}"

    print(f"Starting review server...")
    print(f"  URL: {url}")
    print(f"  Press Ctrl+C to stop.\n")

    webbrowser.open(url)

    try:
        app.run(host="127.0.0.1", port=config.web_port, debug=False)
    except KeyboardInterrupt:
        print("\nServer stopped.")

    return 0


def cmd_undo(config: Config, operation_filter: str | None = None) -> int:
    from tidydownloads.journal import undo_last

    print("TidyDownloads — Undoing last operation...")

    result = undo_last(config.undo_log_path, operation_filter)

    if result.reversed_count == 0 and not result.failed:
        print("Nothing to undo.")
        return 0

    print(f"  Reversed {result.reversed_count} file moves (scan_id: {result.scan_id})")
    if result.failed:
        print(f"  Failed to reverse {len(result.failed)} moves:")
        for f in result.failed:
            print(f"    - {f}")
        return 1

    return 0


def cmd_status(config: Config) -> int:
    import json

    from tidydownloads.journal import get_entries
    from tidydownloads.ollama_client import OllamaClient

    print("TidyDownloads — Status\n")

    # Ollama status
    client = OllamaClient(config.ollama_url, config.ollama_model)
    if client.is_serving():
        print(f"  Ollama: running at {config.ollama_url}")
        if client.is_model_available():
            print(f"  Model:  {config.ollama_model} (available)")
        else:
            print(f"  Model:  {config.ollama_model} (NOT FOUND — run: ollama pull {config.ollama_model})")
    else:
        print(f"  Ollama: not running")

    # Last scan
    if config.proposals_path.exists():
        try:
            data = json.loads(config.proposals_path.read_text())
            proposals = data.get("proposals", [])
            print(f"\n  Last scan: {data.get('scan_id', 'unknown')}")
            print(f"  Proposals: {len(proposals)}")
            actions = {}
            for p in proposals:
                a = p.get("action", "unknown")
                actions[a] = actions.get(a, 0) + 1
            for action, count in sorted(actions.items()):
                print(f"    {action}: {count}")
        except (json.JSONDecodeError, OSError):
            pass
    else:
        print(f"\n  No previous scan found.")

    # Staging folders
    for folder in (config.staging_delete, config.staging_move):
        if folder.exists():
            count = sum(1 for f in folder.iterdir() if not f.name.startswith("."))
            print(f"  {folder.name}/: {count} files")

    # Journal
    entries = get_entries(config.undo_log_path)
    active = [e for e in entries if not e.undone]
    print(f"\n  Undo log: {len(active)} active entries, {len(entries) - len(active)} undone")

    return 0
