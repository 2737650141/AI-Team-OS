"""Provider-aware pre-call estimates; reported provider usage always wins after the call."""

from __future__ import annotations


def estimate_openai_text(text: str, model: str) -> int | None:
    try:
        import tiktoken

        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            return None
        return len(encoding.encode(text))
    except (ImportError, ValueError):
        return None
