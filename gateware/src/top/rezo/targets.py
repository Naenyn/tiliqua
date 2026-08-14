"""Explicit build matrix for the consolidated REZO family.

Variant and display selection happens in Python before Amaranth elaboration.
The non-clocked REZO image therefore does not carry unused REZOMO clock logic.
"""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import runpy


class Product(str, Enum):
    REZO = "rezo"
    REZOMO = "rezomo"


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


TARGETS = {
    "rezo": BuildTarget(
        key="rezo",
        product=Product.REZO,
        display=Display.STANDARD,
        module="rezo_variant",
        bitstream_name="REZO",
        artifact_name="REZO",
        modeline="1280x720p60",
        default_seed=8,
    ),
    "rezo_round": BuildTarget(
        key="rezo_round",
        product=Product.REZO,
        display=Display.ROUND,
        module="rezo_variant",
        bitstream_name="REZO",
        artifact_name="REZO-ROUND",
        modeline="720x720p60r2",
        default_seed=8,
    ),
    "rezomo": BuildTarget(
        key="rezomo",
        product=Product.REZOMO,
        display=Display.STANDARD,
        module="top",
        bitstream_name="REZOMO",
        artifact_name="REZOMO",
        modeline="1280x720p60",
        default_seed=6,
    ),
    "rezomo_round": BuildTarget(
        key="rezomo_round",
        product=Product.REZOMO,
        display=Display.ROUND,
        module="top",
        bitstream_name="REZOMO",
        artifact_name="REZOMO-ROUND",
        modeline="720x720p60r2",
        default_seed=3,
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
    variant_path = Path(__file__).with_name(f"{target.module}.py")
    runpy.run_path(str(variant_path), run_name="__main__")
