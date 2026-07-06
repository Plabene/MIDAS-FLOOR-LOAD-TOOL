from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


ProgressCallback = Callable[[float, str], None]


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


@dataclass
class ProgressReporter:
    callback: ProgressCallback | None = None
    current: float = 0.0

    def update(self, percent: float, message: str = "") -> None:
        value = clamp_percent(percent)
        self.current = value
        if self.callback:
            self.callback(value, message)

    def step(self, current_step: int, total_steps: int, message: str = "") -> None:
        if total_steps <= 0:
            self.update(0.0, message)
            return
        self.update((float(current_step) / float(total_steps)) * 100.0, message)
