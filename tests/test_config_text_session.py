from dataclasses import replace
import json
import unicodedata

import pytest

from whistle_dictation import config
from whistle_dictation.config import ConfigError, Settings, load_settings, save_settings
from whistle_dictation.session import Session, State
from whistle_dictation.text import format_transcript


def test_settings_unicode_roundtrip_and_missing_defaults(tmp_path):
    path = tmp_path / "settings.json"
    assert load_settings(path) == Settings()
    settings = Settings(
        hotkey="Ctrl+Shift+F9", language="de", microphone=2,
        keywords=["München", "Cactus Needle"], replacements={"munich": "München"},
        terminal_punctuation=True,
    )
    save_settings(path, settings)
    assert load_settings(path) == settings
    assert "München" in path.read_text(encoding="utf-8")
    assert not path.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("changes", [
    {"hotkey": "Ctrl+Alt+"},
    {"hotkey": None},
    {"language": "ur"},
    {"microphone": True},
    {"microphone": -1},
    {"max_record_seconds": 9},
    {"max_record_seconds": 901},
    {"max_record_seconds": True},
    {"inference_timeout_seconds": 14},
    {"inference_timeout_seconds": 601},
    {"cleanup": "yes"},
    {"terminal_punctuation": 1},
    {"trailing_space": None},
    {"keywords": "needle"},
    {"keywords": [" "]},
    {"keywords": ["line\nbreak"]},
    {"keywords": ["x" * 121]},
    {"keywords": ["x"] * 129},
    {"replacements": []},
    {"replacements": {"": "value"}},
    {"replacements": {"name": "value\tcommand"}},
])
def test_settings_reject_invalid_fields(changes):
    with pytest.raises(ConfigError):
        replace(Settings(), **changes).validate()


@pytest.mark.parametrize("contents", [
    "[]", "{broken", '{"unknown": 1}', '{"language": []}',
    '{"hotkey": "Win+Space"}',
])
def test_load_settings_wraps_malformed_user_configuration(tmp_path, contents):
    path = tmp_path / "settings.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)


def test_settings_atomic_replace_failure_preserves_previous_config(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    previous = Settings(language="de")
    save_settings(path, previous)

    def unavailable(*_):
        raise OSError("configuration is locked")

    with monkeypatch.context() as patch:
        patch.setattr(config.os, "replace", unavailable)
        with pytest.raises(OSError, match="locked"):
            save_settings(path, Settings(language="en"))
    assert load_settings(path) == previous
    assert not path.with_suffix(".json.tmp").exists()


def test_invalid_save_does_not_replace_existing_config(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(path, Settings())
    previous = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(ConfigError):
        save_settings(path, Settings(keywords=["unsafe\nphrase"]))
    assert json.loads(path.read_text(encoding="utf-8")) == previous


def test_formatting_preserves_names_and_conservatively_cleans_punctuation():
    assert format_transcript("  hello , iPhone and McDonald ! ", Settings()) == (
        "Hello, iPhone and McDonald!"
    )
    assert format_transcript("hello , iPhone", Settings(cleanup=False)) == "hello , iPhone"
    assert format_transcript("hello", Settings(terminal_punctuation=True)) == "Hello."
    assert format_transcript("hello?", Settings(terminal_punctuation=True)) == "Hello?"
    assert format_transcript(" \n\t ", Settings(terminal_punctuation=True)) == ""


def test_replacements_choose_longest_phrase_and_do_not_cascade():
    settings = Settings(
        cleanup=False,
        replacements={"cactus needle": "Needle 3", "needle": "Needle", "alpha": "beta",
                      "beta": "gamma", "C++": "C plus plus"},
    )
    assert format_transcript("CACTUS NEEDLE needle pinneedle alpha beta C++", settings) == (
        "Needle 3 Needle pinneedle beta gamma C plus plus"
    )


@pytest.mark.parametrize("text", ["Istanbul", "\u0130stanbul", "\u0131stanbul"])
def test_unicode_ignorecase_replacement_does_not_raise_keyerror(text):
    settings = Settings(cleanup=False, replacements={"istanbul": "Istanbul"})
    assert format_transcript(text, settings) == "Istanbul"


def test_control_characters_are_removed_before_and_after_replacements():
    settings = Settings(replacements={"sample": "hello\u202eworld\x00now"})
    result = format_transcript("\tsample\ntext\u202e\x00", settings)
    assert result == "Hello world now text"
    assert not any(unicodedata.category(char).startswith("C") for char in result)


def test_cancel_and_stale_response_cannot_complete_new_dictation():
    session = Session()
    session.ready()
    old_id = session.start(target="first field")
    session.process()
    session.reset()
    assert session.target is None
    assert not session.accepts(old_id)
    new_id = session.start(target="second field")
    session.process()
    assert new_id != old_id
    assert not session.complete(old_id)
    assert session.state == State.PROCESSING
    assert session.target == "second field"
    assert session.complete(new_id)
    assert session.state == State.READY
    assert not session.complete(new_id)


def test_state_machine_rejects_invalid_transitions_and_stays_closed():
    session = Session()
    with pytest.raises(RuntimeError, match="not ready"):
        session.start()
    with pytest.raises(RuntimeError, match="No recording"):
        session.process()
    session.ready()
    session.start("field")
    with pytest.raises(RuntimeError, match="not ready"):
        session.start()
    session.fail()
    assert session.state == State.ERROR
    assert session.request_id is None and session.target is None
    session.reset(reload=True)
    assert session.state == State.LOADING
    session.close()
    session.ready()
    session.fail()
    session.reset()
    assert session.state == State.CLOSED
    assert session.request_id is None and session.target is None
