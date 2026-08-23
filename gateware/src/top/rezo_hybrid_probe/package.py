"""Package an already-routed hybrid probe bitstream and firmware."""

from pathlib import Path

from tiliqua.build.archive import ArchiveBuilder
from tiliqua.build.types import BitstreamHelp, ExternalPLLConfig
from tiliqua.platform import TiliquaRevision


BUILD_PATH = Path(__file__).resolve().parents[3] / \
    "build" / "rezo-hybrid-control-probe-r5"

builder = ArchiveBuilder(
    build_path=str(BUILD_PATH),
    name="REZO-HYBRID-PROBE",
    artifact_name="REZO-HYBRID-CONTROL-PROBE",
    tag="12e68232",
    hw_rev=TiliquaRevision.R5,
    external_pll_config=ExternalPLLConfig(
        clk0_hz=49_152_000,
        clk1_inherit=False,
        clk1_hz=74_250_000,
        spread_spectrum=0.01,
    ),
    bitstream_help=BitstreamHelp(
        brief="Experimental REZO CPU/hardware UI split.",
        io_left=[
            "audio / CV input", "audio / CV input",
            "audio / CV input", "audio / CV input",
            "assignable out", "assignable out",
            "assignable out", "assignable out",
        ],
        io_right=["", "", "video out req.", "", "", ""],
        video="1280x720p60",
    ),
)
builder.with_option_storage()
builder.with_bitstream().create()
