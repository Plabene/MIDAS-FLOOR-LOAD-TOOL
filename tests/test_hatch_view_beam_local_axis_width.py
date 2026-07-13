from types import SimpleNamespace

from app.core.mgt_parser import SectionDisplaySize, parse_elements_from_text
from app.main import FloorLoadAutoApp


def test_b2_beam_angle_zero_display_width_is_500mm():
    app = object.__new__(FloorLoadAutoApp)
    size = SectionDisplaySize(section_id=509, width=0.5, depth=0.7, plan_width=0.5, shape="SB", d1=0.7, d2=0.5)
    element = SimpleNamespace(elem_id=560, prop=509, angle_deg=0.0)

    assert app._beam_plan_display_width(element, size) == 0.5


def test_b2_beam_angle_90_display_width_projects_depth():
    app = object.__new__(FloorLoadAutoApp)
    size = SectionDisplaySize(section_id=509, width=0.5, depth=0.7, plan_width=0.5, shape="SB", d1=0.7, d2=0.5)
    element = SimpleNamespace(elem_id=560, prop=509, angle_deg=90.0)

    assert app._beam_plan_display_width(element, size) == 0.7


def test_beam_angle_45_display_width_projects_local_axes():
    app = object.__new__(FloorLoadAutoApp)
    size = SectionDisplaySize(section_id=509, width=0.5, depth=0.7, plan_width=0.5, shape="SB", d1=0.7, d2=0.5)
    element = SimpleNamespace(elem_id=560, prop=509, angle_deg=45.0)

    assert round(app._beam_plan_display_width(element, size), 6) == round((0.5 + 0.7) * 2**0.5 / 2.0, 6)


def test_parse_elements_preserves_frame_beta_angle():
    elements = parse_elements_from_text(
        """
*ELEMENT
560, BEAM, 1, 509, 10, 11, 90, 0
"""
    )

    assert elements[0].angle_deg == 90.0
