from gtui.inference.synthesizer import synthesize
from gtui.ir.schema import AestheticProfile, is_unknown


def test_color_roles_are_inferred_from_usage(synthetic):
    p = synthesize(synthetic)
    c = p.tokens.colors
    assert c["surface.base"].value == "#111115"
    assert c["surface.base"].source_names == ["--color-bg-primary"]
    assert c["surface.raised"].value == "#1c1c22"
    assert c["text.primary"].value == "#f7f7f8"
    assert c["text.secondary"].value == "#a0a0a9"
    assert c["accent.primary"].value == "#5e6ad2"
    assert c["accent.primary"].source_names == ["--color-accent"]
    assert c["accent.hover"].value == "#6f7ae0"
    assert c["text.on_accent"].value == "#ffffff"
    assert c["border.subtle"].value == "#26262c"
    assert c["status.danger"].value == "#e5484d"
    assert c["status.success"].value == "#30a46c"
    for tok in c.values():
        assert tok.evidence, f"{tok.role} has no evidence"
        assert 0 <= tok.confidence <= 1


def test_typography_scale_and_body(synthetic):
    p = synthesize(synthetic)
    t = p.tokens.typography
    assert t.body == "base"
    assert t.scale["base"].size == 14
    # steps are named by position around the body size; 24px is the next step up here
    assert t.scale["lg"].size == 24
    assert list(t.scale) == ["2xs", "xs", "sm", "base", "lg"]
    assert t.families["sans"].primary == "Inter"
    assert t.heading_weight == 600
    assert t.heading_tracking == -0.02


def test_spacing_radius_motion(synthetic):
    p = synthesize(synthetic)
    assert p.tokens.spacing.base == 4
    assert {6.0, 10.0} <= {v.value for v in p.tokens.radius.values()}
    assert p.tokens.motion.durations == {"base": 120}
    assert not p.tokens.shadows  # genuinely flat


def test_component_recipes(synthetic):
    p = synthesize(synthetic)
    kinds = {(c.kind, c.variant) for c in p.components}
    assert ("button", "primary") in kinds
    assert ("button", "ghost") in kinds
    assert ("input", "default") in kinds
    assert ("card", "default") in kinds
    assert ("nav_item", "default") in kinds
    primary = next(c for c in p.components if c.kind == "button" and c.variant == "primary")
    assert primary.properties["background"] == "accent.primary"
    assert primary.properties["text"] == "text.on_accent"
    assert primary.properties["height"] == 32
    assert primary.properties["radius"] == "md"
    assert "hover" in primary.states
    assert primary.states["hover"].changes["background-color"] == "accent.hover"
    card = next(c for c in p.components if c.kind == "card")
    assert card.properties["elevation"] == "border"
    assert card.properties["border"]["color"] == "border.subtle"


def test_character_and_principles(synthetic):
    p = synthesize(synthetic)
    assert p.character.color_scheme == "dark"
    assert p.character.density == "compact"
    assert p.character.depth == "flat"
    ids = {pr.id for pr in p.principles}
    assert "borders-over-shadows" in ids
    assert "accent-restraint" in ids
    assert "spacing-grid" in ids
    for pr in p.principles:
        if pr.kind == "invariant" and pr.id not in ("tight-heading-tracking", "stable-type"):
            assert pr.evidence, pr.id


def test_unknowns_are_explicit_not_invented(synthetic):
    p = synthesize(synthetic)
    assert is_unknown(p.tokens.typography.families["mono"])
    assert any(u.startswith("shadows") for u in p.unknowns)
    # round-trip keeps Unknown as Unknown and never turns it into a value
    again = AestheticProfile.model_validate_json(p.model_dump_json())
    assert is_unknown(again.tokens.typography.families["mono"])
    assert again.tokens.motion.durations == {"base": 120}


def test_profile_round_trip_is_stable(synthetic):
    p = synthesize(synthetic)
    dumped = p.model_dump_json()
    again = AestheticProfile.model_validate_json(dumped)
    assert again.model_dump_json() == dumped
