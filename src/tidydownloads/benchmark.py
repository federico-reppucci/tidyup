"""Benchmark: compare Ollama models on the same set of files.

Uses the file's real Documents path as ground truth for accuracy.
"""

from __future__ import annotations

import json
import logging
import random
import shutil
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("tidydownloads")

from tidydownloads.apple_fm_client import AppleFMClient, AppleFMError
from concurrent.futures import ThreadPoolExecutor, as_completed

from tidydownloads.classifier import (
    Classification,
    PREVIEW_CHARS,
    _build_file_descriptions,
    _precompute_previews,
    _validate_destination,
    classify_files,
    _parse_llm_response,
)
from tidydownloads.config import Config
from tidydownloads.ollama_client import (
    OllamaClient,
    OllamaError,
    PER_FILE_TIMEOUT,
    SPINNER,
)
from tidydownloads.prompts import build_classification_prompt
from tidydownloads.scanner import FileInfo, scan_downloads
from tidydownloads.taxonomy import Taxonomy, discover_taxonomy

_LLM_ERRORS = (OllamaError, AppleFMError)


@dataclass
class BenchResult:
    model: str
    classifications: list[Classification] = field(default_factory=list)
    batch_times: list[float] = field(default_factory=list)
    batch_sizes: list[int] = field(default_factory=list)
    prompt_lengths: list[int] = field(default_factory=list)
    total_llm_time: float = 0.0
    stage2_time: float = 0.0
    scan_time: float = 0.0
    taxonomy_time: float = 0.0
    classify_time: float = 0.0
    total_time: float = 0.0


class TimedBackend:
    """LLM backend that records per-batch timing."""

    def __init__(
        self, client: Any, result: BenchResult,
        per_file_timeout: int = PER_FILE_TIMEOUT,
    ):
        self.client = client
        self.r = result
        self.per_file_timeout = per_file_timeout

    def classify(
        self, files: list[FileInfo], taxonomy: Taxonomy, config: Config
    ) -> list[Classification]:
        results: list[Classification] = []
        total_batches = (len(files) + config.batch_size - 1) // config.batch_size

        # Pre-compute content previews in parallel
        previews = _precompute_previews(files)

        for batch_idx in range(0, len(files), config.batch_size):
            batch = files[batch_idx : batch_idx + config.batch_size]
            batch_num = batch_idx // config.batch_size + 1
            label = f"Batch {batch_num}/{total_batches}..."

            t0 = time.perf_counter()

            def on_token(n: int, _label: str = label, _t0: float = t0) -> None:
                elapsed = time.perf_counter() - _t0
                frame = SPINNER[n % len(SPINNER)]
                print(
                    f"\r    {_label} {frame} {n} tokens ({elapsed:.1f}s)",
                    end="", flush=True,
                )

            file_descriptions = _build_file_descriptions(batch, previews)

            taxonomy_text = taxonomy.to_midsize_text()
            prompt = build_classification_prompt(
                taxonomy_text, file_descriptions, taxonomy=taxonomy,
            )
            self.r.prompt_lengths.append(len(prompt))

            batch_timeout = len(batch) * self.per_file_timeout

            try:
                response = self.client.generate(
                    prompt, timeout=batch_timeout, on_token=on_token,
                )
                elapsed = time.perf_counter() - t0
                self.r.batch_times.append(elapsed)
                self.r.batch_sizes.append(len(batch))
                self.r.total_llm_time += elapsed
                print(f"\r    {label} {elapsed:.1f}s ({len(batch)/elapsed:.1f} f/s)")
                batch_results = _parse_llm_response(response, batch)
                # Validate destinations against taxonomy
                for r in batch_results:
                    if r.action == "move" and r.destination:
                        r.destination = _validate_destination(r.destination, taxonomy)
                results.extend(batch_results)
            except _LLM_ERRORS as e:
                elapsed = time.perf_counter() - t0
                self.r.batch_times.append(elapsed)
                self.r.batch_sizes.append(len(batch))
                self.r.total_llm_time += elapsed
                is_timeout = "timed out" in str(e)
                print(f"\r    {label} {'TIMEOUT' if is_timeout else 'ERROR'} {elapsed:.1f}s: {e}")
                reason = (
                    f"LLM timeout ({batch_timeout}s per-file exceeded)"
                    if is_timeout
                    else f"LLM error: {e}"
                )
                for f in batch:
                    results.append(
                        Classification(f.name, "unsorted", "", reason, 0.0, "llm")
                    )

        return results


