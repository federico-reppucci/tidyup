"""Flask review server with token authentication."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request

from tidydownloads.config import Config
from tidydownloads.journal import JournalEntry, record_move
from tidydownloads.mover import MoveError, move_file_safely

__all__ = ["create_app"]


def create_app(config: Config) -> tuple[Flask, str]:
    """Create the Flask app and return (app, auth_token)."""
    token = secrets.token_urlsafe(32)

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["config"] = config
    app.config["auth_token"] = token

    def check_token():
        t = request.args.get("token") or request.headers.get("X-Auth-Token")
        if t != token:
            abort(403, "Invalid or missing token")

    def _load_proposals() -> list[dict]:
        proposals_path = config.proposals_path
        if not proposals_path.exists():
            return []
        try:
            data = json.loads(proposals_path.read_text())
            return data.get("proposals", [])  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return []

    def _save_proposals(proposals: list[dict]) -> None:
        existing = {}
        if config.proposals_path.exists():
            try:
                existing = json.loads(config.proposals_path.read_text())
            except (json.JSONDecodeError, OSError):
                existing = {}
        existing["proposals"] = proposals
        config.proposals_path.write_text(json.dumps(existing, indent=2))

    @app.route("/")
    def index():
        check_token()
        return render_template("review.html", token=token)

    @app.route("/api/proposals")
    def get_proposals():
        check_token()
        proposals = _load_proposals()
        # Filter to actionable proposals (move + unsorted)
        active = []
        for p in proposals:
            if p.get("action") not in ("move", "unsorted"):
                continue
            staged = Path(p["staged_path"])
            p["exists"] = staged.exists()
            active.append(p)
        return jsonify(active)

    @app.route("/api/accept/<filename>", methods=["POST"])
    def accept_file(filename: str):
        check_token()
        _validate_filename(filename)

        proposals = _load_proposals()
        proposal = _find_proposal(proposals, filename)
        if not proposal:
            abort(404, "Proposal not found")

        staged_path = Path(proposal["staged_path"])
        if not staged_path.exists():
            abort(404, "File not found in staging")

        if proposal.get("action") == "unsorted":
            abort(400, "Cannot accept unsorted file — no destination assigned")

        dest_dir = config.documents_dir / proposal["destination"]
        scan_id = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

        try:
            final_path = move_file_safely(staged_path, dest_dir)
        except MoveError as e:
            abort(400, str(e))

        if final_path:
            record_move(
                JournalEntry(
                    timestamp=scan_id,
                    operation="review_accept",
                    source=str(staged_path),
                    destination=str(final_path),
                    scan_id=scan_id,
                ),
                config.undo_log_path,
            )

        # Remove from proposals
        proposals = [p for p in proposals if p["filename"] != filename]
        _save_proposals(proposals)

        return jsonify({"status": "accepted", "destination": str(final_path)})

    @app.route("/api/accept-all", methods=["POST"])
    def accept_all():
        check_token()
        proposals = _load_proposals()
        scan_id = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        accepted = 0
        errors: list[str] = []

        remaining = []
        for p in proposals:
            if p.get("action") != "move":
                remaining.append(p)
                continue

            staged_path = Path(p["staged_path"])
            if not staged_path.exists():
                errors.append(f"{p['filename']}: file not found")
                continue

            dest_dir = config.documents_dir / p["destination"]
            try:
                final_path = move_file_safely(staged_path, dest_dir)
                if final_path:
                    record_move(
                        JournalEntry(
                            timestamp=scan_id,
                            operation="review_accept",
                            source=str(staged_path),
                            destination=str(final_path),
                            scan_id=scan_id,
                        ),
                        config.undo_log_path,
                    )
                    accepted += 1
            except MoveError as e:
                errors.append(f"{p['filename']}: {e}")
                remaining.append(p)

        _save_proposals(remaining)
        return jsonify({"accepted": accepted, "errors": errors})

    @app.route("/api/reject/<filename>", methods=["POST"])
    def reject_file(filename: str):
        check_token()
        _validate_filename(filename)

        proposals = _load_proposals()
        proposal = _find_proposal(proposals, filename)
        if not proposal:
            abort(404, "Proposal not found")

        staged_path = Path(proposal["staged_path"])
        if not staged_path.exists():
            abort(404, "File not found in staging")

        # Move back to Downloads root
        original = Path(proposal["original_path"])
        scan_id = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

        try:
            final_path = move_file_safely(staged_path, original.parent)
        except MoveError as e:
            abort(400, str(e))

        if final_path:
            record_move(
                JournalEntry(
                    timestamp=scan_id,
                    operation="review_reject",
                    source=str(staged_path),
                    destination=str(final_path),
                    scan_id=scan_id,
                ),
                config.undo_log_path,
            )

        proposals = [p for p in proposals if p["filename"] != filename]
        _save_proposals(proposals)

        return jsonify({"status": "rejected", "returned_to": str(final_path)})

    return app, token


def _validate_filename(filename: str) -> None:
    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400, "Invalid filename")


def _find_proposal(proposals: list[dict], filename: str) -> dict | None:
    for p in proposals:
        if p["filename"] == filename:
            return p
    return None
