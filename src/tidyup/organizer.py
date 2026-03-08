"""File organizer: LLM-based classification with duplicate detection."""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from tidyup.apple_fm_client import AppleFMError
from tidyup.helpers import (
    Proposal,
    build_file_descriptions,
    parse_organize_response,
    precompute_previews,
    sha256_file,
)
from tidyup.ollama_client import OllamaClient, OllamaError, make_token_callback
from tidyup.prompts import build_organize_prompt
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

    def organize(self, files: list[FileInfo]) -> list[Proposal]:
        if not files:
            return []

        previews = precompute_previews(files)
        file_descriptions = build_file_descriptions(files, previews)
        prompt = build_organize_prompt(file_descriptions)

        num_predict = len(files) * 60 + 200
        # Estimate prompt tokens (~4 chars/token) + output tokens + headroom
        num_ctx = max(4096, len(prompt) // 4 + num_predict + 512)
        timeout = max(60, len(files) * 20)

        on_token = make_token_callback("Organizing...")

        try:
            result = self.client.generate(
                prompt,
                timeout=timeout,
                on_token=on_token,
                options={"num_predict": num_predict, "num_ctx": num_ctx},
                keep_alive="10m",
            )
            print(f"\r  Organizing... done ({len(files)} files)")
            return parse_organize_response(result.data, files)
        except _LLM_ERRORS as e:
            print(f"\r  Organizing... ERROR: {e}")
            log.error("LLM error: %s", e)
            # On error, all files stay in place
            return [
                Proposal(
                    relative_path=f.relative_path,
                    destination_folder=str(
                        f.path.parent.relative_to(f.path.parent)
                        if f.path.parent == f.path.parent
                        else ""
                    ),
                    reason=f"LLM error: {e}",
                    needs_move=False,
                )
                for f in files
            ]


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

    def organize(self, files: list[FileInfo]) -> list[Proposal]:
        if not files:
            return []

        # For small file counts, use single call
        if len(files) < 80:
            return OllamaOrganizer(self.client).organize(files)

        previews = precompute_previews(files)
        batches = [files[i : i + self.batch_size] for i in range(0, len(files), self.batch_size)]

        print(
            f"  Parallel: {len(batches)} batches x{self.batch_size} files, {self.workers} workers"
        )

        results: list[Proposal] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(self._organize_batch, b, previews, idx + 1, len(batches)): b
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

        print(f"  Parallel: done, {len(results)} files organized")
        return results

    def _organize_batch(
        self,
        batch: list[FileInfo],
        previews: dict[str, str],
        batch_num: int,
        total: int,
    ) -> list[Proposal]:
        """Organize one batch (runs in thread)."""
        file_descriptions = build_file_descriptions(batch, previews)
        prompt = build_organize_prompt(file_descriptions)

        num_predict = len(batch) * 60 + 200
        num_ctx = max(4096, len(prompt) // 4 + num_predict + 512)
        timeout = max(60, len(batch) * 20)

        result = self.client.generate(
            prompt,
            timeout=timeout,
            options={"num_predict": num_predict, "num_ctx": num_ctx},
            keep_alive="10m",
        )
        return parse_organize_response(result.data, batch)
