# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Shared feedback-loop shaping primitives for the REZO family."""

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out


# Each DAMP profile is expressed as sums of powers of two of the effective
# feedback amount. This keeps the mapping out of the scarce multiplier budget
# while giving each instrument a deliberate decay character.
DAMP_PROFILES = {
    # Collective bank: progressively raise the self-oscillation threshold.
    "rezo": ((), (5,), (4,), (3,), (2,)),
    # Pattern memory: gentler damping preserves long, articulated recurrences.
    "rezomo": ((), (6,), (5,), (4,), (3,)),
    # Stereo routes can reinforce twice; the upper modes restrain them harder.
    "strezo": ((), (4,), (3,), (2,), (2, 3)),
}


def feedback_gain_from_control(control):
    """Map the full 0..0x8000 control range to 0..0x7c00 monotonically."""
    return control - (control >> 5)


def feedback_damping(feedback, mode, profile):
    """Return one multiplier-free feedback-dependent resonance reduction."""
    choices = []
    for shifts in DAMP_PROFILES[profile]:
        value = Const(0, 17)
        for shift in shifts:
            value = value + (feedback >> shift)
        choices.append(value)
    return Array(choices)[Mux(mode > 4, 4, mode)]


def feedback_damping_reference(feedback, mode, profile):
    """Integer reference for the profile table used by simulations."""
    shifts = DAMP_PROFILES[profile][min(max(mode, 0), 4)]
    return sum(feedback >> shift for shift in shifts)


def resonance_control(resonance, damping):
    """Convert resonance amount to inverse-Q without a high-end plateau."""
    damped = Mux(resonance > damping, resonance - damping, 0)
    return 16384 - (damped >> 1)


def resonance_control_reference(resonance, damping):
    return 16384 - (max(resonance - damping, 0) >> 1)


class FeedbackShaper(wiring.Component):
    """Monotonic wide-domain quadratic feedback shaper.

    ``drive`` is intentionally wider than the codec sample.  The former
    implementation first clamped a multi-band feedback sum to Q1.15 and only
    then applied its quadratic knee, making every overload above full scale
    indistinguishable.  This component retains two full-scale units of excess
    above KNEE before the curve reaches zero slope.  CEILING remains the final
    output rail.

    The curve is::

        y = x                                      x <= knee
        y = x - (x - knee)^2 / 131072             x > knee

    Magnitude is bounded at ``knee + 65535`` so the quadratic remains
    monotonic.  With the supported ``knee < ceiling`` control contract, the
    curve always reaches CEILING for a sufficiently large overload.

    The datapath is continuously pipelined and has two sync-clock registers of
    latency.  REZO's feedback accumulator is stable for many clocks before the
    audio FSM consumes ``sample``, so no explicit valid handshake is required.
    """

    def __init__(self, input_width=21):
        self.input_width = input_width
        super().__init__({
            "drive": In(signed(input_width)),
            "knee": In(unsigned(16)),
            "ceiling": In(unsigned(16)),
            "sample": Out(signed(16)),
            "knee_active": Out(1),
            "ceiling_active": Out(1),
        })

    @staticmethod
    def reference(drive, knee, ceiling):
        """Return the exact integer transfer used by the gateware."""
        ceiling = min(max(ceiling, 0), 32767)
        magnitude = abs(drive)
        magnitude = min(magnitude, knee + 65535)
        if magnitude > knee:
            excess = magnitude - knee
            magnitude -= (excess * excess) >> 17
        magnitude = min(magnitude, ceiling)
        return -magnitude if drive < 0 else magnitude

    def elaborate(self, platform):
        m = Module()

        magnitude = Signal(unsigned(self.input_width))
        domain_limit = Signal(unsigned(18))
        limited_magnitude = Signal(unsigned(17))
        excess = Signal(unsigned(16))
        ceiling_safe = Signal(unsigned(16))

        negative_s0 = Signal()
        magnitude_s0 = Signal(unsigned(17))
        excess_s0 = Signal(unsigned(16))
        knee_active_s0 = Signal()

        negative_s1 = Signal()
        magnitude_s1 = Signal(unsigned(17))
        square_s1 = Signal(unsigned(32))
        knee_active_s1 = Signal()

        shaped_magnitude = Signal(unsigned(18))
        output_magnitude = Signal(unsigned(16))

        m.d.comb += [
            magnitude.eq(Mux(self.drive < 0, -self.drive, self.drive)),
            domain_limit.eq(self.knee + 65535),
            limited_magnitude.eq(Mux(
                magnitude > domain_limit, domain_limit, magnitude)),
            excess.eq(Mux(
                limited_magnitude > self.knee,
                limited_magnitude - self.knee, 0)),
            ceiling_safe.eq(Mux(
                self.ceiling > 32767, 32767, self.ceiling)),
        ]

        m.d.sync += [
            negative_s0.eq(self.drive < 0),
            magnitude_s0.eq(limited_magnitude),
            excess_s0.eq(excess),
            knee_active_s0.eq(limited_magnitude > self.knee),
            negative_s1.eq(negative_s0),
            magnitude_s1.eq(magnitude_s0),
            square_s1.eq(excess_s0 * excess_s0),
            knee_active_s1.eq(knee_active_s0),
        ]

        m.d.comb += [
            shaped_magnitude.eq(Mux(
                knee_active_s1,
                magnitude_s1 - (square_s1 >> 17),
                magnitude_s1)),
            output_magnitude.eq(Mux(
                shaped_magnitude > ceiling_safe,
                ceiling_safe, shaped_magnitude)),
            self.knee_active.eq(knee_active_s1),
            self.ceiling_active.eq(shaped_magnitude > ceiling_safe),
            self.sample.eq(Mux(
                negative_s1, -output_magnitude, output_magnitude)),
        ]

        return m
