from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from dotenv import load_dotenv

import json
import logging
import time
import uuid
from functools import lru_cache

logger = logging.getLogger(__name__)

load_dotenv()


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


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
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": 1000},
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
            if m.get("raw"):
                contents.append(m["raw"])
            elif m.get("tool_calls"):
                parts = [{"functionCall": {"name": tc.name, "args": tc.args}} for tc in m["tool_calls"]]
                contents.append({"role": "model", "parts": parts})
            else:
                contents.append({"role": "model", "parts": [{"text": m["text"]}]})
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


_OPENAI_COMPAT = {
    # nama: (base_url, env key, env model)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OPENROUTER_MODEL"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "CEREBRAS_MODEL"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "OPENAI_MODEL"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"),
}


@lru_cache(maxsize=1)   # satu instance: status circuit breaker harus bertahan antar pesan
def get_llm() -> LLMClient:
    order = [p.strip() for p in os.environ.get("LLM_PROVIDERS", "groq,openrouter,gemini").split(",") if p.strip()]
    clients: list[tuple[str, LLMClient]] = []
    for name in order:
        if name == "gemini":
            if os.environ.get("GEMINI_API_KEY") and os.environ.get("LLM_MODEL"):
                clients.append((name, GeminiClient(os.environ["GEMINI_API_KEY"], os.environ["LLM_MODEL"])))
        elif name in ("gemini_backup", "gemini2"):
            key = os.environ.get("GEMINI_API_KEY_BACKUP") or os.environ.get("GEMINI_API_KEY_2")
            model = os.environ.get("GEMINI_MODEL_BACKUP") or os.environ.get("LLM_MODEL")
            if key and model:
                clients.append((name, GeminiClient(key, model)))
        elif name == "ollama":
            if os.environ.get("OLLAMA_MODEL"):
                url = os.environ.get("OLLAMA_URL", "http://localhost:11434/v1")
                clients.append((name, OpenAICompatClient(name, url, None, os.environ["OLLAMA_MODEL"], timeout=90.0)))
        elif name in _OPENAI_COMPAT:
            url, key_env, model_env = _OPENAI_COMPAT[name]
            if os.environ.get(key_env) and os.environ.get(model_env):
                clients.append((name, OpenAICompatClient(name, url, os.environ[key_env], os.environ[model_env])))
    if not clients:
        raise LLMError("tidak ada provider LLM yang dikonfigurasi di .env")
    logger.info("provider LLM aktif: %s", [n for n, _ in clients])
    return FallbackLLM(clients)

class OpenAICompatClient:
    """Groq, OpenRouter, Cerebras, Ollama, dan lainnya: semuanya berbicara format yang sama."""

    def __init__(self, name: str, base_url: str, api_key: str | None, model: str, timeout: float = 30.0) -> None:
        self.name, self._url, self._model = name, base_url.rstrip("/") + "/chat/completions", model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if name == "openrouter":
            self._headers["HTTP-Referer"] = os.environ.get("OPENROUTER_REFERER", "https://github.com/enerva/ai-agent-lab")
            self._headers["X-Title"] = "Enerva AI Concierge"
        self._http = httpx.Client(timeout=timeout)

    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        body: dict[str, Any] = {
            "messages": [{"role": "system", "content": system}, *_to_openai(messages)],
            "temperature": 0.6,
            "max_tokens": 1000,
        }
        if "," in self._model:
            model_list = [m.strip() for m in self._model.split(",") if m.strip()]
            body["models"] = model_list
            body["model"] = model_list[0]
        else:
            body["model"] = self._model
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        try:
            resp = self._http.post(self._url, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.name}: koneksi gagal ({type(exc).__name__})") from None
        if resp.status_code != 200:
            detail = ""
            try:
                err_data = resp.json()
                if isinstance(err_data, dict):
                    err_obj = err_data.get("error")
                    detail = err_obj.get("message", "") if isinstance(err_obj, dict) else str(err_obj or "")
            except Exception:
                detail = resp.text[:200]
            raise LLMError(f"{self.name}: HTTP {resp.status_code} ({detail[:200]})")
        try:
            msg = resp.json()["choices"][0]["message"]
            calls = []
            for tc in msg.get("tool_calls") or []:
                args = json.loads(tc["function"].get("arguments") or "{}")
                calls.append(ToolCall(tc["function"]["name"], args if isinstance(args, dict) else {}, tc.get("id")))
        except (KeyError, IndexError, ValueError, TypeError):
            raise LLMError(f"{self.name}: respons tidak valid") from None
        return LLMResponse(text=(msg.get("content") or "").strip(), tool_calls=calls, raw=None)


def _to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["text"]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": m["text"] or None,
                "tool_calls": [
                    {"id": tc.id or f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.args)}}
                    for tc in m["tool_calls"]
                ],
            })
        elif m["role"] == "assistant":
            out.append({"role": "assistant", "content": m["text"]})
        else:
            out.append({"role": "tool", "tool_call_id": m.get("id") or "", "content": json.dumps(m["result"])})
    return out


class FallbackLLM:
    """Coba penyedia berurutan. Yang gagal diistirahatkan sebentar (circuit breaker),
    supaya tiap pesan tidak menunggu timeout penyedia yang sedang kena limit."""

    def __init__(self, clients: list[tuple[str, LLMClient]], cooldown: float = 60.0, clock=time.monotonic) -> None:
        self._clients, self._cooldown, self._clock = clients, cooldown, clock
        self._down_until: dict[str, float] = {}

    def chat(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        now = self._clock()
        candidates = [c for c in self._clients if self._down_until.get(c[0], 0) <= now] or self._clients
        failed = []
        for name, client in candidates:
            try:
                return client.chat(system, messages, tools)
            except LLMError as exc:
                self._down_until[name] = self._clock() + self._cooldown
                failed.append(name)
                logger.warning("provider %s gagal: %s", name, exc)
        raise LLMError("semua provider gagal: " + ", ".join(failed))