class ParallelTimedBackend:
    """Parallel mini-batch LLM backend with timing."""

    def __init__(
        self,
        client: Any,
        result: BenchResult,
        mini_batch: int = 5,
        workers: int = 4,
        per_file_timeout: int = PER_FILE_TIMEOUT,
    ):
        self.client = client
        self.r = result
        self.mini_batch = mini_batch
        self.workers = workers
        self.per_file_timeout = per_file_timeout

    def classify(
        self, files: list[FileInfo], taxonomy: Taxonomy, config: Config,
    ) -> list[Classification]:
        previews = _precompute_previews(files)
        taxonomy_text = taxonomy.to_midsize_text()
        batches = [
            files[i : i + self.mini_batch]
            for i in range(0, len(files), self.mini_batch)
        ]

        print(
            f"    Parallel: {len(batches)} mini-batches × {self.mini_batch} files, "
            f"{self.workers} workers"
        )

        results: list[Classification] = []
        t_wall_start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(
                    self._classify_batch, b, taxonomy_text, taxonomy, previews,
                    idx + 1, len(batches),
                ): b
                for idx, b in enumerate(batches)
            }
            for fut in as_completed(futures):
                batch = futures[fut]
                try:
                    batch_results, elapsed = fut.result()
                    self.r.batch_times.append(elapsed)
                    self.r.batch_sizes.append(len(batch))
                    self.r.total_llm_time += elapsed
                    results.extend(batch_results)
                    print(
                        f"    Batch done: {len(batch)} files in {elapsed:.1f}s "
                        f"({len(batch)/elapsed:.1f} f/s)"
                    )
                except Exception as e:
                    log.error("Batch failed: %s", e)
                    for f in batch:
                        results.append(
                            Classification(f.name, "unsorted", "", f"batch error: {e}", 0.0, "llm")
                        )

        wall_time = time.perf_counter() - t_wall_start
        print(
            f"    Parallel wall time: {wall_time:.1f}s "
            f"({len(files)/wall_time:.1f} files/s)"
        )

        return results

    def _classify_batch(
        self,
        batch: list[FileInfo],
        taxonomy_text: str,
        taxonomy: Taxonomy,
        previews: dict[str, str],
        batch_num: int,
        total: int,
    ) -> tuple[list[Classification], float]:
        """Classify one mini-batch (runs in thread). Returns (results, elapsed)."""
        t0 = time.perf_counter()

        file_descriptions = _build_file_descriptions(batch, previews)
        prompt = build_classification_prompt(
            taxonomy_text, file_descriptions, taxonomy=taxonomy,
        )
        self.r.prompt_lengths.append(len(prompt))

        num_predict = len(batch) * 60 + 50
        batch_timeout = len(batch) * self.per_file_timeout

        response = self.client.generate(
            prompt, timeout=batch_timeout,
            options={"num_predict": num_predict, "num_ctx": 4096, "top_k": 20},
            keep_alive="10m",
        )

        batch_results = _parse_llm_response(response, batch)
        for r in batch_results:
            if r.action == "move" and r.destination:
                r.destination = _validate_destination(r.destination, taxonomy)

        elapsed = time.perf_counter() - t0
        return batch_results, elapsed


# ── Helpers ─────────────────────────────────────────────────

def collect_files(docs_dir: Path, target: int, seed: int) -> list[tuple[Path, str]]:
    """Return (source_path, relative_parent) tuples. Fixed seed for reproducibility."""
    candidates = [
        f for f in docs_dir.rglob("*")
        if f.is_file()
        and not f.name.startswith(".")
        and 0 < f.stat().st_size < 50_000_000
    ]
    rng = random.Random(seed)
    rng.shuffle(candidates)

    seen: set[str] = set()
    selected: list[tuple[Path, str]] = []
    for f in candidates:
        if f.name in seen:
            continue
        seen.add(f.name)
        rel_parent = str(f.parent.relative_to(docs_dir))
        selected.append((f, rel_parent))
        if len(selected) >= target:
            break
    return selected


def copy_files(files: list[tuple[Path, str]], dest: Path) -> list[Path]:
    copied: list[Path] = []
    for src, _ in files:
        tgt = dest / src.name
        if not tgt.exists():
            shutil.copy2(src, tgt)
            copied.append(tgt)
    return copied


