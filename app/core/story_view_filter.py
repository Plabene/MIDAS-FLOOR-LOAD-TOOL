from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .mgt_parser import Element, Node, Story


@dataclass(frozen=True)
class StoryBelowRange:
    story_name: str
    story_elevation: float
    lower_elevation: float | None
    upper_elevation: float | None


def story_below_range(stories: Sequence[Story], story: Story, tolerance: float = 0.01) -> StoryBelowRange:
    """Return the MIDAS Story View BELOW vertical range for the selected story."""

    story_z = float(getattr(story, "elevation", 0.0))
    tol = max(abs(float(tolerance)), 1.0e-9)
    elevations = sorted({float(getattr(item, "elevation", 0.0)) for item in stories or ()})
    lower_candidates = [z for z in elevations if z < story_z - tol]
    upper_candidates = [z for z in elevations if z > story_z + tol]
    return StoryBelowRange(
        story_name=str(getattr(story, "name", "") or ""),
        story_elevation=story_z,
        lower_elevation=lower_candidates[-1] if lower_candidates else None,
        upper_elevation=upper_candidates[0] if upper_candidates else None,
    )


def element_z_values(element: Element, node_by_id: dict[int, Node]) -> tuple[float, ...]:
    values: list[float] = []
    for node_id in tuple(getattr(element, "node_ids", ()) or ()):
        node = node_by_id.get(int(node_id))
        if node is not None:
            values.append(float(getattr(node, "z", 0.0)))
    return tuple(values)


def element_is_in_story_below_range(
    element: Element,
    node_by_id: dict[int, Node],
    story_range: StoryBelowRange,
    tolerance: float,
    *,
    include_horizontal_at_story: bool = True,
) -> bool:
    """Return True when an element belongs to the selected Story BELOW interval."""

    z_values = element_z_values(element, node_by_id)
    if not z_values:
        return False
    tol = max(abs(float(tolerance)), 1.0e-9)
    story_z = float(story_range.story_elevation)
    lower_z = story_range.lower_elevation
    z_min = min(z_values)
    z_max = max(z_values)

    if z_max > story_z + tol:
        return False
    if not any(abs(z - story_z) <= tol for z in z_values):
        return False
    if include_horizontal_at_story and all(abs(z - story_z) <= tol for z in z_values):
        return True
    if lower_z is not None and z_min < float(lower_z) - tol:
        return False
    return z_min < story_z - tol or any(abs(z - story_z) <= tol for z in z_values)
