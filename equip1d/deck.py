from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Literal

DeckCommand = Literal["play", "stop", "rewind", "fast-forward"]


@dataclass(frozen=True)
class DeckProbe:
    available: bool
    status: str = "unknown"
    timecode: str | None = None
    error: str | None = None


class DeckControlError(RuntimeError):
    pass


class DvcontDeckController:
    """Controls FireWire AV/C tape transport through libavc1394's dvcont."""

    COMMANDS: dict[DeckCommand, str] = {
        "play": "play",
        "stop": "stop",
        "rewind": "rewind",
        "fast-forward": "ff",
    }

    def __init__(self, dvcont_bin: str = "dvcont", timeout: float = 1.5):
        self.dvcont_bin = dvcont_bin
        self.timeout = timeout
        self.last_command: DeckCommand | None = None
        self.last_error: str | None = None

    def command(self, command: DeckCommand) -> None:
        dvcont_command = self.COMMANDS.get(command)
        if not dvcont_command:
            raise DeckControlError(f"Unsupported deck command: {command}")
        self._run([dvcont_command], check=True)
        self.last_command = command
        self.last_error = None

    def probe(self, camera_connected: bool) -> DeckProbe:
        if not camera_connected:
            return DeckProbe(available=False, status="no_camera")

        status = "unknown"
        timecode = None
        error = None
        try:
            status_text = self._run(["status"], check=False)
            status = self._clean_output(status_text) or "unknown"
        except DeckControlError as exc:
            error = str(exc)

        try:
            timecode_text = self._run(["timecode"], check=False)
            timecode = self._clean_output(timecode_text) or None
        except DeckControlError as exc:
            error = error or str(exc)

        self.last_error = error
        return DeckProbe(
            available=error is None,
            status=status,
            timecode=timecode,
            error=error,
        )

    def _run(self, args: list[str], check: bool) -> str:
        try:
            result = subprocess.run(
                [self.dvcont_bin, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise DeckControlError(
                f"{self.dvcont_bin} not found; install libavc1394-tools for deck control"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise DeckControlError(f"{self.dvcont_bin} {' '.join(args)} timed out") from exc
        except OSError as exc:
            raise DeckControlError(f"Could not run {self.dvcont_bin}: {exc}") from exc

        output = (result.stdout or result.stderr or "").strip()
        if check and result.returncode != 0:
            detail = output or f"exit status {result.returncode}"
            raise DeckControlError(f"dvcont {' '.join(args)} failed: {detail}")
        if result.returncode != 0:
            raise DeckControlError(output or f"dvcont {' '.join(args)} exited {result.returncode}")
        return output

    @staticmethod
    def _clean_output(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            return ""
        return lines[-1]


def deck_controller_from_env() -> DvcontDeckController:
    return DvcontDeckController(dvcont_bin=os.environ.get("EQUIP1_DVCONT_BIN", "dvcont"))
