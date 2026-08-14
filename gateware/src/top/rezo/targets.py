"""Explicit build matrix for the consolidated REZO family.

Variant and display selection happens in Python before Amaranth elaboration.
The non-clocked REZO image therefore does not carry unused REZOMO clock logic.
"""

from dataclasses import dataclass
from enum import Enum
import importlib
import os


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
    modeline: str
    default_seed: int


TARGETS = {
    "rezo": BuildTarget(
        key="rezo",
        product=Product.REZO,
        display=Display.STANDARD,
        module="rezo_variant",
        bitstream_name="REZO",
        modeline="1280x720p60",
        default_seed=8,
    ),
    "rezo_round": BuildTarget(
        key="rezo_round",
        product=Product.REZO,
        display=Display.ROUND,
        module="rezo_variant",
        bitstream_name="REZO-ROUND",
        modeline="720x720p60r2",
        default_seed=8,
    ),
    "rezomo": BuildTarget(
        key="rezomo",
        product=Product.REZOMO,
        display=Display.STANDARD,
        module="rezomo_variant",
        bitstream_name="REZOMO",
        modeline="1280x720p60",
        default_seed=3,
    ),
    "rezomo_round": BuildTarget(
        key="rezomo_round",
        product=Product.REZOMO,
        display=Display.ROUND,
        module="rezomo_variant",
        bitstream_name="REZOMO-ROUND",
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


def _import_variant(module_name):
    if __package__:
        return importlib.import_module(f"{__package__}.{module_name}")
    return importlib.import_module(module_name)


def run_target(key):
    """Run the existing Tiliqua CLI for one explicit family target."""
    target = get_target(key)
    seed_override = os.getenv("TILIQUA_REZO_FAMILY_SEED")
    if seed_override is not None:
        os.environ["TILIQUA_REZO_SEED"] = seed_override
    else:
        os.environ.setdefault("TILIQUA_REZO_SEED", str(target.default_seed))
    variant = _import_variant(target.module)
    variant.run_cli(name=target.bitstream_name, modeline=target.modeline)
