"""CPU-only production build matrix for the consolidated REZO family."""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import runpy


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


TARGETS = {
    "rezo": BuildTarget(
        key="rezo",
        product=Product.REZO,
        display=Display.STANDARD,
        module="rezo_cpu",
        bitstream_name="REZO",
        artifact_name="REZO",
        modeline="1280x720p60",
        default_seed=5,
    ),
    "rezo_round": BuildTarget(
        key="rezo_round",
        product=Product.REZO,
        display=Display.ROUND,
        module="rezo_cpu",
        bitstream_name="REZO",
        artifact_name="REZO-ROUND",
        modeline="720x720p60r2",
        default_seed=2,
    ),
    "rezomo": BuildTarget(
        key="rezomo",
        product=Product.REZOMO,
        display=Display.STANDARD,
        module="rezomo_cpu",
        bitstream_name="REZOMO",
        artifact_name="REZOMO",
        modeline="1280x720p60",
        default_seed=12,
    ),
    "rezomo_round": BuildTarget(
        key="rezomo_round",
        product=Product.REZOMO,
        display=Display.ROUND,
        module="rezomo_cpu",
        bitstream_name="REZOMO",
        artifact_name="REZOMO-ROUND",
        modeline="720x720p60r2",
        default_seed=12,
    ),
    "strezo": BuildTarget(
        key="strezo",
        product=Product.STREZO,
        display=Display.STANDARD,
        module="strezo_cpu",
        bitstream_name="STREZO",
        artifact_name="STREZO",
        modeline="1280x720p60",
        default_seed=8,
    ),
    "strezo_round": BuildTarget(
        key="strezo_round",
        product=Product.STREZO,
        display=Display.ROUND,
        module="strezo_cpu",
        bitstream_name="STREZO",
        artifact_name="STREZO-ROUND",
        modeline="720x720p60r2",
        default_seed=7,
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
    os.environ["TILIQUA_REZO_FAMILY_SEED"] = os.getenv(
        "TILIQUA_REZO_FAMILY_SEED", str(target.default_seed))
    os.environ["TILIQUA_REZO_FAMILY_NAME"] = target.bitstream_name
    os.environ["TILIQUA_REZO_FAMILY_ARTIFACT_NAME"] = target.artifact_name
    os.environ["TILIQUA_REZO_FAMILY_MODELINE"] = target.modeline
    cpu_path = Path(__file__).with_name(f"{target.module}.py")
    runpy.run_path(str(cpu_path), run_name="__main__")
