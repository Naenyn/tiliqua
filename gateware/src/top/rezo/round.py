"""Official 720x720 circular-display build of REZOMO."""

import os

# This target has a different pixel clock and placement solution from the
# standard preview. Preserve an explicit caller override for route searches.
os.environ.setdefault("TILIQUA_REZO_SEED", "6")

from top import run_cli


if __name__ == "__main__":
    run_cli(name="REZOMO", modeline="720x720p60r2")
