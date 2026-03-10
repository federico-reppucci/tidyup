"""Thread-safe progress display for tidyup scan phases."""

from __future__ import annotations

import shutil
import sys
import threading
import time
from collections.abc import Callable

__all__ = ["ProgressDisplay"]

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _format_elapsed(seconds: float) -> str:
    """Format elapsed time: '3s', '1m12s'."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m{s % 60:02d}s"


class ProgressDisplay:
    """Thread-safe phase-based progress display for the scan command.

    Usage::

        progress = ProgressDisplay(total_files=500)
        progress.phase(1, "Scanning")
        progress.finish_phase("523 files found")
        progress.phase(2, "Deduplicating")
        progress.finish_phase("12 duplicates")
        ...
    """

    TOTAL_PHASES = 5

    def __init__(self, total_files: int) -> None:
        self._total_files = total_files
        self._lock = threading.Lock()
        self._start_time = time.monotonic()
        self._phase_start = time.monotonic()
        self._phase_num = 0
        self._phase_name = ""
        self._spin_counter = 0
        # Parallel batch tracking
        self._total_batches = 0
        self._completed_batches = 0
        self._active_tokens: dict[int, int] = {}  # batch_num -> token count
        self._last_line_len = 0

    def _write_line(self, text: str, end: str = "") -> None:
        """Write text with padding to clear previous content."""
        cols = shutil.get_terminal_size().columns
        padded = text[:cols].ljust(min(self._last_line_len, cols))
        sys.stdout.write(padded + end)
        sys.stdout.flush()
        self._last_line_len = len(text)

    def _prefix(self) -> str:
        return f"  [{self._phase_num}/{self.TOTAL_PHASES}] {self._phase_name}"

    def phase(self, number: int, name: str) -> None:
        """Start a new phase."""
        with self._lock:
            self._phase_num = number
            self._phase_name = name
            self._phase_start = time.monotonic()
            self._spin_counter = 0
            self._total_batches = 0
            self._completed_batches = 0
            self._active_tokens.clear()
            self._write_line(f"\r{self._prefix()}...", end="")

    def update(self, detail: str) -> None:
        """Update current phase line with a spinner + detail. Thread-safe."""
        with self._lock:
            self._spin_counter += 1
            frame = SPINNER[self._spin_counter % len(SPINNER)]
            elapsed = _format_elapsed(time.monotonic() - self._phase_start)
            self._write_line(f"\r{self._prefix()}... {frame} {detail} ({elapsed})", end="")

    def setup_parallel(self, total_batches: int) -> None:
        """Configure for parallel batch tracking."""
        with self._lock:
            self._total_batches = total_batches
            self._completed_batches = 0
            self._active_tokens.clear()

    def batch_token(self, batch_num: int, token_count: int) -> None:
        """Called per-token by parallel workers. Renders consolidated line."""
        with self._lock:
            self._active_tokens[batch_num] = token_count
            self._spin_counter += 1
            frame = SPINNER[self._spin_counter % len(SPINNER)]
            elapsed = _format_elapsed(time.monotonic() - self._phase_start)
            total_tokens = sum(self._active_tokens.values())
            active = len(self._active_tokens)
            done = self._completed_batches
            detail = (
                f"batch {done + 1}/{self._total_batches} · {active} active · {total_tokens} tokens"
            )
            self._write_line(f"\r{self._prefix()}... {frame} {detail} ({elapsed})", end="")

    def batch_done(self, batch_num: int) -> None:
        """Mark a batch as completed. Thread-safe."""
        with self._lock:
            self._completed_batches += 1
            self._active_tokens.pop(batch_num, None)

    def finish_phase(self, summary: str = "done") -> None:
        """Finish current phase: print final line with elapsed time."""
        with self._lock:
            elapsed = _format_elapsed(time.monotonic() - self._phase_start)
            self._write_line(f"\r{self._prefix()}... {summary} ({elapsed})", end="\n")

    def make_token_callback(self, batch_num: int | None = None) -> Callable[[int], None]:
        """Return an on_token callback for OllamaClient.generate().

        If batch_num is provided, updates the parallel batch tracker.
        Otherwise, updates the phase line with token count.
        """
        if batch_num is not None:

            def _on_token_batch(n: int) -> None:
                self.batch_token(batch_num, n)

            return _on_token_batch

        def _on_token_single(n: int) -> None:
            self.update(f"{n} tokens")

        return _on_token_single
