from core.chart_annotation_builder import build_public_drawings_from_setup


def test_public_drawings_from_setup_has_lines_when_present():
    drawings = build_public_drawings_from_setup(entry=2000.0, sl=1990.0, tp=2020.0)
    line_count = sum(1 for d in drawings if d.kind == "line")
    assert line_count >= 3


def test_public_drawings_from_setup_empty_when_all_none():
    drawings = build_public_drawings_from_setup(entry=None, sl=None, tp=None)
    assert drawings == []
