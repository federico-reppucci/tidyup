"""Tests for _check_ollama_setup() first-run experience logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tidydownloads.cli import _check_ollama_setup


# --- ollama not installed ---

def test_ollama_not_installed_returns_none(tmp_config, capsys):
    with patch("tidydownloads.cli.shutil.which", return_value=None):
        result = _check_ollama_setup(tmp_config)

    assert result is None
    out = capsys.readouterr().out
    assert "Ollama is not installed" in out
    assert "brew install ollama" in out


# --- ollama installed, server + model ready ---

def test_model_already_available_returns_backend(tmp_config):
    with (
        patch("tidydownloads.cli.shutil.which", return_value="/opt/homebrew/bin/ollama"),
        patch("tidydownloads.ollama_client.OllamaClient.ensure_running"),
        patch("tidydownloads.ollama_client.OllamaClient.is_model_available", return_value=True),
        patch("tidydownloads.ollama_client.OllamaClient.check_parallel_support", return_value=4),
    ):
        result = _check_ollama_setup(tmp_config)

    assert result is not None


# --- first run: auto-pull without prompt ---

def test_first_run_auto_pulls_model(tmp_config, capsys):
    """First run (no proposals.json) should auto-pull without [y/N] prompt."""
    assert not tmp_config.proposals_path.exists()  # first run

    with (
        patch("tidydownloads.cli.shutil.which", return_value="/opt/homebrew/bin/ollama"),
        patch("tidydownloads.ollama_client.OllamaClient.ensure_running"),
        patch("tidydownloads.ollama_client.OllamaClient.is_model_available", return_value=False),
        patch("tidydownloads.ollama_client.OllamaClient.pull_model") as mock_pull,
        patch("tidydownloads.ollama_client.OllamaClient.check_parallel_support", return_value=0),
    ):
        result = _check_ollama_setup(tmp_config)

    mock_pull.assert_called_once()
    assert result is not None
    out = capsys.readouterr().out
    assert "First-time setup" in out
    assert "downloading" in out


def test_first_run_pull_failure_returns_none(tmp_config, capsys):
    """If auto-pull fails on first run, return None."""
    from tidydownloads.ollama_client import OllamaError

    assert not tmp_config.proposals_path.exists()

    with (
        patch("tidydownloads.cli.shutil.which", return_value="/opt/homebrew/bin/ollama"),
        patch("tidydownloads.ollama_client.OllamaClient.ensure_running"),
        patch("tidydownloads.ollama_client.OllamaClient.is_model_available", return_value=False),
        patch("tidydownloads.ollama_client.OllamaClient.pull_model", side_effect=OllamaError("network error")),
    ):
        result = _check_ollama_setup(tmp_config)

    assert result is None
    assert "network error" in capsys.readouterr().out


# --- not first run: interactive prompt ---

def test_not_first_run_prompts_user_yes(tmp_config, capsys):
    """Existing user with missing model should get [y/N] prompt."""
    tmp_config.proposals_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_config.proposals_path.write_text('{"proposals": []}')

    with (
        patch("tidydownloads.cli.shutil.which", return_value="/opt/homebrew/bin/ollama"),
        patch("tidydownloads.ollama_client.OllamaClient.ensure_running"),
        patch("tidydownloads.ollama_client.OllamaClient.is_model_available", return_value=False),
        patch("tidydownloads.ollama_client.OllamaClient.pull_model") as mock_pull,
        patch("tidydownloads.ollama_client.OllamaClient.check_parallel_support", return_value=0),
        patch("builtins.input", return_value="y"),
    ):
        result = _check_ollama_setup(tmp_config)

    mock_pull.assert_called_once()
    assert result is not None


def test_not_first_run_prompts_user_no(tmp_config, capsys):
    """User declines download → returns None."""
    tmp_config.proposals_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_config.proposals_path.write_text('{"proposals": []}')

    with (
        patch("tidydownloads.cli.shutil.which", return_value="/opt/homebrew/bin/ollama"),
        patch("tidydownloads.ollama_client.OllamaClient.ensure_running"),
        patch("tidydownloads.ollama_client.OllamaClient.is_model_available", return_value=False),
        patch("builtins.input", return_value="n"),
    ):
        result = _check_ollama_setup(tmp_config)

    assert result is None
    assert "Aborted" in capsys.readouterr().out


# --- dry run ---

def test_dry_run_model_missing_warns(tmp_config, capsys):
    """Dry-run should warn but still return a backend."""
    with (
        patch("tidydownloads.cli.shutil.which", return_value="/opt/homebrew/bin/ollama"),
        patch("tidydownloads.ollama_client.OllamaClient.ensure_running"),
        patch("tidydownloads.ollama_client.OllamaClient.is_model_available", return_value=False),
        patch("tidydownloads.ollama_client.OllamaClient.check_parallel_support", return_value=0),
    ):
        result = _check_ollama_setup(tmp_config, dry_run=True)

    assert result is not None
    assert "Warning" in capsys.readouterr().out


# --- ensure_running fails ---

def test_ensure_running_fails_returns_none(tmp_config, capsys):
    from tidydownloads.ollama_client import OllamaError

    with (
        patch("tidydownloads.cli.shutil.which", return_value="/opt/homebrew/bin/ollama"),
        patch("tidydownloads.ollama_client.OllamaClient.ensure_running",
              side_effect=OllamaError("did not start within 10s")),
    ):
        result = _check_ollama_setup(tmp_config)

    assert result is None
    assert "did not start" in capsys.readouterr().out


# --- parallel tip ---

def test_first_run_shows_parallel_tip(tmp_config, capsys):
    """First run with NUM_PARALLEL unset should show the tip."""
    assert not tmp_config.proposals_path.exists()

    with (
        patch("tidydownloads.cli.shutil.which", return_value="/opt/homebrew/bin/ollama"),
        patch("tidydownloads.ollama_client.OllamaClient.ensure_running"),
        patch("tidydownloads.ollama_client.OllamaClient.is_model_available", return_value=True),
        patch("tidydownloads.ollama_client.OllamaClient.check_parallel_support", return_value=0),
    ):
        _check_ollama_setup(tmp_config)

    assert "OLLAMA_NUM_PARALLEL" in capsys.readouterr().out


def test_parallel_already_set_no_tip(tmp_config, capsys):
    """If NUM_PARALLEL is set, don't show the tip."""
    assert not tmp_config.proposals_path.exists()

    with (
        patch("tidydownloads.cli.shutil.which", return_value="/opt/homebrew/bin/ollama"),
        patch("tidydownloads.ollama_client.OllamaClient.ensure_running"),
        patch("tidydownloads.ollama_client.OllamaClient.is_model_available", return_value=True),
        patch("tidydownloads.ollama_client.OllamaClient.check_parallel_support", return_value=4),
    ):
        _check_ollama_setup(tmp_config)

    assert "OLLAMA_NUM_PARALLEL" not in capsys.readouterr().out
