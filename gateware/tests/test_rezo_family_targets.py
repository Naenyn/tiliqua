from pathlib import Path

import pytest

from top.rezo import targets
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
        (Product.STREZO, Display.STANDARD),
        (Product.STREZO, Display.ROUND),
    }


def test_family_targets_have_isolated_artifacts_and_expected_modelines():
    assert len({target.artifact_name for target in TARGETS.values()}) == 6
    assert TARGETS["rezo_round"].bitstream_name == "REZO"
    assert TARGETS["rezomo_round"].bitstream_name == "REZOMO"
    assert TARGETS["strezo_round"].bitstream_name == "STREZO"
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
    assert TARGETS["strezo"].module == "strezo_variant"
    assert TARGETS["strezo_round"].module == "strezo_variant"
    assert TARGETS["rezo"].default_seed == 9
    assert TARGETS["rezo_round"].default_seed == 2
    assert TARGETS["rezomo"].default_seed == 9
    assert TARGETS["rezomo_round"].default_seed == 4
    assert TARGETS["strezo"].default_seed == 7
    assert TARGETS["strezo_round"].default_seed == 1
    assert TARGETS["rezo_round"].yosys == "yosys"
    assert TARGETS["rezo"].yosys is None
    for key in ("rezomo", "rezomo_round", "strezo", "strezo_round"):
        assert TARGETS[key].yosys == "yosys"
        assert TARGETS[key].nextpnr_ecp5 == "nextpnr-ecp5"
        assert TARGETS[key].ecppack == "ecppack"


def test_family_target_lookup_rejects_ambiguous_names():
    with pytest.raises(
            ValueError,
            match=("choose rezo, rezo_round, rezomo, rezomo_round, "
                   "strezo, strezo_round")):
        get_target("round")


def test_family_runner_preserves_variant_main_identity(monkeypatch):
    called = {}

    def fake_run_path(path, run_name):
        called.update(path=Path(path).name, run_name=run_name)

    monkeypatch.delenv("TILIQUA_REZO_SEED", raising=False)
    monkeypatch.setattr(targets.runpy, "run_path", fake_run_path)
    targets.run_target("rezomo_round")
    assert called == {"path": "top.py", "run_name": "__main__"}
    assert targets.os.environ["TILIQUA_REZO_SEED"] == "4"
    assert targets.os.environ["TILIQUA_REZO_FAMILY_NAME"] == "REZOMO"
    assert targets.os.environ["TILIQUA_REZO_FAMILY_ARTIFACT_NAME"] == "REZOMO-ROUND"
    assert targets.os.environ["TILIQUA_REZO_FAMILY_MODELINE"] == "720x720p60r2"
