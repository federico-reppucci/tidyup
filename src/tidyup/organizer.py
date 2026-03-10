"""File organizer: LLM-based classification with duplicate detection."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from tidyup.apple_fm_client import AppleFMError
from tidyup.helpers import (
    NOT_CLASSIFIED_REASON,
    Proposal,
    build_file_descriptions,
    current_parent,
    parse_organize_response,
    precompute_previews,
    sha256_file,
)
from tidyup.ollama_client import OllamaClient, OllamaError, make_token_callback
from tidyup.progress import ProgressDisplay
from tidyup.prompts import build_organize_prompt, build_retry_prompt
from tidyup.scanner import FileInfo

__all__ = [
    "OllamaOrganizer",
    "ParallelOllamaOrganizer",
    "detect_duplicates",
]

_LLM_ERRORS = (OllamaError, AppleFMError)

log = logging.getLogger("tidyup")


def detect_duplicates(files: list[FileInfo]) -> tuple[list[Proposal], list[FileInfo]]:
    """Find duplicate files by content hash. Returns (trash_proposals, unique_files).

    Groups by size first (cheap pre-filter), then hashes same-size files.
    Keeps the oldest file (earliest modified_time) as the original.
    Skips directories (.app bundles).
    """
    trash: list[Proposal] = []

    by_size: dict[int, list[FileInfo]] = defaultdict(list)
    for f in files:
        if f.path.is_dir():
            continue
        by_size[f.size].append(f)

    dup_paths: set[str] = set()

    for size_group in by_size.values():
        if len(size_group) < 2:
            continue

        by_hash: dict[str, list[FileInfo]] = defaultdict(list)
        for f in size_group:
            try:
                h = sha256_file(f.path)
            except OSError:
                continue
            by_hash[h].append(f)

        for hash_group in by_hash.values():
            if len(hash_group) < 2:
                continue

            hash_group.sort(key=lambda f: f.modified_time)
            original = hash_group[0]
            for dup in hash_group[1:]:
                dup_paths.add(dup.relative_path)
                trash.append(
                    Proposal(
                        relative_path=dup.relative_path,
                        destination_folder="Trash",
                        reason=f"Duplicate of {original.relative_path}",
                        needs_move=True,
                    )
                )

    unique = [f for f in files if f.relative_path not in dup_paths]
    return trash, unique


class OllamaOrganizer:
    """Single LLM call organizer for all files."""

    def __init__(self, client: OllamaClient):
        self.client = client

    def _call_llm(
        self,
        files: list[FileInfo],
        previews: dict[str, str],
        prompt_builder: Callable[[list[str]], str],
        label: str = "Organizing...",
        on_token: Callable[[int], None] | None = None,
        quiet: bool = False,
    ) -> list[Proposal]:
        """Make a single LLM call and parse the response."""
        file_descriptions = build_file_descriptions(files, previews)
        prompt = prompt_builder(file_descriptions)

        num_predict = len(files) * 60 + 200
        num_ctx = max(4096, len(prompt) // 4 + num_predict + 512)
        timeout = max(120, len(files) * 20)

        token_cb = on_token or make_token_callback(label)
        result = self.client.generate(
            prompt,
            timeout=timeout,
            on_token=token_cb,
            options={"num_predict": num_predict, "num_ctx": num_ctx},
            keep_alive="10m",
        )
        if not quiet:
            print(f"\r  {label} done ({len(files)} files)")
        return parse_organize_response(result.data, files)

    def organize(
        self, files: list[FileInfo], progress: ProgressDisplay | None = None
    ) -> list[Proposal]:
        if not files:
            return []

        if progress:
            progress.phase(3, "Extracting previews")
        previews = precompute_previews(files)
        if progress:
            progress.finish_phase(f"{len(previews)} files")

        if progress:
            progress.phase(4, "Organizing via LLM")
            on_token = progress.make_token_callback()
        else:
            on_token = None

        try:
            proposals = self._call_llm(
                files,
                previews,
                build_organize_prompt,
                on_token=on_token,
                quiet=progress is not None,
            )
        except _LLM_ERRORS as e:
            if progress:
                progress.finish_phase(f"ERROR: {e}")
            else:
                print(f"\r  Organizing... ERROR: {e}")
            log.error("LLM error: %s", e)
            return [
                Proposal(
                    relative_path=f.relative_path,
                    destination_folder=current_parent(f.relative_path),
                    reason=f"LLM error: {e}",
                    needs_move=False,
                )
                for f in files
            ]

        # Retry once for files the LLM missed
        proposals = self._retry_unclassified(files, previews, proposals, progress)

        if progress:
            classified = sum(1 for p in proposals if p.reason != NOT_CLASSIFIED_REASON)
            progress.finish_phase(f"{classified}/{len(files)} files classified")

        return proposals

    def _retry_unclassified(
        self,
        files: list[FileInfo],
        previews: dict[str, str],
        proposals: list[Proposal],
        progress: ProgressDisplay | None = None,
    ) -> list[Proposal]:
        """If any files were not classified, retry once with a focused prompt."""
        unclassified = [p for p in proposals if p.reason == NOT_CLASSIFIED_REASON]
        if not unclassified:
            return proposals

        unclassified_paths = {p.relative_path for p in unclassified}
        retry_files = [f for f in files if f.relative_path in unclassified_paths]
        log.info("Retrying %d unclassified files", len(retry_files))

        if progress:
            on_token = progress.make_token_callback()
            progress.update(f"retrying {len(retry_files)} missed files")
        else:
            on_token = None

        try:
            retry_proposals = self._call_llm(
                retry_files,
                previews,
                build_retry_prompt,
                label="Retrying missed files...",
                on_token=on_token,
                quiet=progress is not None,
            )
        except _LLM_ERRORS as e:
            log.warning("Retry LLM call failed: %s", e)
            return proposals

        # Merge: replace unclassified proposals with retry results
        retry_map = {p.relative_path: p for p in retry_proposals}
        merged = []
        for p in proposals:
            if p.relative_path in retry_map and p.reason == NOT_CLASSIFIED_REASON:
                merged.append(retry_map[p.relative_path])
            else:
                merged.append(p)
        return merged


class ParallelOllamaOrganizer:
    """Parallel organizer that splits files into batches for 80+ files."""

    def __init__(
        self,
        client: OllamaClient,
        batch_size: int = 40,
        workers: int = 4,
    ):
        self.client = client
        self.batch_size = batch_size
        self.workers = workers

    def organize(
        self, files: list[FileInfo], progress: ProgressDisplay | None = None
    ) -> list[Proposal]:
        if not files:
            return []

        # For small file counts, use single call
        if len(files) < 80:
            return OllamaOrganizer(self.client).organize(files, progress=progress)

        if progress:
            progress.phase(3, "Extracting previews")
        previews = precompute_previews(files)
        if progress:
            progress.finish_phase(f"{len(previews)} files")

        batches = [files[i : i + self.batch_size] for i in range(0, len(files), self.batch_size)]

        if progress:
            progress.phase(4, "Organizing via LLM")
            progress.setup_parallel(len(batches))
        else:
            print(
                f"  Parallel: {len(batches)} batches x{self.batch_size} files,"
                f" {self.workers} workers"
            )

        results: list[Proposal] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(self._organize_batch, b, previews, idx + 1, len(batches), progress): b
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
                            Proposal(
                                relative_path=f.relative_path,
                                destination_folder="",
                                reason=f"batch error: {e}",
                                needs_move=False,
                            )
                        )

        if progress:
            classified = sum(1 for p in results if p.reason != NOT_CLASSIFIED_REASON)
            progress.finish_phase(f"{classified}/{len(files)} files classified")
        else:
            print(f"  Parallel: done, {len(results)} files organized")
        return results

    def _organize_batch(
        self,
        batch: list[FileInfo],
        previews: dict[str, str],
        batch_num: int,
        total: int,
        progress: ProgressDisplay | None = None,
    ) -> list[Proposal]:
        """Organize one batch (runs in thread)."""
        on_token = progress.make_token_callback(batch_num) if progress else None
        quiet = progress is not None

        single = OllamaOrganizer(self.client)
        proposals = single._call_llm(
            batch, previews, build_organize_prompt, on_token=on_token, quiet=quiet
        )
        proposals = single._retry_unclassified(batch, previews, proposals)

        if progress:
            progress.batch_done(batch_num)
        return proposals
