from gtui.core.color import (
    RGBA,
    contrast_ratio,
    distance,
    hue_family,
    is_neutral,
    lightness,
    oklch_css,
    parse_color,
    to_oklch,
)


def test_parse_rgb_and_rgba():
    assert parse_color("rgb(17, 17, 21)") == RGBA(17, 17, 21, 1.0)
    c = parse_color("rgba(94, 106, 210, 0.25)")
    assert c is not None and (c.r, c.g, c.b) == (94, 106, 210) and abs(c.a - 0.25) < 1e-9
    assert parse_color("rgba(0, 0, 0, 0)").transparent


def test_parse_modern_syntax_roundtrips_to_srgb():
    base = RGBA(94, 106, 210)
    L, C, h = to_oklch(base)
    back = parse_color(f"oklch({L} {C} {h})")
    assert back is not None and distance(back, base) < 0.005
    srgb = parse_color("color(srgb 0.3686 0.4157 0.8235)")
    assert srgb is not None and distance(srgb, base) < 0.005


def test_parse_hex_forms():
    assert parse_color("#fff") == RGBA(255, 255, 255)
    assert parse_color("#5E6AD2").hex == "#5e6ad2"
    assert parse_color("#00000080").a < 0.6


def test_oklch_css_formatting():
    assert oklch_css(RGBA(255, 255, 255)).startswith("oklch(1.000 0.000")
    assert oklch_css(RGBA(0, 0, 0, 0.5)).endswith("/ 0.50)")


def test_perceptual_helpers():
    assert lightness(RGBA(0, 0, 0)) < 0.05 < 0.95 < lightness(RGBA(255, 255, 255))
    assert is_neutral(RGBA(28, 28, 34))
    assert not is_neutral(RGBA(94, 106, 210))
    assert hue_family(RGBA(229, 72, 77)) == "red"
    assert hue_family(RGBA(48, 164, 108)) == "green"
    assert hue_family(RGBA(94, 106, 210)) in ("blue", "purple")
    assert abs(contrast_ratio(RGBA(0, 0, 0), RGBA(255, 255, 255)) - 21.0) < 0.01


def test_unparseable_returns_none():
    assert parse_color("currentcolor") is None
    assert parse_color("") is None
    assert parse_color(None) is None
