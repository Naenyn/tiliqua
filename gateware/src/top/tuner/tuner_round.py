# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Official 720x720 circular-display tuner build entry point."""

import os
from pathlib import Path
import runpy


if __name__ == "__main__":
    os.environ["TILIQUA_TUNER_MODELINE"] = "720x720p60r2"
    # Keep the round archive separate from the standard HDMI build directory.
    os.environ["TILIQUA_TUNER_NAME"] = "TUNER-ROUND"
    runpy.run_path(str(Path(__file__).with_name("top.py")), run_name="__main__")
