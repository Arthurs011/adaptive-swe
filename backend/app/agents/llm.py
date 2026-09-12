"""OpenAI-compatible LLM client with usage tracking."""

from __future__ import annotations

import json
import time

import httpx

from ..config import get_settings


class LLMClient:
    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        if self.settings.llm_base_url and "openai" in self.settings.llm_base_url:
            self.api_key = self.settings.llm_api_key
        else:
            self.api_key = self.settings.llm_api_key
        self.base_url = self.settings.llm_base_url.rstrip("/")
        self.total_tokens = 0

    def complete(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
        json_mode: bool = False,
    ) -> tuple[str, int]:
        """Return (text, prompt_and_completion_tokens)."""
        model = model or self.settings.llm_model
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=180.0,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                total = usage.get("total_tokens", 0) or (
                    usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                )
                self.total_tokens += int(total)
                return content, int(total)
            except (httpx.HTTPError, KeyError) as exc:
                if attempt == 2:
                    raise RuntimeError(f"LLM call failed: {exc}") from exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("LLM call failed")

    def chat(self, system: str, user: str, **kwargs) -> tuple[str, int]:
        return self.complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts with the configured embeddings model.

        Falls back to a deterministic hashing embedding if no API key model
        available so the memory subsystem still works offline.
        """
        if not self.api_key or not self.settings.llm_embeddings_model:
            return [_fallback_embed(t) for t in texts]
        try:
            resp = httpx.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.settings.llm_embeddings_model,
                    "input": texts,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            ordered = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in ordered]
        except Exception:  # noqa: BLE001
            return [_fallback_embed(t) for t in texts]

    @staticmethod
    def parse_json(content: str) -> dict:
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(content[start : end + 1])
            return json.loads(content)
        except json.JSONDecodeError:
            return {}


def _fallback_embed(text: str, dim: int = 256) -> list[float]:
    """Deterministic offline embedding fallback (seeded by sha256)."""
    import hashlib

    vector = [0.0] * dim
    # slide a 4-char window
    for i in range(len(text) - 3):
        chunk = text[i : i + 4]
        h = int(hashlib.sha256(chunk.encode()).hexdigest()[:8], 16)
        idx = sum(ord(c) for c in chunk) % dim
        vector[idx] += (h % 100) / 100.0
    norm = sum(v * v for v in vector) ** 0.5 or 1.0
    return [v / norm for v in vector]