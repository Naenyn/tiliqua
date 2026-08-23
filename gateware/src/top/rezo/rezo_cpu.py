"""Production 1280x720 REZO build with firmware-owned UI control."""

import os
from pathlib import Path

from tiliqua.tiliqua_soc import TiliquaSoc

try:
    from .rezo_variant import RezoBeamTop, run_cli
except ImportError:
    from rezo_variant import RezoBeamTop, run_cli


class RezoCpuTop(RezoBeamTop):
    """REZO DSP/renderer gateware plus the minimal UI control CPU."""

    # Let nextpnr finish and emit the complete report even when an intermediate
    # estimate misses timing. The post-route Python gate below is authoritative
    # and rejects both failures and marginal routes before packaging.
    nextpnr_opts = (
        "--timing-allow-fail "
        f"--seed {os.getenv('TILIQUA_REZO_CPU_SEED', '1')}")
    # Seed 1 is qualified on hardware. Its weakest measured clock margin is
    # 3.66%, so retain a 3% release gate while leaving a small tool-version
    # tolerance.
    minimum_timing_headroom_percent = 3.0


FW_ROOT = Path(__file__).resolve().parents[1] / "rezo_hybrid_probe" / "fw"


def compile_firmware(args):
    """Build the firmware image directly into this target's build folder."""
    artifact_name = args.artifact_name or args.name
    build_path = Path("build").resolve() / \
        f"{artifact_name.lower()}-{args.hw.value}"
    build_path.mkdir(parents=True, exist_ok=True)
    firmware_bin_path = build_path / "firmware.bin"
    TiliquaSoc.compile_firmware(str(FW_ROOT), str(firmware_bin_path))
    return {"firmware_bin_path": str(firmware_bin_path)}


if __name__ == "__main__":
    run_cli(
        name="REZO",
        artifact_name="REZO-CPU",
        modeline="1280x720p60",
        fragment=RezoCpuTop,
        argparse_fragment=compile_firmware,
    )
