"""
ScholarBot — LLM service abstraction.
Returns a callable llm(system, user) -> str.
Priority: Anthropic Claude > Ollama > template fallback.
"""
import logging
import os
from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS

logger = logging.getLogger(__name__)


def get_llm():
    """Return the best available LLM callable."""
    if ANTHROPIC_API_KEY:
        return _claude_llm()
    return _template_llm()


def _claude_llm():
    import requests

    def call(system: str, user: str) -> str:
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": CLAUDE_MAX_TOKENS,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=45,
            )
            data = r.json()
            if "content" in data:
                return data["content"][0]["text"]
            logger.error("Claude API error: %s", data)
            return _fallback_response()
        except Exception as e:
            logger.warning("Claude API call failed: %s", e)
            return _fallback_response()

    return call


def _template_llm():
    def call(system: str, user: str) -> str:
        logger.info("No API key — using template response")
        return _fallback_response()
    return call


def _fallback_response() -> str:
    return (
        "I am a highly motivated student committed to academic excellence "
        "and community impact. My studies have equipped me with technical "
        "skills and a deep understanding of the challenges facing my community."
    )
