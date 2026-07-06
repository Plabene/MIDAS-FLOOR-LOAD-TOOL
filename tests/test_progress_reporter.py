import pytest

from app.core.progress import ProgressReporter, clamp_percent


def test_progress_reporter_clamps_percent():
    calls = []
    reporter = ProgressReporter(callback=lambda percent, message: calls.append((percent, message)))

    reporter.update(-10, "start")
    reporter.update(150, "done")

    assert calls == [(0.0, "start"), (100.0, "done")]
    assert reporter.current == 100.0


def test_progress_reporter_step_calculates_percent():
    calls = []
    reporter = ProgressReporter(callback=lambda percent, message: calls.append((percent, message)))

    reporter.step(1, 4, "1/4")

    assert calls[-1] == (25.0, "1/4")
    assert reporter.current == 25.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-1.0, 0.0), (0.0, 0.0), (42.5, 42.5), (100.0, 100.0), (101.0, 100.0)],
)
def test_clamp_percent(value, expected):
    assert clamp_percent(value) == expected
