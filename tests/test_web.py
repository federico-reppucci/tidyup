"""Tests for the Flask review web server."""

import json

import pytest

from tidydownloads.web.server import create_app


@pytest.fixture
def web_client(tmp_config):
    """Flask test client with valid token."""
    # Create a proposal
    tmp_config.staging_move.mkdir(parents=True, exist_ok=True)
    (tmp_config.staging_move / "report.pdf").write_bytes(b"pdf content")

    proposals = {
        "scan_id": "2026-01-01T00:00:00",
        "proposals": [
            {
                "filename": "report.pdf",
                "staged_path": str(tmp_config.staging_move / "report.pdf"),
                "original_path": str(tmp_config.downloads_dir / "report.pdf"),
                "action": "move",
                "destination": "03 Work/Reports",
                "reason": "Work report",
                "confidence": 0.85,
                "method": "llm",
            }
        ],
    }
    tmp_config.proposals_path.write_text(json.dumps(proposals))

    app, token = create_app(tmp_config)
    app.config["TESTING"] = True
    client = app.test_client()
    return client, token, tmp_config


def test_index_requires_token(web_client):
    client, token, _ = web_client
    resp = client.get("/")
    assert resp.status_code == 403


def test_index_with_valid_token(web_client):
    client, token, _ = web_client
    resp = client.get(f"/?token={token}")
    assert resp.status_code == 200


def test_get_proposals(web_client):
    client, token, _ = web_client
    resp = client.get(f"/api/proposals?token={token}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["filename"] == "report.pdf"


def test_accept_file(web_client):
    client, token, config = web_client
    resp = client.post(f"/api/accept/report.pdf?token={token}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "accepted"

    # File should be in Documents
    dest = config.documents_dir / "03 Work" / "Reports" / "report.pdf"
    assert dest.exists()

    # Staging should be empty
    assert not (config.staging_move / "report.pdf").exists()


def test_reject_file(web_client):
    client, token, config = web_client
    resp = client.post(f"/api/reject/report.pdf?token={token}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "rejected"

    # File should be back in Downloads
    assert (config.downloads_dir / "report.pdf").exists()


def test_accept_nonexistent_file(web_client):
    client, token, _ = web_client
    resp = client.post(f"/api/accept/nonexistent.pdf?token={token}")
    assert resp.status_code == 404


def test_reject_path_traversal(web_client):
    client, token, _ = web_client
    # Slashes in filename cause Flask 404 (route not matched) — that's safe.
    # Test with ".." in a flat filename to hit our validation.
    resp = client.post(f"/api/accept/..passwd?token={token}")
    assert resp.status_code == 400


def test_accept_all(web_client):
    client, token, config = web_client
    resp = client.post(f"/api/accept-all?token={token}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["accepted"] == 1

    dest = config.documents_dir / "03 Work" / "Reports" / "report.pdf"
    assert dest.exists()


# --- Unsorted proposals ---

@pytest.fixture
def web_client_with_unsorted(tmp_config):
    """Flask test client with move and unsorted proposals."""
    tmp_config.staging_move.mkdir(parents=True, exist_ok=True)
    tmp_config.staging_unsorted.mkdir(parents=True, exist_ok=True)
    (tmp_config.staging_move / "report.pdf").write_bytes(b"pdf content")
    (tmp_config.staging_unsorted / "mystery.bin").write_bytes(b"\x00")

    proposals = {
        "scan_id": "2026-01-01T00:00:00",
        "proposals": [
            {
                "filename": "report.pdf",
                "staged_path": str(tmp_config.staging_move / "report.pdf"),
                "original_path": str(tmp_config.downloads_dir / "report.pdf"),
                "action": "move",
                "destination": "03 Work/Reports",
                "reason": "Work report",
                "confidence": 0.85,
                "method": "llm",
            },
            {
                "filename": "mystery.bin",
                "staged_path": str(tmp_config.staging_unsorted / "mystery.bin"),
                "original_path": str(tmp_config.downloads_dir / "mystery.bin"),
                "action": "unsorted",
                "destination": "",
                "reason": "Low confidence (0.40): unknown file",
                "confidence": 0.4,
                "method": "llm",
            },
        ],
    }
    tmp_config.proposals_path.write_text(json.dumps(proposals))

    app, token = create_app(tmp_config)
    app.config["TESTING"] = True
    client = app.test_client()
    return client, token, tmp_config


def test_get_proposals_includes_unsorted(web_client_with_unsorted):
    client, token, _ = web_client_with_unsorted
    resp = client.get(f"/api/proposals?token={token}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 2
    actions = {d["action"] for d in data}
    assert actions == {"move", "unsorted"}


def test_accept_unsorted_blocked(web_client_with_unsorted):
    client, token, _ = web_client_with_unsorted
    resp = client.post(f"/api/accept/mystery.bin?token={token}")
    assert resp.status_code == 400


def test_reject_unsorted(web_client_with_unsorted):
    client, token, config = web_client_with_unsorted
    resp = client.post(f"/api/reject/mystery.bin?token={token}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "rejected"
    assert (config.downloads_dir / "mystery.bin").exists()


def test_accept_all_skips_unsorted(web_client_with_unsorted):
    client, token, config = web_client_with_unsorted
    resp = client.post(f"/api/accept-all?token={token}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["accepted"] == 1  # Only the move proposal

    # Unsorted file should still be in staging
    assert (config.staging_unsorted / "mystery.bin").exists()
