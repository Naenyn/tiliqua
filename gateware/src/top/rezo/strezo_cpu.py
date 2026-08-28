"""Production 1280x720 STREZO build with firmware-owned UI control."""

from pathlib import Path

try:
    from .cpu_build import family_seed, run_family_cpu_cli
    from .strezo_variant import RezoBeamTop, run_cli
except ImportError:
    from cpu_build import family_seed, run_family_cpu_cli
    from strezo_variant import RezoBeamTop, run_cli


class StrezoCpuTop(RezoBeamTop):
    """STREZO DSP/renderer plus the minimal REZO-family control CPU."""

    nextpnr_opts = (
        "--timing-allow-fail "
        "--placer-heap-timingweight 20 "
        f"--seed {family_seed('TILIQUA_STREZO_CPU_SEED', '7')}")
    minimum_timing_headroom_percent = 3.0


FW_ROOT = Path(__file__).resolve().parent / "strezo_cpu_fw"

if __name__ == "__main__":
    run_family_cpu_cli(
        run_cli,
        default_name="STREZO",
        default_artifact_name="STREZO",
        default_modeline="1280x720p60",
        fragment=StrezoCpuTop,
        firmware_root=FW_ROOT,
    )
