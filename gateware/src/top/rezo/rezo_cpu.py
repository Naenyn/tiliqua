"""Production 1280x720 REZO build with firmware-owned UI control."""

from pathlib import Path

try:
    from .cpu_build import family_seed, run_family_cpu_cli
    from .rezo_variant import RezoBeamTop, run_cli
except ImportError:
    from cpu_build import family_seed, run_family_cpu_cli
    from rezo_variant import RezoBeamTop, run_cli


class RezoCpuTop(RezoBeamTop):
    """REZO DSP/renderer gateware plus the minimal UI control CPU."""

    # Let nextpnr finish and emit the complete report even when an intermediate
    # estimate misses timing. The post-route Python gate below is authoritative
    # and rejects both failures and marginal routes before packaging.
    nextpnr_opts = (
        "--timing-allow-fail "
        f"--seed {family_seed('TILIQUA_REZO_CPU_SEED', '5')}")
    # Seed 5 is qualified for the aligned pager renderer. Retain the 3% gate so
    # marginal routes are rejected rather than silently packaged.
    minimum_timing_headroom_percent = 3.0


FW_ROOT = Path(__file__).resolve().parent / "cpu_fw"

if __name__ == "__main__":
    run_family_cpu_cli(
        run_cli,
        default_name="REZO",
        default_artifact_name="REZO",
        default_modeline="1280x720p60",
        fragment=RezoCpuTop,
        firmware_root=FW_ROOT,
    )
