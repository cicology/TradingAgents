from __future__ import annotations

import time
from typing import Any

import httpx

from trading_desk.config import OPENROUTER_URL, SITE_NAME, SITE_URL, api_key, unique_models


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self, timeout: float = 90.0) -> None:
        self._timeout = timeout
        self.model_used: str | None = None

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        last_error: Exception | None = None
        for model in unique_models():
            try:
                text = self._post(model, system, user, temperature)
                self.model_used = model
                return text
            except OpenRouterError as exc:
                last_error = exc
                message = str(exc).lower()
                if any(token in message for token in ("429", "rate", "404", "not found", "unavailable")):
                    time.sleep(1.5)
                    continue
                raise
        raise OpenRouterError(f"All OpenRouter models failed. Last error: {last_error}")

    def _post(self, model: str, system: str, user: str, temperature: float) -> str:
        headers = {
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": SITE_URL,
            "X-Title": SITE_NAME,
        }
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(OPENROUTER_URL, headers=headers, json=payload)
        if response.status_code >= 400:
            raise OpenRouterError(f"{model} HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError(f"Unexpected OpenRouter payload: {data}") from exc
        if not content:
            raise OpenRouterError(f"{model} returned empty content")
        return str(content)
