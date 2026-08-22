"""Explicit build matrix for the consolidated REZO family.

Variant and display selection happens in Python before Amaranth elaboration.
The non-clocked REZO image therefore does not carry unused REZOMO clock logic.
"""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import runpy
import importlib.util
import sys


class Product(str, Enum):
    REZO = "rezo"
    REZOMO = "rezomo"
    STREZO = "strezo"


class Display(str, Enum):
    STANDARD = "standard"
    ROUND = "round"


@dataclass(frozen=True)
class BuildTarget:
    key: str
    product: Product
    display: Display
    module: str
    bitstream_name: str
    artifact_name: str
    modeline: str
    default_seed: int
    yosys: str | None = None
    nextpnr_ecp5: str | None = None
    ecppack: str | None = None


TARGETS = {
    "rezo": BuildTarget(
        key="rezo",
        product=Product.REZO,
        display=Display.STANDARD,
        module="rezo_variant",
        bitstream_name="REZO",
        artifact_name="REZO",
        modeline="1280x720p60",
        default_seed=2,
    ),
    "rezo_round": BuildTarget(
        key="rezo_round",
        product=Product.REZO,
        display=Display.ROUND,
        module="rezo_variant",
        bitstream_name="REZO",
        artifact_name="REZO-ROUND",
        modeline="720x720p60r2",
        default_seed=2,
        yosys="yosys",
    ),
    "rezomo": BuildTarget(
        key="rezomo",
        product=Product.REZOMO,
        display=Display.STANDARD,
        module="top",
        bitstream_name="REZOMO",
        artifact_name="REZOMO",
        modeline="1280x720p60",
        default_seed=9,
        yosys="yosys",
        nextpnr_ecp5="nextpnr-ecp5",
        ecppack="ecppack",
    ),
    "rezomo_round": BuildTarget(
        key="rezomo_round",
        product=Product.REZOMO,
        display=Display.ROUND,
        module="top",
        bitstream_name="REZOMO",
        artifact_name="REZOMO-ROUND",
        modeline="720x720p60r2",
        default_seed=4,
        yosys="yosys",
        nextpnr_ecp5="nextpnr-ecp5",
        ecppack="ecppack",
    ),
    "strezo": BuildTarget(
        key="strezo",
        product=Product.STREZO,
        display=Display.STANDARD,
        module="strezo_variant",
        bitstream_name="STREZO",
        artifact_name="STREZO",
        modeline="1280x720p60",
        default_seed=4,
        yosys="yosys",
        nextpnr_ecp5="nextpnr-ecp5",
        ecppack="ecppack",
    ),
    "strezo_round": BuildTarget(
        key="strezo_round",
        product=Product.STREZO,
        display=Display.ROUND,
        module="strezo_variant",
        bitstream_name="STREZO",
        artifact_name="STREZO-ROUND",
        modeline="720x720p60r2",
        default_seed=1,
        yosys="yosys",
        nextpnr_ecp5="nextpnr-ecp5",
        ecppack="ecppack",
    ),
}


def get_target(key):
    """Return one immutable build target, raising a useful error for typos."""
    try:
        return TARGETS[key]
    except KeyError as error:
        choices = ", ".join(sorted(TARGETS))
        raise ValueError(f"unknown REZO-family target {key!r}; choose {choices}") from error


def run_target(key):
    """Run one variant with the same ``__main__`` identity as its old branch."""
    target = get_target(key)
    seed_override = os.getenv("TILIQUA_REZO_FAMILY_SEED")
    if seed_override is not None:
        os.environ["TILIQUA_REZO_SEED"] = seed_override
    else:
        os.environ.setdefault("TILIQUA_REZO_SEED", str(target.default_seed))
    os.environ["TILIQUA_REZO_FAMILY_NAME"] = target.bitstream_name
    os.environ["TILIQUA_REZO_FAMILY_ARTIFACT_NAME"] = target.artifact_name
    os.environ["TILIQUA_REZO_FAMILY_MODELINE"] = target.modeline
    if target.yosys is not None:
        os.environ["YOSYS"] = os.getenv("TILIQUA_REZO_FAMILY_YOSYS", target.yosys)
    if target.nextpnr_ecp5 is not None:
        os.environ["NEXTPNR_ECP5"] = os.getenv(
            "TILIQUA_REZO_FAMILY_NEXTPNR_ECP5", target.nextpnr_ecp5)
    if target.ecppack is not None:
        os.environ["ECPPACK"] = os.getenv(
            "TILIQUA_REZO_FAMILY_ECPPACK", target.ecppack)
    variant_path = Path(__file__).with_name(f"{target.module}.py")
    if target.product in (Product.REZO, Product.STREZO):
        # The accepted REZO and STREZO images imported their journals as the
        # top-level module ``persistence``. Preserve those elaboration identities
        # even though the consolidated tree carries three different schemas.
        persistence_name = (
            "rezo_persistence.py"
            if target.product is Product.REZO
            else "strezo_persistence.py"
        )
        persistence_path = Path(__file__).with_name(persistence_name)
        spec = importlib.util.spec_from_file_location("persistence", persistence_path)
        persistence = importlib.util.module_from_spec(spec)
        previous = sys.modules.get("persistence")
        sys.modules["persistence"] = persistence
        try:
            spec.loader.exec_module(persistence)
            runpy.run_path(str(variant_path), run_name="__main__")
        finally:
            if previous is None:
                sys.modules.pop("persistence", None)
            else:
                sys.modules["persistence"] = previous
    else:
        runpy.run_path(str(variant_path), run_name="__main__")
