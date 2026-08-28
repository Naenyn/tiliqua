import re
from pathlib import Path

import pytest

from top.rezo import targets
from top.rezo.cpu_control import (
    RezoCpuControlPlane,
    RezomoCpuControlPlane,
    StrezoCpuControlPlane,
)
from top.rezo.targets import Display, Product, TARGETS, get_target
from top.rezo.ui_specs import RezoUISpec, RezomoUISpec, StrezoUISpec


COMMON_UI_TARGETS = {
    "TARGET_PAGE": "PAGE",
    "TARGET_PRESET": "PRESET",
    "TARGET_BAND_BASE": "BAND",
    "TARGET_DRIVE": "DRIVE",
    "TARGET_RESONANCE": "RESONANCE",
    "TARGET_FEEDBACK": "FEEDBACK",
    "TARGET_LIMIT_KNEE": "KNEE",
    "TARGET_LIMIT_CAP": "CEILING",
    "TARGET_DAMP": "DAMP",
    "TARGET_INPUT_BASE": "INPUT",
    "TARGET_GROUP_BASE": "GROUP",
    "TARGET_OUTPUT_BASE": "OUTPUT",
    "TARGET_FEEDBACK_SEND_BASE": "FEEDBACK_ENABLE",
    "TARGET_PALETTE": "PALETTE",
    "TARGET_SAVE_DEFAULT": "SAVE",
    "TARGET_BAND_LAYOUT": "LAYOUT",
    "TARGET_BAND_ENABLE_BASE": "ENABLE",
    "TARGET_BAND_FREQ_BASE": "FREQUENCY",
}


@pytest.mark.parametrize(
    ("firmware_dir", "ui_spec", "product_targets"),
    (
        ("cpu_fw", RezoUISpec, {
            "TARGET_MODE": "MODE",
            "TARGET_FILTER_TYPE": "FILTER_TYPE",
            "TARGET_FILTER_CUTOFF": "CUTOFF",
            "TARGET_FILTER_SLOPE": "SLOPE",
            "TARGET_FILTER_WIDTH": "WIDTH",
            "TARGET_FILTER_CV_BASE": "FILTER_MATRIX",
        }),
        ("rezomo_cpu_fw", RezomoUISpec, {
            "TARGET_MODE": "MODE",
            "TARGET_SHIFT_DIRECTION": "SHIFT_DIRECTION",
            "TARGET_CLOCK_ALGORITHM": "CLOCK_ALGORITHM",
            "TARGET_TURING_LENGTH": "TURING_LENGTH",
            "TARGET_TURING_CHANGE": "TURING_CHANGE",
            "TARGET_CLOCK_SOURCE": "CLOCK_SOURCE",
            "TARGET_CLOCK_RATE": "CLOCK_RATE",
            "TARGET_CLOCK_DEPTH": "CLOCK_DEPTH",
            "TARGET_TURING_TARGET": "TURING_TARGET",
            "TARGET_TURING_START": "TURING_START",
            "TARGET_DATA_SOURCE": "DATA_SOURCE",
        }),
        ("strezo_cpu_fw", StrezoUISpec, {
            "TARGET_CROSS_LAYOUT": "CROSS_LAYOUT",
            "TARGET_MOTION_SOURCE": "MOTION_SOURCE",
            "TARGET_MOTION_RATE": "MOTION_RATE",
            "TARGET_MOTION_PHASE": "MOTION_PHASE",
            "TARGET_CROSS_MATRIX_BASE": "CROSS_CELL",
            "TARGET_CROSS_FEEDBACK": "CROSS_FEEDBACK",
            "TARGET_OUTPUT_SIDE_BASE": "OUTPUT_SIDE_TARGET",
            "TARGET_CROSS_ROW_BASE": "CROSS_ROW",
            "TARGET_CROSS_COL_BASE": "CROSS_COL",
            "TARGET_SAME_FEEDBACK": "SAME_FEEDBACK",
        }),
    ),
)
def test_renderer_ui_specs_match_firmware_targets(
        firmware_dir, ui_spec, product_targets):
    main_rs = (
        Path(__file__).parents[1] / "src" / "top" / "rezo" /
        firmware_dir / "src" / "main.rs"
    ).read_text()
    rust_targets = {
        name: int(value)
        for name, value in re.findall(
            r"^const ([A-Z_]+): u8 = (\d+);$", main_rs, re.MULTILINE)
    }

    for spec_name, rust_name in (COMMON_UI_TARGETS | product_targets).items():
        assert getattr(ui_spec, spec_name) == rust_targets[rust_name]


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
    assert TARGETS["rezo"].module == "rezo_cpu"
    assert TARGETS["rezo_round"].module == "rezo_cpu"
    assert TARGETS["rezomo"].module == "rezomo_cpu"
    assert TARGETS["rezomo_round"].module == "rezomo_cpu"
    assert TARGETS["strezo"].module == "strezo_cpu"
    assert TARGETS["strezo_round"].module == "strezo_cpu"
    assert TARGETS["rezo"].default_seed == 5
    assert TARGETS["rezo_round"].default_seed == 2
    assert TARGETS["rezomo"].default_seed == 12
    assert TARGETS["rezomo_round"].default_seed == 12
    assert TARGETS["strezo"].default_seed == 7
    assert TARGETS["strezo_round"].default_seed == 7


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

    monkeypatch.delenv("TILIQUA_REZO_FAMILY_SEED", raising=False)
    monkeypatch.setattr(targets.runpy, "run_path", fake_run_path)
    targets.run_target("rezomo_round")
    assert called == {"path": "rezomo_cpu.py", "run_name": "__main__"}
    assert targets.os.environ["TILIQUA_REZO_FAMILY_SEED"] == "12"
    assert targets.os.environ["TILIQUA_REZO_FAMILY_NAME"] == "REZOMO"
    assert targets.os.environ["TILIQUA_REZO_FAMILY_ARTIFACT_NAME"] == \
        "REZOMO-ROUND"
    assert targets.os.environ["TILIQUA_REZO_FAMILY_MODELINE"] == "720x720p60r2"