def cleanup(paths: list[Path]) -> None:
    for p in paths:
        if p.exists():
            p.unlink()


def fmt_size(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def accuracy_score(
    classifications: list[Classification],
    ground_truth: dict[str, str],  # filename → relative parent in Documents
) -> dict:
    """Compare model destinations against actual file locations."""
    exact = 0
    top_match = 0  # top-level folder matches
    wrong = 0
    not_moved = 0  # delete / unsorted / skip
    total = len(classifications)

    details: list[dict] = []

    for c in classifications:
        actual = ground_truth.get(c.filename, "")
        if c.action != "move":
            not_moved += 1
            details.append({
                "file": c.filename, "action": c.action,
                "predicted": "", "actual": actual, "match": "n/a",
            })
            continue

        predicted = c.destination.rstrip("/")
        actual_clean = actual.rstrip("/")

        if predicted == actual_clean:
            exact += 1
            details.append({
                "file": c.filename, "action": "move",
                "predicted": predicted, "actual": actual_clean, "match": "exact",
            })
        elif predicted.split("/")[0] == actual_clean.split("/")[0]:
            top_match += 1
            details.append({
                "file": c.filename, "action": "move",
                "predicted": predicted, "actual": actual_clean, "match": "top-folder",
            })
        else:
            wrong += 1
            details.append({
                "file": c.filename, "action": "move",
                "predicted": predicted, "actual": actual_clean, "match": "wrong",
            })

    moved = exact + top_match + wrong
    return {
        "exact": exact,
        "top_match": top_match,
        "wrong": wrong,
        "not_moved": not_moved,
        "moved": moved,
        "total": total,
        "exact_pct": exact / moved * 100 if moved else 0,
        "top_pct": (exact + top_match) / moved * 100 if moved else 0,
        "details": details,
    }


def run_model(
    model: str, files: list[FileInfo], taxonomy: Taxonomy, config: Config,
    per_file_timeout: int = PER_FILE_TIMEOUT,
    parallel: bool = False,
) -> BenchResult:
    """Run classification for one model and return metrics."""
    label = f"{model} (parallel)" if parallel else model
    result = BenchResult(model=label)

    if model == "apple":
        client: Any = AppleFMClient()
        print(f"  Checking Apple FM availability...", end=" ", flush=True)
        if not client.is_available():
            raise AppleFMError(
                "Apple Foundation Model not available. "
                "Requires macOS 26+ with Apple Intelligence and afm-cli installed."
            )
        print("ok")
        parallel = False  # Apple FM doesn't support parallel
    else:
        config.ollama_model = model
        client = OllamaClient(config.ollama_url, model)
        print(f"  Ensuring {model} is ready...", end=" ", flush=True)
        client.ensure_running()
        if not client.is_model_available():
            print(f"pulling...", end=" ", flush=True)
            client.pull_model()
        print("ok")

        if parallel:
            num_parallel = client.check_parallel_support()
            if not num_parallel:
                print(
                    "  Tip: For best parallel performance, set "
                    "OLLAMA_NUM_PARALLEL=4 before starting Ollama"
                )

    if parallel:
        backend: Any = ParallelTimedBackend(
            client, result,
            mini_batch=config.mini_batch_size,
            workers=config.parallel_requests,
            per_file_timeout=per_file_timeout,
        )
    else:
        backend = TimedBackend(client, result, per_file_timeout=per_file_timeout)

    t0 = time.perf_counter()
    result.classifications = classify_files(files, taxonomy, config, backend=backend)
    result.classify_time = time.perf_counter() - t0
    result.total_time = result.classify_time

    return result


# ── Reporting ───────────────────────────────────────────────

def print_comparison(results: list[BenchResult], ground_truth: dict[str, str]) -> None:
    labels = [r.model for r in results]
    w = max(len(l) for l in labels) + 2  # column width

    print(f"\n{'='*70}")
    print(f"  HEAD-TO-HEAD COMPARISON")
    print(f"{'='*70}\n")

    # ── Speed ──
    print(f"  {'SPEED':<30s}", end="")
    for l in labels:
        print(f" {l:>{w}s}", end="")
    print()
    print(f"  {'-'*30}", end="")
    for _ in labels:
        print(f" {'-'*w}", end="")
    print()

    rows = [
        ("Total time", [f"{r.total_time:.1f}s" for r in results]),
        ("LLM time", [f"{r.total_llm_time:.1f}s" for r in results]),
        ("Files/sec (overall)", [f"{len(r.classifications)/r.total_time:.2f}" for r in results]),
        ("Files/sec (LLM only)", [f"{sum(1 for c in r.classifications if c.method=='llm')/r.total_llm_time:.2f}" if r.total_llm_time else "n/a" for r in results]),
        ("Avg batch time", [f"{statistics.mean(r.batch_times):.1f}s" if r.batch_times else "n/a" for r in results]),
        ("Speedup vs first", [f"{results[0].total_time/r.total_time:.1f}x" for r in results]),
    ]
    for label, vals in rows:
        print(f"  {label:<30s}", end="")
        for v in vals:
            print(f" {v:>{w}s}", end="")
        print()

    # ── Accuracy ──
    accuracies = [accuracy_score(r.classifications, ground_truth) for r in results]

    print()
    print(f"  {'ACCURACY':<30s}", end="")
    for l in labels:
        print(f" {l:>{w}s}", end="")
    print()
    print(f"  {'-'*30}", end="")
    for _ in labels:
        print(f" {'-'*w}", end="")
    print()

    acc_rows = [
        ("Files moved", [str(a["moved"]) for a in accuracies]),
        ("Exact path match", [f"{a['exact']} ({a['exact_pct']:.0f}%)" for a in accuracies]),
        ("Top-folder match", [f"{a['exact']+a['top_match']} ({a['top_pct']:.0f}%)" for a in accuracies]),
        ("Wrong destination", [str(a["wrong"]) for a in accuracies]),
        ("Not moved", [str(a["not_moved"]) for a in accuracies]),
    ]
    for label, vals in acc_rows:
        print(f"  {label:<30s}", end="")
        for v in vals:
            print(f" {v:>{w}s}", end="")
        print()

    # ── Action distribution ──
    print()
    print(f"  {'ACTION DISTRIBUTION':<30s}", end="")
    for l in labels:
        print(f" {l:>{w}s}", end="")
    print()
    print(f"  {'-'*30}", end="")
    for _ in labels:
        print(f" {'-'*w}", end="")
    print()

    for action in ("move", "delete", "unsorted", "skip"):
        vals = []
        for r in results:
            cnt = sum(1 for c in r.classifications if c.action == action)
            pct = cnt / len(r.classifications) * 100
            vals.append(f"{cnt} ({pct:.0f}%)")
        print(f"  {action:<30s}", end="")
        for v in vals:
            print(f" {v:>{w}s}", end="")
        print()

    # ── Confidence ──
    print()
    print(f"  {'CONFIDENCE (LLM files)':<30s}", end="")
    for l in labels:
        print(f" {l:>{w}s}", end="")
    print()
    print(f"  {'-'*30}", end="")
    for _ in labels:
        print(f" {'-'*w}", end="")
    print()

    for stat_name, fn in [("Mean", statistics.mean), ("Median", statistics.median)]:
        vals = []
        for r in results:
            confs = [c.confidence for c in r.classifications if c.method == "llm"]
            vals.append(f"{fn(confs):.3f}" if confs else "n/a")
        print(f"  {stat_name:<30s}", end="")
        for v in vals:
            print(f" {v:>{w}s}", end="")
        print()

    # ── Disagreements ──
    if len(results) == 2:
        a_cls = {c.filename: c for c in results[0].classifications}
        b_cls = {c.filename: c for c in results[1].classifications}

        disagree_action = []
        disagree_dest = []
        for fname in a_cls:
            if fname not in b_cls:
                continue
            ca, cb = a_cls[fname], b_cls[fname]
            if ca.action != cb.action:
                disagree_action.append((fname, ca, cb))
            elif ca.action == "move" and cb.action == "move" and ca.destination != cb.destination:
                disagree_dest.append((fname, ca, cb))

        print(f"\n  MODEL DISAGREEMENTS")
        print(f"  {'-'*66}")
        print(f"  Action disagreements: {len(disagree_action)}")
        print(f"  Destination disagreements (both move): {len(disagree_dest)}")

        if disagree_action:
            print(f"\n  Action Disagreements (showing first 15):")
            print(f"    {'File':<35s} {labels[0]:>12s} {labels[1]:>12s}")
            for fname, ca, cb in disagree_action[:15]:
                print(f"    {fname:<35s} {ca.action:>12s} {cb.action:>12s}")

        if disagree_dest:
            print(f"\n  Destination Disagreements (showing first 15):")
            print(f"    {'File':<30s} {'Actual':<20s} {labels[0]:<20s} {labels[1]:<20s}")
            for fname, ca, cb in disagree_dest[:15]:
                actual = ground_truth.get(fname, "?")
                act_short = actual[:19]
                a_short = ca.destination[:19]
                b_short = cb.destination[:19]
                print(f"    {fname:<30s} {act_short:<20s} {a_short:<20s} {b_short:<20s}")

    # ── Accuracy detail: wrong destinations ──
    for r, acc in zip(results, accuracies):
        wrongs = [d for d in acc["details"] if d["match"] == "wrong"]
        if wrongs:
            print(f"\n  WRONG DESTINATIONS — {r.model} (showing first 15):")
            print(f"    {'File':<30s} {'Predicted':<20s} {'Actual':<20s}")
            for d in wrongs[:15]:
                print(f"    {d['file']:<30s} {d['predicted'][:19]:<20s} {d['actual'][:19]:<20s}")

    print(f"\n{'='*70}")


# ── Entry point ─────────────────────────────────────────────

def run_benchmark(
    config: Config, models: list[str], num_files: int, seed: int,
    per_file_timeout: int = PER_FILE_TIMEOUT,
    parallel: bool = True,
) -> int:
    """Run the benchmark and return an exit code."""
    mode = "parallel" if parallel else "sequential"
    print(f"{'='*70}")
    print(f"  TidyDownloads — Model Comparison Benchmark")
    print(f"  Models: {' vs '.join(models)}")
    print(f"  Files: {num_files}  |  Seed: {seed}  |  Batch size: {config.batch_size}"
          f"  |  Timeout: {per_file_timeout}s/file  |  Mode: {mode}")
    print(f"{'='*70}\n")

    # ── Collect & copy ──
    print(f"[1/4] Collecting files from Documents (seed={seed})...")
    source_files = collect_files(config.documents_dir, num_files, seed)
    if len(source_files) < num_files:
        print(f"  Warning: only found {len(source_files)} unique files")

    ground_truth = {src.name: rel for src, rel in source_files}
    total_size = sum(src.stat().st_size for src, _ in source_files)

    ext_counts: dict[str, int] = {}
    for src, _ in source_files:
        ext = src.suffix.lower() or "(none)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
    top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:10]

    print(f"  {len(source_files)} files ({fmt_size(total_size)})")
    print(f"  Extensions: {', '.join(f'{e}({c})' for e, c in top_exts)}")

    print(f"\n[2/4] Copying to Downloads...")
    copied = copy_files(source_files, config.downloads_dir)
    print(f"  Copied {len(copied)} files")

    try:
        # ── Scan & taxonomy (shared, once) ──
        files = scan_downloads(config)
        copied_names = {f.name for f in copied}
        files = [f for f in files if f.name in copied_names]
        taxonomy = discover_taxonomy(config.documents_dir)
        print(f"  Scanned {len(files)} files, {len(taxonomy.folders)} taxonomy folders")

        # ── Run each model ──
        all_results: list[BenchResult] = []
        for i, model in enumerate(models):
            print(f"\n[3/4] Running model {i+1}/{len(models)}: {model}")
            result = run_model(
                model, files, taxonomy, config,
                per_file_timeout=per_file_timeout, parallel=parallel,
            )
            all_results.append(result)
            print(f"  → {result.total_time:.1f}s total, "
                  f"{len(result.classifications)/result.total_time:.2f} files/s")

        # ── Compare ──
        print(f"\n[4/4] Generating comparison...")
        print_comparison(all_results, ground_truth)

        # ── Save raw results ──
        out_path = config.data_dir / "benchmark_results.json"
        raw = []
        for r in all_results:
            raw.append({
                "model": r.model,
                "total_time": round(r.total_time, 2),
                "llm_time": round(r.total_llm_time, 2),
                "stage2_time": round(r.stage2_time, 2),
                "files": len(r.classifications),
                "batch_times": [round(t, 2) for t in r.batch_times],
                "classifications": [
                    {"file": c.filename, "action": c.action,
                     "destination": c.destination, "confidence": c.confidence,
                     "reason": c.reason}
                    for c in r.classifications
                ],
            })
        out_path.write_text(json.dumps(raw, indent=2))
        print(f"\n  Raw results saved to {out_path}")

    finally:
        print(f"\nCleaning up {len(copied)} test files...")
        cleanup(copied)
        print("Done.")

    return 0
