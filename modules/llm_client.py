"""Gemini wrapper that returns parsed JSON and records every call for the LLM trace.

The API key comes from the app (user input) or from GEMINI_API_KEY in the environment / .env.
It is held in memory only and never written to disk or logs.
"""

import json
import re
import time

import config

MAX_TRACE_CHARS = 20000  # prompt / response text kept per call for the trace view
TRANSIENT_RETRY_WAITS = (2, 5, 10)  # seconds between retries of dropped connections / server errors
TRANSIENT_MARKERS = (
    "disconnected",
    "connection",
    "timed out",
    "timeout",
    "temporarily",
    "unavailable",
    " 500",
    " 502",
    " 503",
    " 504",
    "internal",
    "overloaded",
)


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, temperature: float | None = None):
        self.api_key = (config.GEMINI_API_KEY if api_key is None else api_key).strip()
        self.model = (model or config.GEMINI_MODEL).strip()
        self.temperature = config.LLM_TEMPERATURE if temperature is None else temperature
        self._client = None
        self.calls = []  # one entry per request: purpose, latency, tokens, prompt, response

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def total_tokens(self) -> int:
        return sum((c.get("prompt_tokens") or 0) + (c.get("output_tokens") or 0) for c in self.calls)

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def ping(self) -> dict:
        """Check that the key and model work with one tiny request."""
        reply = self.generate_json('Reply with exactly this JSON: {"ok": true}', purpose="connection_test")
        if reply.get("ok") is not True:
            raise LLMError(f"Unexpected reply from {self.model}: {reply}")
        return {"model": self.model, "latency_ms": self.calls[-1]["latency_ms"]}

    def generate_json(self, prompt: str, purpose: str = "", system: str | None = None) -> dict:
        """Send the prompt and return the JSON object in the reply. Retries once on invalid JSON."""
        if not self.available:
            raise LLMError("No Gemini API key. Enter it in the sidebar or set GEMINI_API_KEY in .env.")
        from google.genai import types

        settings = types.GenerateContentConfig(
            system_instruction=system or "You are a precise analytics assistant. Reply with valid JSON only.",
            response_mime_type="application/json",
            temperature=self.temperature,
        )
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        last_error = None
        for _attempt in range(2):
            started = time.perf_counter()
            for network_try, wait in enumerate((*TRANSIENT_RETRY_WAITS, None)):
                try:
                    response = self._get_client().models.generate_content(
                        model=self.model, contents=contents, config=settings
                    )
                    break
                except Exception as error:
                    self._record(purpose, prompt, "", started, None, ok=False, error=str(error))
                    if wait is None or not _is_transient(error):
                        raise LLMError(_friendly_error(error, self.model)) from error
                    self.calls[-1]["error"] += f" (retry {network_try + 1} in {wait}s)"
                    time.sleep(wait)
                    started = time.perf_counter()
            text = response.text or ""
            try:
                value = parse_json(text)
                self._record(purpose, prompt, text, started, response, ok=True)
                return value
            except ValueError as error:
                last_error = error
                self._record(purpose, prompt, text, started, response, ok=False, error=f"invalid JSON: {error}")
                contents += [
                    {"role": "model", "parts": [{"text": text}]},
                    {
                        "role": "user",
                        "parts": [
                            {"text": f"That was not valid JSON ({error}). Reply with the corrected JSON object only."}
                        ],
                    },
                ]
        raise LLMError(f"{self.model} did not return valid JSON for {purpose or 'the request'}: {last_error}")

    def _record(self, purpose, prompt, text, started, response, ok, error=None):
        usage = getattr(response, "usage_metadata", None)
        self.calls.append(
            {
                "purpose": purpose,
                "model": self.model,
                "ok": ok,
                "error": error,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
                "prompt": prompt[:MAX_TRACE_CHARS],
                "response": text[:MAX_TRACE_CHARS],
            }
        )


def _is_transient(error: Exception) -> bool:
    """Network drops and 5xx errors are worth retrying; bad keys, unknown models and quota are not."""
    message = f" {type(error).__name__} {error}".lower()
    if any(m in message for m in ("api key", "permission_denied", "not found", "quota", "resource_exhausted")):
        return False
    return any(marker in message for marker in TRANSIENT_MARKERS)


def _friendly_error(error: Exception, model: str) -> str:
    message = str(error)
    lowered = message.lower()
    if (
        "api key not valid" in lowered
        or "api_key_invalid" in lowered
        or "permission_denied" in lowered
        or " 401" in lowered
        or " 403" in lowered
    ):
        return "Gemini rejected the API key. Check it at https://aistudio.google.com/apikey"
    if ("not found" in lowered and "model" in lowered) or " 404" in lowered:
        return f"Model '{model}' was not found for this key. Pick another model in the sidebar."
    if "resource_exhausted" in lowered or "quota" in lowered or " 429" in lowered:
        return "Gemini quota or rate limit reached. Wait a minute or use a key with more quota."
    return f"Gemini call failed: {message[:500]}"


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating ``` fences and text around the object."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as error:
            raise ValueError(str(error)) from error
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
