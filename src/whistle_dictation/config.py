"""Validated, atomically written settings. Audio and transcripts are never saved here."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

LANGUAGES = {"en", "de", "fr", "es", "it", "nl", "pl"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    hotkey: str = "Ctrl+Alt+Shift+Space"
    language: str | None = "en"
    microphone: int | None = None
    max_record_seconds: int = 300
    cleanup: bool = True
    terminal_punctuation: bool = False
    trailing_space: bool = True
    keywords: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)
    inference_timeout_seconds: int = 180

    def validate(self) -> Settings:
        from .win32 import NativeError, parse_hotkey

        try:
            parse_hotkey(self.hotkey)
        except (NativeError, ValueError, TypeError) as exc:
            raise ConfigError(str(exc)) from exc
        if self.language is not None and self.language not in LANGUAGES:
            raise ConfigError("Choose a supported language or automatic detection.")
        if self.microphone is not None and (type(self.microphone) is not int or self.microphone < 0):
            raise ConfigError("Microphone must be an input device index or null.")
        if type(self.max_record_seconds) is not int or not 10 <= self.max_record_seconds <= 900:
            raise ConfigError("Maximum recording time must be 10–900 seconds.")
        if type(self.inference_timeout_seconds) is not int or not 15 <= self.inference_timeout_seconds <= 600:
            raise ConfigError("Inference timeout must be 15–600 seconds.")
        for name in ("cleanup", "terminal_punctuation", "trailing_space"):
            if type(getattr(self, name)) is not bool:
                raise ConfigError(f"{name} must be true or false.")
        if not isinstance(self.keywords, list) or len(self.keywords) > 128:
            raise ConfigError("Use at most 128 dictionary phrases.")
        if any(not isinstance(word, str) or not word.strip() or len(word) > 120 or
               any(ord(char) < 32 for char in word) for word in self.keywords):
            raise ConfigError("Dictionary phrases must be non-empty single lines, up to 120 characters.")
        if not isinstance(self.replacements, dict) or len(self.replacements) > 128:
            raise ConfigError("Use at most 128 replacements.")
        for source, target in self.replacements.items():
            if (not isinstance(source, str) or not isinstance(target, str) or not source.strip()
                    or len(source) > 120 or len(target) > 500
                    or any(ord(c) < 32 for c in source + target)):
                raise ConfigError("Replacements must be single-line text with a non-empty source.")
        return self


def load_settings(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ConfigError("Settings must be a JSON object.")
        unknown = value.keys() - Settings.__dataclass_fields__.keys()
        if unknown:
            raise ConfigError(f"Unknown settings: {', '.join(sorted(unknown))}")
        return Settings(**value).validate()
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ConfigError(f"Could not read settings: {exc}") from exc


def save_settings(path: Path, settings: Settings) -> None:
    settings.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(asdict(settings), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
