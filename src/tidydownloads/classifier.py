"""Two-tier classification: rule-based (Tier 1) + LLM (Tier 2) with pluggable backend."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol

from tidydownloads.apple_fm_client import AppleFMError
from tidydownloads.config import Config
from tidydownloads.content import extract_preview
from tidydownloads.helpers import (
    PREVIEW_CHARS,
    Classification,
    build_file_descriptions,
    parse_llm_response,
    precompute_previews,
    validate_destination,
)
from tidydownloads.ollama_client import (
    PER_FILE_TIMEOUT,
    OllamaClient,
    OllamaError,
    make_token_callback,
)
from tidydownloads.prompts import build_classification_prompt, build_subfolder_prompt
from tidydownloads.scanner import FileInfo
from tidydownloads.taxonomy import FolderInfo, Taxonomy

__all__ = [
    "PREVIEW_CHARS",
    "TIER1_CONFIDENCE",
    "TIER1_DELETE",
    "Classification",
    "ClassifierBackend",
    "OllamaBackend",
    "ParallelOllamaBackend",
    "RulesOnlyBackend",
    "classify_files",
    "classify_tier1",
    "refine_subfolders",
]

# Errors from any LLM client
_LLM_ERRORS = (OllamaError, AppleFMError)

log = logging.getLogger("tidydownloads")


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

        # Pre-compute content previews in parallel
        previews = precompute_previews(files)
        taxonomy_text = taxonomy.to_midsize_text()

        for batch_idx in range(0, len(files), config.batch_size):
            batch = files[batch_idx : batch_idx + config.batch_size]
            batch_num = batch_idx // config.batch_size + 1
            prefix = f"Classifying batch {batch_num}/{total_batches}..."
            on_token = make_token_callback(prefix)

            file_descriptions = build_file_descriptions(batch, previews)

            prompt = build_classification_prompt(
                taxonomy_text,
                file_descriptions,
                taxonomy=taxonomy,
            )

            batch_timeout = len(batch) * self.per_file_timeout

            try:
                response = self.client.generate(
                    prompt,
                    timeout=batch_timeout,
                    on_token=on_token,
                )
                print(f"\r  Classifying batch {batch_num}/{total_batches}... done")
                batch_results = parse_llm_response(response, batch)
                # Validate destinations against taxonomy
                for r in batch_results:
                    if r.action == "move" and r.destination:
                        r.destination = validate_destination(r.destination, taxonomy)
                results.extend(batch_results)
            except _LLM_ERRORS as e:
                is_timeout = "timed out" in str(e)
                print(
                    f"\r  Classifying batch {batch_num}/{total_batches}... "
                    f"{'TIMEOUT' if is_timeout else 'ERROR'}: {e}"
                )
                log.error("LLM error on batch %d: %s", batch_num, e)
                reason = (
                    f"LLM timeout ({batch_timeout}s per-file exceeded)"
                    if is_timeout
                    else f"LLM error: {e}"
                )
                for f in batch:
                    results.append(
                        Classification(
                            filename=f.name,
                            action="unsorted",
                            destination="",
                            reason=reason,
                            confidence=0.0,
                            method="llm",
                        )
                    )

        return results


class ParallelOllamaBackend:
    """Concurrent mini-batch classification using Ollama's parallel request support."""

    def __init__(
        self,
        client: OllamaClient,
        mini_batch: int = 5,
        workers: int = 4,
    ):
        self.client = client
        self.mini_batch = mini_batch
        self.workers = workers

    def classify(
        self, files: list[FileInfo], taxonomy: Taxonomy, config: Config
    ) -> list[Classification]:
        previews = precompute_previews(files)
        taxonomy_text = taxonomy.to_midsize_text()
        batches = [files[i : i + self.mini_batch] for i in range(0, len(files), self.mini_batch)]

        print(
            f"  Parallel: {len(batches)} mini-batches x{self.mini_batch} files, "
            f"{self.workers} workers"
        )

        results: list[Classification] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(
                    self._classify_batch,
                    b,
                    taxonomy_text,
                    taxonomy,
                    previews,
                    idx + 1,
                    len(batches),
                ): b
                for idx, b in enumerate(batches)
            }
            for fut in as_completed(futures):
                batch = futures[fut]
                try:
                    batch_results = fut.result()
                    results.extend(batch_results)
                except Exception as e:
                    log.error("Batch failed: %s", e)
                    for f in batch:
                        results.append(
                            Classification(f.name, "unsorted", "", f"batch error: {e}", 0.0, "llm")
                        )

        print(f"  Parallel: done, {len(results)} files classified")
        return results

    def _classify_batch(
        self,
        batch: list[FileInfo],
        taxonomy_text: str,
        taxonomy: Taxonomy,
        previews: dict[str, str],
        batch_num: int,
        total: int,
    ) -> list[Classification]:
        """Classify one mini-batch (runs in thread)."""
        file_descriptions = build_file_descriptions(batch, previews)
        prompt = build_classification_prompt(
            taxonomy_text,
            file_descriptions,
            taxonomy=taxonomy,
        )
        num_predict = len(batch) * 60 + 50
        batch_timeout = len(batch) * PER_FILE_TIMEOUT

        response = self.client.generate(
            prompt,
            timeout=batch_timeout,
            options={"num_predict": num_predict, "num_ctx": 4096, "top_k": 20},
            keep_alive="10m",
        )
        batch_results = parse_llm_response(response, batch)
        for r in batch_results:
            if r.action == "move" and r.destination:
                r.destination = validate_destination(r.destination, taxonomy)
        return batch_results


# --- Stage 2: Subfolder refinement (kept for backward compat) ---


def refine_subfolders(
    client: Any,  # OllamaClient or AppleFMClient — must have generate()
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

    NOTE: No longer called by OllamaBackend/TimedBackend (single-stage now).
    Kept for backward compatibility.
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
                    desc += f" — content preview: {preview[:PREVIEW_CHARS].replace(chr(10), ' ')}"
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
                on_token=(
                    (lambda n, _fi=folder_info: on_progress(f"Refining {_fi.name}/", n))  # type: ignore[misc]
                    if on_progress
                    else None
                ),
            )

            if on_progress:
                print(f"\r  Refining {folder_info.name}/... done")

            _apply_subfolder_response(response, folder_info, group)
        except _LLM_ERRORS as e:
            log.warning(
                "Stage 2 failed for %s: %s — keeping stage 1 destinations",
                folder_info.name,
                e,
            )
            if on_progress:
                print(f"\r  Refining {folder_info.name}/... skipped ({e})")
            # Keep stage 1 destination, just fix to actual folder name
            for r in group:
                r.destination = folder_info.name

    return results


def _apply_subfolder_response(
    response: dict,
    folder_info: FolderInfo,
    group: list[Classification],
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
                results.append(
                    Classification(
                        filename=f.name,
                        action="skip",
                        destination="",
                        reason="Cannot classify without LLM",
                        confidence=0.0,
                        method="rule",
                    )
                )
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
    skipped = 0
    for r in tier2_results:
        if r.confidence < config.confidence_threshold and r.action not in ("skip", "unsorted"):
            r.action = "unsorted"
            r.reason = f"Low confidence ({r.confidence:.2f}): {r.reason}"
            skipped += 1
        final.append(r)

    if skipped:
        print(f"  Confidence filter: {skipped} files below threshold → unsorted/")

    return final
