from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion, merge_adjacent_load_regions
from app.core.load_parser import LoadLayerInfo


def test_merge_touching_same_load_regions_into_one():
    left = _region("A", "1F", "LOAD_001_A_DL_1_LL_1", [(0, 0), (5, 0), (5, 4), (0, 4)])
    right = _region("B", "1F", "LOAD_001_A_DL_1_LL_1", [(5, 0), (10, 0), (10, 4), (5, 4)])

    merged = merge_adjacent_load_regions([left, right])

    assert len(merged) == 1
    assert merged[0].region.source_id.startswith("MERGED:")
    assert merged[0].area == 40.0
    assert "MERGED_ADJACENT_HATCH_REGIONS(n=2)" in merged[0].warnings


def test_do_not_merge_disconnected_regions():
    first = _region("A", "1F", "LOAD_001_A_DL_1_LL_1", [(0, 0), (5, 0), (5, 4), (0, 4)])
    second = _region("B", "1F", "LOAD_001_A_DL_1_LL_1", [(20, 0), (25, 0), (25, 4), (20, 4)])

    merged = merge_adjacent_load_regions([first, second])

    assert len(merged) == 2


def test_do_not_merge_different_layers_or_stories():
    base = _region("A", "1F", "LOAD_001_A_DL_1_LL_1", [(0, 0), (5, 0), (5, 4), (0, 4)])
    different_layer = _region("B", "1F", "LOAD_002_A_DL_1_LL_1", [(5, 0), (10, 0), (10, 4), (5, 4)])
    different_story = _region("C", "2F", "LOAD_001_A_DL_1_LL_1", [(5, 0), (10, 0), (10, 4), (5, 4)])

    assert len(merge_adjacent_load_regions([base, different_layer])) == 2
    assert len(merge_adjacent_load_regions([base, different_story])) == 2


def _region(source_id: str, story: str, layer: str, vertices):
    points = [(float(x), float(y)) for x, y in vertices]
    polygon = Polygon(points)
    hatch = HatchRegion(
        source_type="HATCH",
        layer=layer,
        handle=source_id,
        vertices=points,
        polygon=polygon,
        area=float(polygon.area),
        bbox=tuple(float(value) for value in polygon.bounds),
        story_name=story,
        source_id=source_id,
        hatch_pattern_name="SOLID",
        hatch_solid_fill=1,
    )
    load = LoadLayerInfo(layer=layer, real_name="A", dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])
