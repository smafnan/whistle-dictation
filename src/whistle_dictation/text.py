"""Conservative formatting; no remote rewriting or interpretation of spoken commands."""
from __future__ import annotations

import re
import unicodedata

from .config import Settings


def format_transcript(text: str, settings: Settings) -> str:
    # Always remove controls: injecting a tab or newline could move focus or submit a form.
    text = "".join(" " if unicodedata.category(c).startswith("C") else c for c in text)
    text = re.sub(r"\s+", " ", text).strip()
    if settings.replacements:
        ordered = sorted(settings.replacements, key=len, reverse=True)
        alternatives = "|".join(f"(?P<term{i}>{re.escape(key)})" for i, key in enumerate(ordered))
        lookup = {f"term{i}": settings.replacements[key] for i, key in enumerate(ordered)}
        text = re.sub(rf"(?<!\w)(?:{alternatives})(?!\w)",
                      lambda match: lookup[match.lastgroup], text, flags=re.IGNORECASE)
    if settings.cleanup:
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        # Only capitalize the first character. Preserve names and domain-specific casing.
        if text:
            text = text[0].upper() + text[1:]
    if settings.terminal_punctuation and text and text[-1] not in '.!?…"”\')':
        text += "."
    # Apply again after personal replacements; they must not introduce controls either.
    text = "".join(" " if unicodedata.category(c).startswith("C") else c for c in text)
    return re.sub(r"\s+", " ", text).strip()
