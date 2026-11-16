"""Gemini wrapper that always returns parsed JSON.

When no API key is configured, `available` is False and callers use their rule-based fallback.
"""

import json
import re

import config


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, temperature: float | None = None):
        self.api_key = config.GEMINI_API_KEY if api_key is None else api_key
        self.model = model or config.GEMINI_MODEL
        self.temperature = config.LLM_TEMPERATURE if temperature is None else temperature
        self._client = None
        self.calls = []  # (purpose, prompt chars, response chars) for the audit trail

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate_json(self, prompt: str, purpose: str = "", system: str | None = None) -> dict:
        """Send the prompt and return the JSON object in the reply. Retries once on bad JSON."""
        if not self.available:
            raise LLMError("No GEMINI_API_KEY configured")
        from google.genai import types

        settings = types.GenerateContentConfig(
            system_instruction=system or "You are a precise assistant that replies with valid JSON only.",
            response_mime_type="application/json",
            temperature=self.temperature,
        )
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        last_error = None
        for _ in range(2):
            try:
                response = self._get_client().models.generate_content(
                    model=self.model, contents=contents, config=settings
                )
            except Exception as error:  # network, quota, auth
                raise LLMError(f"Gemini call failed: {error}") from error
            text = response.text or ""
            self.calls.append({"purpose": purpose, "prompt_chars": len(prompt), "response_chars": len(text)})
            try:
                return parse_json(text)
            except ValueError as error:
                last_error = error
                contents += [
                    {"role": "model", "parts": [{"text": text}]},
                    {"role": "user", "parts": [{"text": f"That was not valid JSON ({error}). Reply with the corrected JSON object only."}]},
                ]
        raise LLMError(f"Gemini did not return valid JSON: {last_error}")


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
            raise ValueError("no JSON object found")
        try:
            value = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as error:
            raise ValueError(str(error)) from error
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
