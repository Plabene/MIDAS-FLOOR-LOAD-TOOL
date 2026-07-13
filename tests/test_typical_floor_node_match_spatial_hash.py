import math
import random

import pytest

from app.core.typical_floor_detector import _node_match_ratio


def _brute_force_node_match_ratio(first, second, tolerance):
    if not first or not second:
        return 0.0
    tol = abs(float(tolerance))
    matched = sum(
        min(math.hypot(float(x) - float(sx), float(y) - float(sy)) for sx, sy in second) <= tol
        for x, y in first
    )
    return matched / len(first)


@pytest.mark.parametrize("tolerance", [0.01, 0.25, 1.0, 3.5])
def test_spatial_hash_node_match_ratio_equals_brute_force(tolerance):
    randomizer = random.Random(20260713)
    second = [
        (randomizer.uniform(-100.0, 100.0), randomizer.uniform(-100.0, 100.0))
        for _index in range(500)
    ]
    first = [
        (randomizer.uniform(-100.0, 100.0), randomizer.uniform(-100.0, 100.0))
        for _index in range(300)
    ]
    first.extend(second[::25])

    actual = _node_match_ratio(first, second, tolerance)
    expected = _brute_force_node_match_ratio(first, second, tolerance)

    assert actual == pytest.approx(expected, abs=1.0e-12)


def test_zero_tolerance_uses_exact_coordinate_matches():
    first = [(0.0, 0.0), (1.0, 1.0), (-2.0, 3.0)]
    second = [(1.0, 1.0), (-2.0, 3.0), (8.0, 9.0)]

    assert _node_match_ratio(first, second, 0.0) == pytest.approx(2.0 / 3.0)


def test_near_zero_positive_tolerance_still_matches_brute_force():
    first = [(0.0, 0.0), (1.0 + 5.0e-14, 1.0)]
    second = [(0.0, 0.0), (1.0, 1.0)]

    assert _node_match_ratio(first, second, 1.0e-13) == _brute_force_node_match_ratio(first, second, 1.0e-13)
