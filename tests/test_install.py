"""Tests for the Finder Quick Action installer."""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import patch

import pytest

from tidyup.install import (
    WORKFLOW_NAME,
    _build_shell_script,
    _find_tidyup_path,
    install_quick_action,
    uninstall_quick_action,
)


@pytest.fixture
def fake_services_dir(tmp_path: Path):
    """Redirect SERVICES_DIR to a temp directory."""
    services = tmp_path / "Library" / "Services"
    services.mkdir(parents=True)
    with patch("tidyup.install.SERVICES_DIR", services):
        yield services


class TestFindTidyupPath:
    def test_finds_via_which(self):
        with patch("shutil.which", return_value="/usr/local/bin/tidyup"):
            assert _find_tidyup_path() == "/usr/local/bin/tidyup"

    def test_fallback_to_python_bin_dir(self, tmp_path: Path):
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        (fake_bin / "tidyup").touch()
        with (
            patch("shutil.which", return_value=None),
            patch("sys.executable", str(fake_bin / "python3")),
        ):
            result = _find_tidyup_path()
            assert "tidyup" in result

    def test_raises_if_not_found(self, tmp_path: Path):
        with (
            patch("shutil.which", return_value=None),
            patch("sys.executable", str(tmp_path / "python3")),
            pytest.raises(FileNotFoundError, match="Cannot find"),
        ):
            _find_tidyup_path()


class TestBuildShellScript:
    def test_contains_tidyup_path(self):
        script = _build_shell_script("/usr/local/bin/tidyup")
        assert "/usr/local/bin/tidyup" in script
        assert "quoted form of" in script

    def test_handles_folder_detection(self):
        script = _build_shell_script("/usr/local/bin/tidyup")
        assert '[ ! -d "$folder" ]' in script
        assert "dirname" in script

    def test_uses_osascript_for_terminal(self):
        script = _build_shell_script("/usr/local/bin/tidyup")
        assert "osascript" in script
        assert "Terminal" in script


class TestInstallQuickAction:
    def test_creates_workflow_bundle(self, fake_services_dir: Path):
        with patch("tidyup.install._find_tidyup_path", return_value="/usr/local/bin/tidyup"):
            path = install_quick_action()

        assert path == fake_services_dir / WORKFLOW_NAME
        assert path.is_dir()
        assert (path / "Contents" / "Resources" / "document.wflow").exists()
        assert (path / "Contents" / "Info.plist").exists()
        assert (path / "Contents" / "Resources" / "en.lproj" / "ServicesMenu.strings").exists()

    def test_document_wflow_is_valid_plist(self, fake_services_dir: Path):
        with patch("tidyup.install._find_tidyup_path", return_value="/usr/local/bin/tidyup"):
            path = install_quick_action()

        with open(path / "Contents" / "Resources" / "document.wflow", "rb") as f:
            data = plistlib.load(f)

        assert data["workflowMetaData"]["workflowTypeIdentifier"] == (
            "com.apple.Automator.servicesMenu"
        )
        assert data["workflowMetaData"]["serviceInputTypeIdentifier"] == (
            "com.apple.Automator.fileSystemObject"
        )
        assert len(data["actions"]) == 1

        action = data["actions"][0]["action"]
        assert action["ActionName"] == "Run Shell Script"
        assert "/usr/local/bin/tidyup" in action["ActionParameters"]["COMMAND_STRING"]
        assert action["ActionParameters"]["inputMethod"] == 1
        assert action["ActionParameters"]["shell"] == "/bin/zsh"

    def test_info_plist_has_nsservices(self, fake_services_dir: Path):
        with patch("tidyup.install._find_tidyup_path", return_value="/usr/local/bin/tidyup"):
            path = install_quick_action()

        with open(path / "Contents" / "Info.plist", "rb") as f:
            data = plistlib.load(f)

        assert data["CFBundleName"] == "tidyup"
        # NSServices is required for pbs to register the Quick Action
        assert "NSServices" in data
        service = data["NSServices"][0]
        assert service["NSMenuItem"]["default"] == "tidyup"
        assert service["NSMessage"] == "runWorkflowAsService"
        assert "public.folder" in service["NSSendFileTypes"]

    def test_overwrites_existing_workflow(self, fake_services_dir: Path):
        with patch("tidyup.install._find_tidyup_path", return_value="/usr/local/bin/tidyup"):
            install_quick_action()
            # Install again — should overwrite without error
            path = install_quick_action()

        assert path.is_dir()
        assert (path / "Contents" / "Resources" / "document.wflow").exists()

    def test_propagates_not_found_error(self, fake_services_dir: Path):
        with (
            patch("tidyup.install._find_tidyup_path", side_effect=FileNotFoundError("not found")),
            pytest.raises(FileNotFoundError),
        ):
            install_quick_action()


class TestUninstallQuickAction:
    def test_removes_existing_workflow(self, fake_services_dir: Path):
        with patch("tidyup.install._find_tidyup_path", return_value="/usr/local/bin/tidyup"):
            install_quick_action()

        with patch("tidyup.install.SERVICES_DIR", fake_services_dir):
            assert uninstall_quick_action() is True

        assert not (fake_services_dir / WORKFLOW_NAME).exists()

    def test_returns_false_if_not_installed(self, fake_services_dir: Path):
        assert uninstall_quick_action() is False


class TestCliIntegration:
    def test_install_command(self, fake_services_dir: Path):
        from tidyup.cli import main

        with patch("tidyup.install._find_tidyup_path", return_value="/usr/local/bin/tidyup"):
            result = main(["install"])

        assert result == 0
        assert (fake_services_dir / WORKFLOW_NAME).is_dir()

    def test_uninstall_command(self, fake_services_dir: Path):
        from tidyup.cli import main

        with patch("tidyup.install._find_tidyup_path", return_value="/usr/local/bin/tidyup"):
            main(["install"])
            result = main(["uninstall"])

        assert result == 0
        assert not (fake_services_dir / WORKFLOW_NAME).exists()

    def test_install_when_binary_not_found(self, fake_services_dir: Path, capsys):
        from tidyup.cli import main

        with (
            patch("shutil.which", return_value=None),
            patch("sys.executable", "/nonexistent/python3"),
        ):
            result = main(["install"])

        assert result == 1
        assert "Cannot find" in capsys.readouterr().out
