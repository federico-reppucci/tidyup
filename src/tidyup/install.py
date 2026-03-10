"""Install / uninstall the macOS Finder Quick Action for TidyUp."""

from __future__ import annotations

import plistlib
import shutil
import sys
from pathlib import Path

SERVICES_DIR = Path.home() / "Library" / "Services"
WORKFLOW_NAME = "TidyUp.workflow"


def _find_tidyup_path() -> str:
    """Return the absolute path to the tidyup binary."""
    path = shutil.which("tidyup")
    if path:
        return str(Path(path).resolve())
    # Fallback: look in the same bin dir as the running Python
    candidate = Path(sys.executable).parent / "tidyup"
    if candidate.exists():
        return str(candidate.resolve())
    raise FileNotFoundError(
        "Cannot find the 'tidyup' binary on PATH. "
        "Make sure tidyup is installed (pip install tidyup)."
    )


def _build_shell_script(tidyup_path: str) -> str:
    """Build the shell script that the Quick Action executes.

    Accepts a file or folder path as $1. If a file is passed, its parent
    directory is used. Opens Terminal.app and runs ``tidyup scan <folder>``.
    """
    return (
        'folder="$1"\n'
        '[ ! -d "$folder" ] && folder="$(dirname "$folder")"\n'
        "osascript \\\n"
        "  -e 'on run argv' \\\n"
        "  -e '  set folderPath to item 1 of argv' \\\n"
        "  -e '  tell application \"Terminal\"' \\\n"
        "  -e '    activate' \\\n"
        f'  -e \'    do script quoted form of "{tidyup_path}"'
        f' & " scan " & quoted form of folderPath\' \\\n'
        "  -e '  end tell' \\\n"
        "  -e 'end run' \\\n"
        '  -- "$folder"\n'
    )


def _build_document_wflow(shell_script: str) -> dict:
    """Build the document.wflow plist structure for a Quick Action."""
    return {
        "AMApplicationBuild": "523",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [
            {
                "action": {
                    "AMAccepts": {
                        "Container": "List",
                        "Optional": True,
                        "Types": ["com.apple.cocoa.path"],
                    },
                    "AMActionVersion": "1.0.2",
                    "AMApplication": ["Automator"],
                    "AMCategory": "AMCategoryUtilities",
                    "AMIconName": "Terminal",
                    "AMName": "Run Shell Script",
                    "AMProvides": {
                        "Container": "List",
                        "Types": ["com.apple.cocoa.path"],
                    },
                    "AMRequiredResources": [],
                    "ActionBundlePath": ("/System/Library/Automator/Run Shell Script.action"),
                    "ActionName": "Run Shell Script",
                    "ActionParameters": {
                        "COMMAND_STRING": shell_script,
                        "CheckedForUserDefaultShell": True,
                        "inputMethod": 1,  # 1 = pass input as arguments
                        "shell": "/bin/zsh",
                        "source": "",
                    },
                    "BundleIdentifier": "com.apple.RunShellScript",
                    "CFBundleVersion": "1.0.2",
                    "CanShowSelectedItemsWhenRun": False,
                    "CanShowWhenRun": True,
                    "Category": ["AMCategoryUtilities"],
                    "Class Name": "RunShellScriptAction",
                    "InputUUID": "A19E1DB3-25F3-47E0-B9B9-2E1B45B2CFB6",
                    "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
                    "OutputUUID": "67283654-D9F3-4014-B18C-E609D5531F59",
                    "UUID": "F14FF24F-65C4-46E4-A498-5043B8B7A263",
                    "UnlocalizedApplications": ["Automator"],
                    "arguments": {
                        "0": {
                            "default value": 1,
                            "name": "inputMethod",
                            "required": "0",
                            "type": "0",
                            "uuid": "0",
                        },
                        "1": {
                            "default value": "",
                            "name": "source",
                            "required": "0",
                            "type": "0",
                            "uuid": "1",
                        },
                        "2": {
                            "default value": "/bin/zsh",
                            "name": "shell",
                            "required": "0",
                            "type": "0",
                            "uuid": "2",
                        },
                        "3": {
                            "default value": "",
                            "name": "COMMAND_STRING",
                            "required": "0",
                            "type": "0",
                            "uuid": "3",
                        },
                        "4": {
                            "default value": True,
                            "name": "CheckedForUserDefaultShell",
                            "required": "0",
                            "type": "0",
                            "uuid": "4",
                        },
                    },
                    "isViewVisible": True,
                    "location": "449.500000:620.000000",
                    "nibPath": (
                        "/System/Library/Automator/Run Shell Script.action"
                        "/Contents/Resources/Base.lproj/main.nib"
                    ),
                },
            },
        ],
        "connectors": {},
        "workflowMetaData": {
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


def _build_info_plist() -> dict:
    """Build the Info.plist for the workflow bundle.

    The NSServices entry is what registers the workflow as a macOS service
    (Quick Action) with the pasteboard server.
    """
    return {
        "CFBundleDevelopmentRegion": "en_US",
        "CFBundleIdentifier": "com.tidyup.finder-action",
        "CFBundleName": "TidyUp",
        "CFBundleShortVersionString": "1.0",
        "NSServices": [
            {
                "NSMenuItem": {"default": "TidyUp"},
                "NSMessage": "runWorkflowAsService",
                "NSSendFileTypes": [
                    "public.folder",
                    "public.item",
                ],
            },
        ],
    }


def install_quick_action() -> Path:
    """Create and install the TidyUp Quick Action to ~/Library/Services/.

    The bundle structure mirrors Apple's system workflows:
      TidyUp.workflow/Contents/
        Info.plist              (with NSServices for pbs registration)
        Resources/
          document.wflow        (the Automator workflow definition)
          en.lproj/
            ServicesMenu.strings (localized menu item title)

    Returns the path to the installed workflow bundle.
    Raises FileNotFoundError if the tidyup binary cannot be found.
    """
    tidyup_path = _find_tidyup_path()
    shell_script = _build_shell_script(tidyup_path)
    document_wflow = _build_document_wflow(shell_script)
    info_plist = _build_info_plist()

    bundle_path = SERVICES_DIR / WORKFLOW_NAME
    contents_dir = bundle_path / "Contents"
    resources_dir = contents_dir / "Resources"
    en_lproj = resources_dir / "en.lproj"

    # Remove existing workflow if present
    if bundle_path.exists():
        shutil.rmtree(bundle_path)

    en_lproj.mkdir(parents=True)

    # document.wflow goes in Resources/ (matching Apple's system workflows)
    with open(resources_dir / "document.wflow", "wb") as f:
        plistlib.dump(document_wflow, f)

    with open(contents_dir / "Info.plist", "wb") as f:
        plistlib.dump(info_plist, f)

    # ServicesMenu.strings — localized menu title
    services_strings = {"default": "TidyUp"}
    with open(en_lproj / "ServicesMenu.strings", "wb") as f:
        plistlib.dump(services_strings, f)

    return bundle_path


def uninstall_quick_action() -> bool:
    """Remove the TidyUp Quick Action from ~/Library/Services/.

    Returns True if the workflow was found and removed, False if it didn't exist.
    """
    bundle_path = SERVICES_DIR / WORKFLOW_NAME
    if not bundle_path.exists():
        return False
    shutil.rmtree(bundle_path)
    return True
