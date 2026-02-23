"""Two-tier classification: rule-based (Tier 1) + LLM (Tier 2) with pluggable backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from tidydownloads.config import Config
from tidydownloads.content import extract_preview
from tidydownloads.ollama_client import OllamaClient, OllamaError
from tidydownloads.prompts import build_classification_prompt
from tidydownloads.scanner import FileInfo
from tidydownloads.taxonomy import Taxonomy

log = logging.getLogger("tidydownloads")


@dataclass
class Classification:
    filename: str
    action: str  # "move" | "delete" | "skip"
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

    def __init__(self, client: OllamaClient):
        self.client = client

    def classify(
        self, files: list[FileInfo], taxonomy: Taxonomy, config: Config
    ) -> list[Classification]:
        results: list[Classification] = []
        total_batches = (len(files) + config.batch_size - 1) // config.batch_size

        for batch_idx in range(0, len(files), config.batch_size):
            batch = files[batch_idx:batch_idx + config.batch_size]
            batch_num = batch_idx // config.batch_size + 1
            print(f"  Classifying batch {batch_num}/{total_batches}...")

            file_descriptions = []
            for f in batch:
                desc = f"{f.name} ({f.mime_type}, {f.size_human})"
                preview = extract_preview(f.path)
                if preview:
                    # Truncate preview for prompt space
                    preview_short = preview[:200].replace("\n", " ")
                    desc += f" — content preview: {preview_short}"
                file_descriptions.append(desc)

            prompt = build_classification_prompt(
                taxonomy.to_prompt_text(),
                file_descriptions,
            )

            try:
                response = self.client.generate(prompt)
                batch_results = _parse_llm_response(response, batch)
                results.extend(batch_results)
            except OllamaError as e:
                log.error("Ollama error on batch %d: %s", batch_num, e)
                # Skip this batch — files stay in Downloads
                for f in batch:
                    results.append(Classification(
                        filename=f.name,
                        action="skip",
                        destination="",
                        reason=f"LLM error: {e}",
                        confidence=0.0,
                        method="llm",
                    ))

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
        if r.confidence < config.confidence_threshold and r.action != "skip":
            r.action = "skip"
            r.reason = f"Low confidence ({r.confidence:.2f}): {r.reason}"
            skipped += 1
        else:
            if r.action != "skip":
                staged += 1
        final.append(r)

    if skipped:
        print(f"  Confidence filter: {skipped} files below threshold, staying in Downloads")

    return final
