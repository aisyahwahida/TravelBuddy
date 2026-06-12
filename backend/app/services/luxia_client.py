import json
import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_LUXIA_BASE_URL = "https://bridge.luxiacloud.com/luxia/v1/chat"
DEFAULT_LUXIA_MODEL = "luxia3-llm-8b-0731"


class LuxiaClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("LUXIA_API_KEY", "")
        self.base_url = os.getenv("LUXIA_BASE_URL", DEFAULT_LUXIA_BASE_URL)
        self.model = os.getenv("LUXIA_MODEL", DEFAULT_LUXIA_MODEL)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1600,
    ) -> str:
        if not self.api_key:
            raise ValueError("LUXIA_API_KEY is empty. Set it in your .env or environment.")

        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        response = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=int(os.getenv("LUXIA_TIMEOUT_SECONDS", "60")),
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])
