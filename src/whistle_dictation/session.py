"""Small state machine shared by the tray app and its tests."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4


class State(str, Enum):
    LOADING = "loading"
    READY = "ready"
    RECORDING = "recording"
    PROCESSING = "processing"
    ERROR = "error"
    CLOSED = "closed"


@dataclass
class Session:
    state: State = State.LOADING
    request_id: str | None = None
    target: Any = None

    def ready(self) -> None:
        if self.state in (State.LOADING, State.ERROR):
            self.state = State.READY

    def start(self, target: Any = None) -> str:
        if self.state != State.READY:
            raise RuntimeError("Dictation is not ready.")
        self.request_id = uuid4().hex
        self.target = target
        self.state = State.RECORDING
        return self.request_id

    def process(self) -> None:
        if self.state != State.RECORDING:
            raise RuntimeError("No recording to transcribe.")
        self.state = State.PROCESSING

    def accepts(self, request_id: str | None) -> bool:
        return self.state == State.PROCESSING and self.request_id == request_id

    def complete(self, request_id: str) -> bool:
        if not self.accepts(request_id):
            return False
        self.state = State.READY
        return True

    def reset(self, *, reload: bool = False) -> None:
        self.request_id = None
        self.target = None
        if self.state != State.CLOSED:
            self.state = State.LOADING if reload else State.READY

    def fail(self) -> None:
        if self.state != State.CLOSED:
            self.state = State.ERROR
            self.request_id = None
            self.target = None

    def close(self) -> None:
        self.state = State.CLOSED
        self.request_id = None
        self.target = None
