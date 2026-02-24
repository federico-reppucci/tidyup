"""Two-tier classification: rule-based (Tier 1) + LLM (Tier 2) with pluggable backend."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from tidydownloads.config import Config
from tidydownloads.content import extract_preview
from tidydownloads.ollama_client import (
    OllamaClient,
    OllamaError,
    PER_FILE_TIMEOUT,
    SPINNER,
    make_token_callback,
)
from tidydownloads.prompts import build_classification_prompt, build_subfolder_prompt
from tidydownloads.scanner import FileInfo
from tidydownloads.taxonomy import FolderInfo, Taxonomy

log = logging.getLogger("tidydownloads")


@dataclass
class Classification:
    filename: str
    action: str  # "move" | "delete" | "unsorted" | "skip"
    destination: str  # Documents subfolder path (only for "move")
    reason: str
    confidence: float
    method: str  # "rule" | "llm"


# --- Tier 1: Rule-based classification ---

TIER1_DELETE: dict[str, str] = {
    ".dmg": "macOS disk image installer",
    ".pkg": "macOS package installer",
    ".torrent": "torrent metadata file",
    ".crdownload": "incomplete Chrome download",
    ".part": "incomplete download",
    ".download": "incomplete Safari download",
}

TIER1_CONFIDENCE: dict[str, float] = {
    ".dmg": 0.95,
    ".pkg": 0.95,
    ".torrent": 0.90,
    ".crdownload": 0.95,
    ".part": 0.95,
    ".download": 0.95,
}


def classify_tier1(file_info: FileInfo) -> Classification | None:
    """Rule-based classification by extension. Returns None if ambiguous."""
    ext = file_info.extension
    if ext in TIER1_DELETE:
        return Classification(
            filename=file_info.name,
            action="delete",
            destination="",
            reason=TIER1_DELETE[ext],
            confidence=TIER1_CONFIDENCE[ext],
            method="rule",
        )
    return None


# --- Pluggable backend protocol ---

class ClassifierBackend(Protocol):
    def classify(
        self, files: list[FileInfo], taxonomy: Taxonomy, config: Config
    ) -> list[Classification]: ...


# --- Tier 2: Ollama LLM backend ---

class OllamaBackend:
    """Uses local Ollama instance for classification."""

    def __init__(self, client: OllamaClient, per_file_timeout: int = PER_FILE_TIMEOUT):
        self.client = client
        self.per_file_timeout = per_file_timeout

    def classify(
        self, files: list[FileInfo], taxonomy: Taxonomy, config: Config
    ) -> list[Classification]:
        results: list[Classification] = []
        total_batches = (len(files) + config.batch_size - 1) // config.batch_size

        for batch_idx in range(0, len(files), config.batch_size):
            batch = files[batch_idx:batch_idx + config.batch_size]
            batch_num = batch_idx // config.batch_size + 1
            prefix = f"Classifying batch {batch_num}/{total_batches}..."
            on_token = make_token_callback(prefix)

            file_descriptions = []
            for f in batch:
                desc = f"{f.name} ({f.mime_type}, {f.size_human})"
                preview = extract_preview(f.path)
                if preview:
                    preview_short = preview[:200].replace("\n", " ")
                    desc += f" — content preview: {preview_short}"
                file_descriptions.append(desc)

            prompt = build_classification_prompt(
                taxonomy.to_compact_text(),
                file_descriptions,
            )

            batch_timeout = len(batch) * self.per_file_timeout

            try:
                response = self.client.generate(
                    prompt, timeout=batch_timeout, on_token=on_token,
                )
                print(f"\r  Classifying batch {batch_num}/{total_batches}... done")
                batch_results = _parse_llm_response(response, batch)
                results.extend(batch_results)
            except OllamaError as e:
                is_timeout = "timed out" in str(e)
                print(f"\r  Classifying batch {batch_num}/{total_batches}... {'TIMEOUT' if is_timeout else 'ERROR'}: {e}")
                log.error("Ollama error on batch %d: %s", batch_num, e)
                reason = (
                    f"LLM timeout ({batch_timeout}s per-file exceeded)"
                    if is_timeout
                    else f"LLM error: {e}"
                )
                for f in batch:
                    results.append(Classification(
                        filename=f.name,
                        action="unsorted",
                        destination="",
                        reason=reason,
                        confidence=0.0,
                        method="llm",
                    ))

        # Stage 2: refine subfolder assignments
        file_info_map = {f.name: f for f in files}
        print("  Stage 2: refining subfolder assignments...")

        def _stage2_progress(prefix: str, n: int) -> None:
            msg = f"\r  {prefix} {SPINNER[n % len(SPINNER)]} {n} tokens" if n else f"\r  {prefix}"
            print(msg, end="", flush=True)

        results = refine_subfolders(
            self.client, results, taxonomy, file_info_map,
            per_file_timeout=self.per_file_timeout,
            on_progress=_stage2_progress,
        )

        return results


def _parse_llm_response(
    response: dict, batch: list[FileInfo]
) -> list[Classification]:
    """Parse LLM JSON response into Classification objects."""
    results: list[Classification] = []
    batch_names = {f.name for f in batch}

    items = response.get("files", [])
    if not isinstance(items, list):
        log.warning("LLM returned non-list 'files' field")
        return [
            Classification(f.name, "skip", "", "LLM returned invalid format", 0.0, "llm")
            for f in batch
        ]

    seen: set[str] = set()
    for item in items:
        filename = item.get("file", "")
        if filename not in batch_names or filename in seen:
            continue
        seen.add(filename)

        action = item.get("action", "")
        if action not in ("move", "delete"):
            action = "skip"

        destination = item.get("destination", "") if action == "move" else ""
        reason = item.get("reason", "")
        try:
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        results.append(Classification(
            filename=filename,
            action=action,
            destination=destination,
            reason=reason,
            confidence=confidence,
            method="llm",
        ))

    # Any files not in the response get skipped
    for f in batch:
        if f.name not in seen:
            results.append(Classification(
                filename=f.name,
                action="skip",
                destination="",
                reason="Not classified by LLM",
                confidence=0.0,
                method="llm",
            ))

    return results


# --- Stage 2: Subfolder refinement ---

def refine_subfolders(
    client: OllamaClient,
    results: list[Classification],
    taxonomy: Taxonomy,
    file_info_map: dict[str, FileInfo],
    per_file_timeout: int = PER_FILE_TIMEOUT,
    on_progress: Callable[[str, int], None] | None = None,
) -> list[Classification]:
    """Refine stage 1 'move' classifications by picking the correct subfolder.

    Groups files by their top-level destination folder, then for each folder
    that has subfolders, asks the LLM to pick the best subfolder.

    If stage 2 fails for a group, the stage 1 destination is kept unchanged.
    """
    # Group "move" results by top-level folder
    groups: dict[str, list[Classification]] = defaultdict(list)
    for r in results:
        if r.action == "move" and r.destination:
            top_folder = r.destination.split("/")[0]
            groups[top_folder].append(r)

    if not groups:
        return results

    for folder_name, group in groups.items():
        folder_info = taxonomy.find_folder(folder_name)
        if not folder_info or not folder_info.subfolders:
            # No subfolders to refine — update destination to actual folder name
            for r in group:
                if folder_info:
                    r.destination = folder_info.name
            continue

        # Build file descriptions for this group
        file_descriptions: list[str] = []
        for r in group:
            fi = file_info_map.get(r.filename)
            if fi:
                desc = f"{fi.name} ({fi.mime_type}, {fi.size_human})"
                preview = extract_preview(fi.path)
                if preview:
                    desc += f" — content preview: {preview[:200].replace(chr(10), ' ')}"
                file_descriptions.append(desc)
            else:
                file_descriptions.append(r.filename)

        prompt = build_subfolder_prompt(
            folder_info.name,
            folder_info.subfolders,
            file_descriptions,
        )

        batch_timeout = len(group) * per_file_timeout

        try:
            if on_progress:
                on_progress(f"Refining {folder_info.name}/", 0)

            response = client.generate(
                prompt,
                timeout=batch_timeout,
                on_token=on_progress and (lambda n: on_progress(f"Refining {folder_info.name}/", n)),
            )

            if on_progress:
                print(f"\r  Refining {folder_info.name}/... done")

            _apply_subfolder_response(response, folder_info, group)
        except OllamaError as e:
            log.warning("Stage 2 failed for %s: %s — keeping stage 1 destinations", folder_info.name, e)
            if on_progress:
                print(f"\r  Refining {folder_info.name}/... skipped ({e})")
            # Keep stage 1 destination, just fix to actual folder name
            for r in group:
                r.destination = folder_info.name

    return results


def _apply_subfolder_response(
    response: dict, folder_info: FolderInfo, group: list[Classification],
) -> None:
    """Parse stage 2 response and update classification destinations."""
    items = response.get("files", [])
    if not isinstance(items, list):
        log.warning("Stage 2 returned non-list for %s", folder_info.name)
        for r in group:
            r.destination = folder_info.name
        return

    # Build a lookup: lowercase subfolder name → actual subfolder name
    sub_lookup: dict[str, str] = {s.lower(): s for s in folder_info.subfolders}

    subfolder_map: dict[str, str] = {}
    for item in items:
        filename = item.get("file", "")
        subfolder = item.get("subfolder", "")
        if filename and subfolder:
            subfolder_map[filename] = subfolder

    for r in group:
        chosen = subfolder_map.get(r.filename, "")
        if chosen:
            # Fuzzy match to actual subfolder name
            actual_sub = sub_lookup.get(chosen.lower())
            if not actual_sub:
                # Try partial match
                for key, val in sub_lookup.items():
                    if chosen.lower() in key or key in chosen.lower():
                        actual_sub = val
                        break
            if actual_sub:
                r.destination = f"{folder_info.name}/{actual_sub}"
            else:
                log.debug("Stage 2 subfolder '%s' not found in %s", chosen, folder_info.name)
                r.destination = folder_info.name
        else:
            # No subfolder assigned — keep top-level
            r.destination = folder_info.name


# --- Rules-only fallback backend ---

class RulesOnlyBackend:
    """Extension-based rules only. No LLM. Fast but less accurate."""

    def classify(
        self, files: list[FileInfo], taxonomy: Taxonomy, config: Config
    ) -> list[Classification]:
        results: list[Classification] = []
        for f in files:
            result = classify_tier1(f)
            if result:
                results.append(result)
            else:
                results.append(Classification(
                    filename=f.name,
                    action="skip",
                    destination="",
                    reason="Cannot classify without LLM",
                    confidence=0.0,
                    method="rule",
                ))
        return results


# --- Main classify function ---

def classify_files(
    files: list[FileInfo],
    taxonomy: Taxonomy,
    config: Config,
    backend: ClassifierBackend | None = None,
) -> list[Classification]:
    """Classify files using Tier 1 rules, then Tier 2 LLM for the rest."""
    tier1_results: list[Classification] = []
    tier2_files: list[FileInfo] = []

    for f in files:
        result = classify_tier1(f)
        if result:
            tier1_results.append(result)
        else:
            tier2_files.append(f)

    if tier1_results:
        print(f"  Tier 1 (rules): {len(tier1_results)} files classified")

    if not tier2_files:
        return tier1_results

    print(f"  Tier 2 (LLM): {len(tier2_files)} files to classify...")

    if backend is None:
        client = OllamaClient(config.ollama_url, config.ollama_model)
        backend = OllamaBackend(client)

    tier2_results = backend.classify(tier2_files, taxonomy, config)

    # Apply confidence threshold
    final: list[Classification] = list(tier1_results)
    staged = 0
    skipped = 0
    for r in tier2_results:
        if r.confidence < config.confidence_threshold and r.action not in ("skip", "unsorted"):
            r.action = "unsorted"
            r.reason = f"Low confidence ({r.confidence:.2f}): {r.reason}"
            skipped += 1
        else:
            if r.action != "skip":
                staged += 1
        final.append(r)

    if skipped:
        print(f"  Confidence filter: {skipped} files below threshold → unsorted/")

    return final
