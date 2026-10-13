from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from dotenv import load_dotenv

load_dotenv()


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None   # pesan asli penyedia, dikirim balik apa adanya (menjaga metadata seperti thought signature)


class LLMClient(Protocol):
    """Satu-satunya yang diketahui agent tentang LLM. Ganti penyedia = ganti satu kelas.

    messages (format netral):
      {"role": "user", "text": str}
      {"role": "assistant", "text": str, "tool_calls": [ToolCall], "raw": Any}
      {"role": "tool", "name": str, "result": dict}
    """

    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse: ...


class GeminiClient:
    _URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str, timeout: float = 30.0) -> None:
        self._key, self._model = api_key, model
        self._http = httpx.Client(timeout=timeout)

    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": _to_contents(messages),
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600},
        }
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]
        try:
            # API key di header, bukan di URL, supaya tidak masuk log.
            resp = self._http.post(
                self._URL.format(model=self._model), json=body, headers={"x-goog-api-key": self._key}
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"koneksi LLM gagal: {type(exc).__name__}") from None
        if resp.status_code != 200:
            try:
                detail = resp.json()["error"]["message"][:200]
            except Exception:
                detail = ""
            raise LLMError(f"LLM HTTP {resp.status_code}: {detail}")

        candidates = resp.json().get("candidates") or []
        content = candidates[0].get("content") if candidates else None
        if not content or not content.get("parts"):
            raise LLMError("LLM tidak mengembalikan konten (kemungkinan diblokir safety filter)")

        texts, calls = [], []
        for part in content["parts"]:
            if "functionCall" in part:
                fc = part["functionCall"]
                calls.append(ToolCall(fc["name"], fc.get("args") or {}))
            elif part.get("text") and not part.get("thought"):
                texts.append(part["text"])
        return LLMResponse(text="".join(texts).strip(), tool_calls=calls, raw=content)


def _to_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "assistant":
            contents.append(m["raw"] or {"role": "model", "parts": [{"text": m["text"]}]})
            continue
        part = (
            {"text": m["text"]}
            if m["role"] == "user"
            else {"functionResponse": {"name": m["name"], "response": {"result": m["result"]}}}
        )
        if contents and contents[-1]["role"] == "user":   # hasil tool paralel harus dalam satu giliran
            contents[-1]["parts"].append(part)
        else:
            contents.append({"role": "user", "parts": [part]})
    return contents


def get_llm() -> LLMClient:
    return GeminiClient(os.environ["GEMINI_API_KEY"], os.environ["LLM_MODEL"])