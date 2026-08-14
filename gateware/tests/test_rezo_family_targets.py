import pytest

from top.rezo.targets import Display, Product, TARGETS, get_target


def test_family_exposes_complete_product_display_matrix():
    assert {
        (target.product, target.display)
        for target in TARGETS.values()
    } == {
        (Product.REZO, Display.STANDARD),
        (Product.REZO, Display.ROUND),
        (Product.REZOMO, Display.STANDARD),
        (Product.REZOMO, Display.ROUND),
    }


def test_family_targets_have_isolated_names_and_expected_modelines():
    assert len({target.bitstream_name for target in TARGETS.values()}) == 4
    for target in TARGETS.values():
        expected = (
            "1280x720p60"
            if target.display is Display.STANDARD
            else "720x720p60r2"
        )
        assert target.modeline == expected


def test_family_variants_are_selected_before_elaboration():
    assert TARGETS["rezo"].module == "rezo_variant"
    assert TARGETS["rezo_round"].module == "rezo_variant"
    assert TARGETS["rezomo"].module == "top"
    assert TARGETS["rezomo_round"].module == "top"


def test_family_target_lookup_rejects_ambiguous_names():
    with pytest.raises(ValueError, match="choose rezo, rezo_round, rezomo, rezomo_round"):
        get_target("round")
