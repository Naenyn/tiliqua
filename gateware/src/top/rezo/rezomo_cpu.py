"""Production 1280x720 REZOMO build with firmware-owned UI control."""

import os
from pathlib import Path

import git

from tiliqua.tiliqua_soc import TiliquaSoc

try:
    from .top import RezoBeamTop, run_cli
except ImportError:
    from top import RezoBeamTop, run_cli


class RezomoCpuTop(RezoBeamTop):
    """REZOMO DSP/renderer plus the minimal REZO-family control CPU."""

    nextpnr_opts = (
        "--timing-allow-fail "
        f"--seed {os.getenv('TILIQUA_REZOMO_CPU_SEED', '11')}")
    minimum_timing_headroom_percent = 3.0


FW_ROOT = Path(__file__).resolve().parent / "rezomo_cpu_fw"


def compile_firmware(args):
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
        "version_text": version_text[:8],
    }


if __name__ == "__main__":
    run_cli(
        name="REZOMO",
        artifact_name="REZOMO-CPU",
        modeline="1280x720p60",
        fragment=RezomoCpuTop,
        argparse_fragment=compile_firmware,
    )
