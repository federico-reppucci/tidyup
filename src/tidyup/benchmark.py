"""Benchmark: compare Ollama models on file organization quality and speed."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from tidyup.config import Config
from tidyup.helpers import (
    Proposal,
    build_file_descriptions,
    parse_organize_response,
    precompute_previews,
)
from tidyup.ollama_client import GenerateResult, OllamaClient, OllamaError
from tidyup.prompts import build_organize_prompt
from tidyup.scanner import FileInfo, scan_downloads

__all__ = ["BenchmarkResult", "run_benchmark"]

log = logging.getLogger("tidyup")

DEFAULT_MODELS = [
    "gemma3:4b",
    "qwen3:4b",
    "gemma3:12b",
    "qwen3.5:9b",
    "qwen3.5:27b",
]


@dataclass
class BenchmarkResult:
    model: str
    elapsed: float = 0.0
    token_count: int = 0
    proposals: list[Proposal] = field(default_factory=list)
    valid_json: bool = False
    error: str = ""
    file_count: int = 0  # total input files

    @property
    def tokens_per_sec(self) -> float:
        return self.token_count / self.elapsed if self.elapsed > 0 else 0.0

    @property
    def files_covered(self) -> int:
        """Number of input files that appear in the response."""
        return len(self.proposals)

    @property
    def folders(self) -> dict[str, int]:
        """Top-level folder -> file count mapping."""
        counts: dict[str, int] = defaultdict(int)
        for p in self.proposals:
            top = PurePosixPath(p.destination_folder).parts[0] if p.destination_folder else "(root)"
            counts[top] += 1
        return dict(counts)

    @property
    def folder_count(self) -> int:
        return len(self.folders)


def _ensure_model(client: OllamaClient) -> None:
    """Pull model if not available."""
    if not client.is_model_available():
        print(f"  Pulling {client.model}...")
        client.pull_model()


def _run_single(
    client: OllamaClient,
    prompt: str,
    files: list[FileInfo],
    num_predict: int,
    num_ctx: int,
    timeout: int,
) -> BenchmarkResult:
    """Run a single benchmark pass for one model."""
    result = BenchmarkResult(model=client.model, file_count=len(files))
    token_count = 0

    def on_token(n: int) -> None:
        nonlocal token_count
        token_count = n
        frame = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[n % 10]
        print(f"\r  {client.model} {frame} {n} tokens", end="", flush=True)

    try:
        gen: GenerateResult = client.generate(
            prompt,
            timeout=timeout,
            on_token=on_token,
            options={"num_predict": num_predict, "num_ctx": num_ctx},
            keep_alive="10m",
        )
        print(f"\r  {client.model} — {gen.token_count} tokens in {gen.elapsed:.1f}s")

        result.elapsed = gen.elapsed
        result.token_count = gen.token_count
        result.valid_json = True
        result.proposals = parse_organize_response(gen.data, files)
    except OllamaError as e:
        print(f"\r  {client.model} — ERROR: {e}")
        result.error = str(e)

    return result


def run_benchmark(
    config: Config,
    models: list[str] | None = None,
    runs: int = 1,
) -> list[BenchmarkResult]:
    """Run benchmark: scan files once, test each model, return results."""
    model_list = models or DEFAULT_MODELS

    # Scan files
    files = scan_downloads(config)
    if not files:
        print("No files to benchmark.")
        return []

    print(f"TidyUp Benchmark — {len(files)} files in {config.target_dir}\n")

    # Build prompt once (shared across all models)
    previews = precompute_previews(files)
    file_descriptions = build_file_descriptions(files, previews)
    prompt = build_organize_prompt(file_descriptions)

    num_predict = len(files) * 60 + 200
    num_ctx = max(4096, len(prompt) // 4 + num_predict + 512)
    timeout = max(120, len(files) * 20)

    # Ensure Ollama is running
    probe = OllamaClient(config.ollama_url, model_list[0])
    probe.ensure_running()

    results: list[BenchmarkResult] = []

    for model_name in model_list:
        client = OllamaClient(config.ollama_url, model_name)

        try:
            _ensure_model(client)
        except OllamaError as e:
            print(f"  {model_name} — SKIP (pull failed: {e})")
            results.append(BenchmarkResult(model=model_name, error=str(e), file_count=len(files)))
            continue

        for run_idx in range(runs):
            if runs > 1:
                print(f"  Run {run_idx + 1}/{runs}:")
            r = _run_single(client, prompt, files, num_predict, num_ctx, timeout)
            if runs > 1:
                r.model = f"{model_name} (run {run_idx + 1})"
            results.append(r)

    return results


def print_comparison_table(results: list[BenchmarkResult]) -> None:
    """Print formatted comparison table."""
    if not results:
        return

    file_count = results[0].file_count
    cols = [
        f"{'Model':<22}",
        f"{'Time':>6}",
        f"{'Tokens':>7}",
        f"{'Tok/s':>6}",
        f"{'Files':>7}",
        f"{'Folders':>8}",
        f"{'Valid JSON':>11}",
    ]
    header = " ".join(cols)
    sep = "─" * len(header)

    print(f"\n{sep}")
    print(header)
    print(sep)

    for r in results:
        time_str = f"{r.elapsed:.1f}s" if r.elapsed else "—"
        tok_str = str(r.token_count) if r.token_count else "—"
        tps_str = f"{r.tokens_per_sec:.1f}" if r.elapsed else "—"
        files_str = f"{r.files_covered}/{file_count}" if r.valid_json else "—"
        folders_str = str(r.folder_count) if r.valid_json else "—"
        valid_str = "✓" if r.valid_json else f"✗ {r.error[:30]}"

        print(
            f"{r.model:<22} {time_str:>6} {tok_str:>7} {tps_str:>6} "
            f"{files_str:>7} {folders_str:>8} {valid_str:>11}"
        )

    print(sep)


def print_agreement_matrix(results: list[BenchmarkResult]) -> None:
    """Print pairwise agreement matrix (% of files assigned to same folder)."""
    valid = [r for r in results if r.valid_json and r.proposals]
    if len(valid) < 2:
        return

    # Build model -> {file_path: folder} mapping
    assignments: dict[str, dict[str, str]] = {}
    for r in valid:
        mapping = {p.relative_path: p.destination_folder for p in r.proposals}
        assignments[r.model] = mapping

    models = [r.model for r in valid]

    print("\nAgreement Matrix (% same folder):")

    # Header
    col_width = max(len(m) for m in models) + 2
    header = " " * col_width
    for m in models:
        header += f"{m:>{col_width}}"
    print(header)

    # Rows
    for m1 in models:
        row = f"{m1:<{col_width}}"
        for m2 in models:
            if m1 == m2:
                row += f"{'—':>{col_width}}"
            else:
                a1, a2 = assignments[m1], assignments[m2]
                common_files = set(a1.keys()) & set(a2.keys())
                if not common_files:
                    row += f"{'N/A':>{col_width}}"
                else:
                    agree = sum(1 for f in common_files if a1[f] == a2[f])
                    pct = agree * 100 // len(common_files)
                    row += f"{pct}%".rjust(col_width)
            row += ""
        print(row)


def print_folder_structures(results: list[BenchmarkResult]) -> None:
    """Print per-model folder structure summary."""
    valid = [r for r in results if r.valid_json and r.proposals]
    if not valid:
        return

    print("\nPer-model folder structures:")
    for r in valid:
        folders = r.folders
        sorted_folders = sorted(folders.items(), key=lambda x: -x[1])
        folder_parts = [f"{name}({count})" for name, count in sorted_folders]
        print(f"  {r.model}: {' '.join(folder_parts)}")
