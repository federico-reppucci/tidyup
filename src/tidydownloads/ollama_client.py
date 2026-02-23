"""HTTP client for Ollama using only stdlib (urllib.request)."""

from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("tidydownloads")

GENERATE_TIMEOUT = 120  # seconds
STARTUP_TIMEOUT = 10  # seconds


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
        except FileNotFoundError:
            raise OllamaError("Ollama not found. Install with: brew install ollama")

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
        payload = json.dumps({
            "name": self.model,
            "stream": True,
        }).encode()

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
            raise OllamaError(f"Failed to pull model: {e}")

        if not self.is_model_available():
            raise OllamaError(f"Model '{self.model}' not available after pull")
        log.info("Model %s pulled successfully", self.model)

    def generate(self, prompt: str) -> dict[str, Any]:
        """Send a prompt to Ollama and return parsed JSON response."""
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }).encode()

        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=GENERATE_TIMEOUT) as resp:
                data = json.loads(resp.read())
                response_text = data.get("response", "")
                return json.loads(response_text)
        except urllib.error.URLError as e:
            raise OllamaError(f"Failed to connect to Ollama: {e}")
        except json.JSONDecodeError as e:
            raise OllamaError(f"Invalid JSON from Ollama: {e}")
        except TimeoutError:
            raise OllamaError("Ollama request timed out")
