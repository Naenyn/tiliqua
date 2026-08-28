"""Production 1280x720 REZOMO build with firmware-owned UI control."""

import os
from pathlib import Path

from tiliqua.tiliqua_soc import TiliquaSoc

try:
    from .top import RezoBeamTop, run_cli
except ImportError:
    from top import RezoBeamTop, run_cli


class RezomoCpuTop(RezoBeamTop):
    """REZOMO DSP/renderer plus the minimal REZO-family control CPU."""

    nextpnr_opts = (
        "--timing-allow-fail "
        f"--seed {os.getenv('TILIQUA_REZO_FAMILY_SEED', os.getenv('TILIQUA_REZOMO_CPU_SEED', '12'))}")
    minimum_timing_headroom_percent = 3.0


FW_ROOT = Path(__file__).resolve().parent / "rezomo_cpu_fw"


def compile_firmware(args):
    artifact_name = args.artifact_name or args.name
    build_path = Path("build").resolve() / \
        f"{artifact_name.lower()}-{args.hw.value}"
    build_path.mkdir(parents=True, exist_ok=True)
    firmware_bin_path = build_path / "firmware.bin"
    TiliquaSoc.compile_firmware(str(FW_ROOT), str(firmware_bin_path))
    return {"firmware_bin_path": str(firmware_bin_path)}


if __name__ == "__main__":
    run_cli(
        name=os.getenv("TILIQUA_REZO_FAMILY_NAME", "REZOMO"),
        artifact_name=os.getenv(
            "TILIQUA_REZO_FAMILY_ARTIFACT_NAME", "REZOMO"),
        modeline=os.getenv(
            "TILIQUA_REZO_FAMILY_MODELINE", "1280x720p60"),
        fragment=RezomoCpuTop,
        argparse_fragment=compile_firmware,
    )
