"""Production 1280x720 REZO build with firmware-owned UI control."""

import os
from pathlib import Path

import git

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
        "--placer-heap-timingweight 20 "
        f"--seed {os.getenv('TILIQUA_REZO_CPU_SEED', '5')}")
    # Seed 5 is qualified for the aligned pager renderer. Retain the 3% gate so
    # marginal routes are rejected rather than silently packaged.
    minimum_timing_headroom_percent = 3.0


FW_ROOT = Path(__file__).resolve().parent / "cpu_fw"


def compile_firmware(args):
    """Build the firmware image directly into this target's build folder."""
    artifact_name = args.artifact_name or args.name
    build_path = Path("build").resolve() / \
        f"{artifact_name.lower()}-{args.hw.value}"
    build_path.mkdir(parents=True, exist_ok=True)
    firmware_bin_path = build_path / "firmware.bin"
    TiliquaSoc.compile_firmware(str(FW_ROOT), str(firmware_bin_path))
    repo = git.Repo(search_parent_directories=True)
    try:
        version_text = repo.git.describe("--tags", "--exact-match", "--dirty")
    except git.exc.GitCommandError:
        version_text = repo.git.describe("--always", "--dirty")
    return {
        "firmware_bin_path": str(firmware_bin_path),
        # Match the archive/bootloader tag width used by top_level_cli.
        "version_text": version_text[:8],
    }


if __name__ == "__main__":
    run_cli(
        name="REZO",
        artifact_name="REZO-CPU",
        modeline="1280x720p60",
        fragment=RezoCpuTop,
        argparse_fragment=compile_firmware,
    )