def test_family_cpu_planes_share_generated_core_and_address_map():
    planes = [
        cls(None, firmware_bin_path=__file__)
        for cls in (
            RezoCpuControlPlane,
            RezomoCpuControlPlane,
            StrezoCpuControlPlane,
        )
    ]

    # Product UI peripherals and physical firmware ROM capacity may differ,
    # but the CPU-visible regions must not silently generate different cores.
    assert len({plane.cpu._source_file for plane in planes}) == 1
    assert {plane.MAINRAM_SIZE for plane in planes} == {0x10000}
    assert {plane.DATA_BASE for plane in planes} == {0x8000}
    assert {plane.DATA_SIZE for plane in planes} == {0x0800}
    assert [plane.CODE_SIZE for plane in planes] == [0x4000, 0x5000, 0x5000]


@pytest.mark.parametrize(
    ("firmware_dir", "code_size"),
    (("cpu_fw", 0x4000), ("rezomo_cpu_fw", 0x5000),
     ("strezo_cpu_fw", 0x5000)),
)
def test_family_linker_maps_match_cpu_fabric(firmware_dir, code_size):
    memory_x = (
        Path(__file__).parents[1] / "src" / "top" / "rezo" /
        firmware_dir / "memory.x"
    ).read_text()

    assert "ORIGIN = 0x00000000" in memory_x
    assert f"LENGTH = 0x{code_size:08x}" in memory_x
    assert "ORIGIN = 0x00008000" in memory_x
    assert "LENGTH = 0x00000800" in memory_x

    # Linker scripts are passed to rustc through rustflags, so Cargo cannot
    # infer this dependency on its own. Without the build-script directive a
    # memory-map-only change can silently reuse an executable linked for the
    # previous RAM address.
    build_rs = (
        Path(__file__).parents[1] / "src" / "top" / "rezo" /
        firmware_dir / "build.rs"
    ).read_text()
    assert "cargo:rerun-if-changed=memory.x" in build_rs
