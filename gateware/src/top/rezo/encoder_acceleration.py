"""Shared encoder acceleration policy for the REZO family."""

from amaranth import Mux


# Detents completed within 20 ms at the 60 MHz UI clock are considered part
# of one deliberate fast turn. Acceleration ramps one step at a time instead
# of jumping directly from precise editing to the maximum multiplier.
ACCEL_WINDOW_CYCLES = 1_200_000
MAX_CONTINUOUS_STEP = 4


def progressive_edit_level(detent_timer, current_level, continuous, same_direction):
    """Return the encoded 0..3 level for a 1x..4x completed detent.

    The first detent, a slow detent, a direction reversal, and every discrete
    selector are all exactly one step. Sustained rapid movement in one
    direction advances through 1, 2, 3, 4 and remains capped at four.
    """
    accelerating = (
        continuous & same_direction &
        (detent_timer < ACCEL_WINDOW_CYCLES)
    )
    return Mux(
        accelerating,
        Mux(current_level.all(), MAX_CONTINUOUS_STEP - 1,
            current_level + 1),
        0,
    )
