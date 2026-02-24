"""Stage classified files into to_delete/, to_move/, and unsorted/ folders."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from tidydownloads.classifier import Classification
from tidydownloads.config import Config
from tidydownloads.journal import JournalEntry, record_move
from tidydownloads.mover import move_file_safely

log = logging.getLogger("tidydownloads")


def check_stale_staging(config: Config) -> list[str]:
    """Check if staging folders have leftover files from a previous run."""
    warnings: list[str] = []
    for folder in (config.staging_delete, config.staging_move, config.staging_unsorted):
        if folder.exists():
            leftover = [
                f.name for f in folder.iterdir()
                if not f.name.startswith(".")
            ]
            if leftover:
                warnings.append(
                    f"  {folder.name}/ has {len(leftover)} leftover files from a previous run"
                )
    return warnings


def stage_files(
    classifications: list[Classification],
    config: Config,
    dry_run: bool = False,
) -> dict:
    """Move classified files to staging folders and write proposals.json."""
    scan_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    proposals: list[dict] = []

    delete_count = 0
    move_count = 0
    unsorted_count = 0
    skip_count = 0

    for cls in classifications:
        source = config.downloads_dir / cls.filename
        if not source.exists():
            log.warning("File disappeared during staging: %s", cls.filename)
            continue

        if cls.action == "delete":
            if dry_run:
                print(f"  [DRY RUN] Would stage for deletion: {cls.filename} — {cls.reason}")
                delete_count += 1
                continue

            dest = move_file_safely(source, config.staging_delete)
            if dest:
                delete_count += 1
                proposals.append({
                    "filename": cls.filename,
                    "staged_path": str(dest),
                    "original_path": str(source),
                    "action": "delete",
                    "destination": "",
                    "reason": cls.reason,
                    "confidence": cls.confidence,
                    "method": cls.method,
                })
                record_move(
                    JournalEntry(
                        timestamp=scan_id,
                        operation="scan_stage",
                        source=str(source),
                        destination=str(dest),
                        scan_id=scan_id,
                    ),
                    config.undo_log_path,
                )

        elif cls.action == "move":
            if dry_run:
                print(
                    f"  [DRY RUN] Would stage for move: {cls.filename} "
                    f"→ Documents/{cls.destination} — {cls.reason}"
                )
                move_count += 1
                continue

            dest = move_file_safely(source, config.staging_move)
            if dest:
                move_count += 1
                proposals.append({
                    "filename": cls.filename,
                    "staged_path": str(dest),
                    "original_path": str(source),
                    "action": "move",
                    "destination": cls.destination,
                    "reason": cls.reason,
                    "confidence": cls.confidence,
                    "method": cls.method,
                })
                record_move(
                    JournalEntry(
                        timestamp=scan_id,
                        operation="scan_stage",
                        source=str(source),
                        destination=str(dest),
                        scan_id=scan_id,
                    ),
                    config.undo_log_path,
                )

        elif cls.action == "unsorted":
            if dry_run:
                print(f"  [DRY RUN] Would stage as unsorted: {cls.filename} — {cls.reason}")
                unsorted_count += 1
                continue

            dest = move_file_safely(source, config.staging_unsorted)
            if dest:
                unsorted_count += 1
                proposals.append({
                    "filename": cls.filename,
                    "staged_path": str(dest),
                    "original_path": str(source),
                    "action": "unsorted",
                    "destination": "",
                    "reason": cls.reason,
                    "confidence": cls.confidence,
                    "method": cls.method,
                })
                record_move(
                    JournalEntry(
                        timestamp=scan_id,
                        operation="scan_stage",
                        source=str(source),
                        destination=str(dest),
                        scan_id=scan_id,
                    ),
                    config.undo_log_path,
                )

        else:
            skip_count += 1

    # Write proposals.json
    if not dry_run and proposals:
        manifest = {"scan_id": scan_id, "proposals": proposals}
        config.data_dir.mkdir(parents=True, exist_ok=True)
        config.proposals_path.write_text(json.dumps(manifest, indent=2))

    return {
        "scan_id": scan_id,
        "delete_count": delete_count,
        "move_count": move_count,
        "unsorted_count": unsorted_count,
        "skip_count": skip_count,
        "total": len(classifications),
    }
