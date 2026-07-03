from __future__ import annotations

from shapely.geometry import Polygon


def validate_polygon(polygon: Polygon, *, min_area: float = 1.0e-8) -> list[str]:
    warnings: list[str] = []
    if polygon.is_empty:
        warnings.append("polygon이 비어 있습니다.")
    if polygon.area <= min_area:
        warnings.append(f"polygon 면적이 너무 작습니다: {polygon.area:.6g}")
    if not polygon.is_valid:
        warnings.append("polygon self-intersection 또는 geometry invalid가 감지되었습니다.")
    return warnings
