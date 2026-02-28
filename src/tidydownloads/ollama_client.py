"""HTTP client for Ollama using only stdlib (urllib.request)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

__all__ = [
    "GENERATE_TIMEOUT",
    "PER_FILE_TIMEOUT",
    "SPINNER",
    "STARTUP_TIMEOUT",
    "OllamaClient",
    "OllamaError",
    "make_token_callback",
]

log = logging.getLogger("tidydownloads")

GENERATE_TIMEOUT = 300  # seconds (larger models need more time)
PER_FILE_TIMEOUT = 20  # seconds per file in a batch
STARTUP_TIMEOUT = 10  # seconds

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def make_token_callback(prefix: str) -> Callable[[int], None]:
    """Return a callback that prints a spinner + token count on the current line."""

    def on_token(n: int) -> None:
        frame = SPINNER[n % len(SPINNER)]
        print(f"\r  {prefix} {frame} {n} tokens", end="", flush=True)

    return on_token


class OllamaError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1:8b"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def is_serving(self) -> bool:
        """Check if Ollama HTTP server is responding."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except (urllib.error.URLError, OSError):
            return False

    def is_model_available(self) -> bool:
        """Check if the configured model is pulled."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "") for m in data.get("models", [])]
                return any(self.model in m for m in models)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return False

    def ensure_running(self) -> None:
        """Start Ollama if not running, wait for it to be ready."""
        if self.is_serving():
            return

        log.info("Ollama not running, attempting to start...")
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as e:
            raise OllamaError(
                "Ollama is not installed.\n\n"
                "  Install:  brew install ollama\n"
                "  Start:    brew services start ollama\n"
                "  Then run: tidydownloads scan"
            ) from e

        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self.is_serving():
                log.info("Ollama started successfully")
                return
            time.sleep(0.5)

        raise OllamaError(f"Ollama did not start within {STARTUP_TIMEOUT}s")

    def pull_model(self) -> None:
        """Pull the configured model from Ollama. Streams progress to stderr."""
        log.info("Pulling model %s...", self.model)
        payload = json.dumps(
            {
                "name": self.model,
                "stream": True,
            }
        ).encode()

        req = urllib.request.Request(
            f"{self.base_url}/api/pull",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                last_status = ""
                for line in resp:
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    status = data.get("status", "")
                    if status != last_status:
                        print(f"  {status}")
                        last_status = status
                    if data.get("error"):
                        raise OllamaError(data["error"])
        except urllib.error.URLError as e:
            raise OllamaError(f"Failed to pull model: {e}") from e

        if not self.is_model_available():
            raise OllamaError(f"Model '{self.model}' not available after pull")
        log.info("Model %s pulled successfully", self.model)

    def check_parallel_support(self) -> int:
        """Check OLLAMA_NUM_PARALLEL from environment.

        Returns the value if explicitly set, 0 otherwise.
        Can't query this from the Ollama API, so we rely on the env var.
        """
        return int(os.environ.get("OLLAMA_NUM_PARALLEL", 0))

    def generate(
        self,
        prompt: str,
        timeout: int = GENERATE_TIMEOUT,
        on_token: Callable[[int], None] | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str | None = None,
    ) -> dict[str, Any]:
        """Send a prompt to Ollama and return parsed JSON response.

        Uses streaming to provide live progress via *on_token* and to
        enforce a socket-level *timeout* (applied per-chunk, so stalls
        are detected quickly).

        *options* are merged with defaults (caller values take precedence).
        *keep_alive* sets how long the model stays loaded after the request.
        """
        merged_options: dict[str, Any] = {"temperature": 0.1}
        if options:
            merged_options.update(options)

        payload_dict: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": True,
            "options": merged_options,
        }
        if keep_alive:
            payload_dict["keep_alive"] = keep_alive

        payload = json.dumps(payload_dict).encode()

        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            response_text = ""
            token_count = 0
            deadline = time.monotonic() + timeout

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for line in resp:
                    if time.monotonic() > deadline:
                        raise OllamaError(f"Ollama request timed out ({timeout}s)")
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise OllamaError(chunk["error"])

                    fragment = chunk.get("response", "")
                    if fragment:
                        response_text += fragment
                        token_count += 1
                        if on_token is not None:
                            on_token(token_count)

                    if chunk.get("done"):
                        break

            return json.loads(response_text)  # type: ignore[no-any-return]
        except urllib.error.URLError as e:
            raise OllamaError(f"Failed to connect to Ollama: {e}") from e
        except ConnectionError as e:
            raise OllamaError(f"Ollama connection lost: {e}") from e
        except json.JSONDecodeError as e:
            raise OllamaError(f"Invalid JSON from Ollama: {e}") from e
        except TimeoutError as e:
            raise OllamaError(f"Ollama request timed out ({timeout}s)") from e
