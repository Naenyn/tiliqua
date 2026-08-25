"""Production 1280x720 STREZO build with firmware-owned UI control."""

import os
from pathlib import Path

from tiliqua.tiliqua_soc import TiliquaSoc

try:
    from .strezo_variant import RezoBeamTop, run_cli
except ImportError:
    from strezo_variant import RezoBeamTop, run_cli


class StrezoCpuTop(RezoBeamTop):
    """STREZO DSP/renderer plus the minimal REZO-family control CPU."""

    nextpnr_opts = (
        "--timing-allow-fail "
        f"--seed {os.getenv('TILIQUA_STREZO_CPU_SEED', '8')}")
    minimum_timing_headroom_percent = 3.0


FW_ROOT = Path(__file__).resolve().parent / "strezo_cpu_fw"


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
        name="STREZO",
        artifact_name="STREZO-CPU",
        modeline="1280x720p60",
        fragment=StrezoCpuTop,
        argparse_fragment=compile_firmware,
    )
