"""Shared build plumbing for CPU-backed REZO-family targets."""

from functools import partial
import os
from pathlib import Path

from tiliqua.tiliqua_soc import TiliquaSoc


def family_seed(product_variable, default):
    """Return the family seed override, then the legacy product override."""
    return os.getenv(
        "TILIQUA_REZO_FAMILY_SEED",
        os.getenv(product_variable, default),
    )


def compile_firmware(firmware_root, args):
    """Build one product firmware image into its selected artifact folder."""
    artifact_name = args.artifact_name or args.name
    build_path = Path("build").resolve() / \
        f"{artifact_name.lower()}-{args.hw.value}"
    build_path.mkdir(parents=True, exist_ok=True)
    firmware_bin_path = build_path / "firmware.bin"
    TiliquaSoc.compile_firmware(str(firmware_root), str(firmware_bin_path))
    return {"firmware_bin_path": str(firmware_bin_path)}


def run_family_cpu_cli(run_cli, *, default_name, default_artifact_name,
                       default_modeline, fragment, firmware_root):
    """Launch a CPU-backed product with the common family environment API."""
    run_cli(
        name=os.getenv("TILIQUA_REZO_FAMILY_NAME", default_name),
        artifact_name=os.getenv(
            "TILIQUA_REZO_FAMILY_ARTIFACT_NAME", default_artifact_name),
        modeline=os.getenv(
            "TILIQUA_REZO_FAMILY_MODELINE", default_modeline),
        fragment=fragment,
        argparse_fragment=partial(compile_firmware, firmware_root),
    )
