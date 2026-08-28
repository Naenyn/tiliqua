"""Production 1280x720 REZOMO build with firmware-owned UI control."""

from pathlib import Path

try:
    from .cpu_build import family_seed, run_family_cpu_cli
    from .top import RezoBeamTop, run_cli
except ImportError:
    from cpu_build import family_seed, run_family_cpu_cli
    from top import RezoBeamTop, run_cli


class RezomoCpuTop(RezoBeamTop):
    """REZOMO DSP/renderer plus the minimal REZO-family control CPU."""

    nextpnr_opts = (
        "--timing-allow-fail "
        f"--seed {family_seed('TILIQUA_REZOMO_CPU_SEED', '12')}")
    minimum_timing_headroom_percent = 3.0


FW_ROOT = Path(__file__).resolve().parent / "rezomo_cpu_fw"

if __name__ == "__main__":
    run_family_cpu_cli(
        run_cli,
        default_name="REZOMO",
        default_artifact_name="REZOMO",
        default_modeline="1280x720p60",
        fragment=RezomoCpuTop,
        firmware_root=FW_ROOT,
    )
