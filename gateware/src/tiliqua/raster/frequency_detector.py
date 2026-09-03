# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Native-sample frequency and high-rate activity measurement."""

from amaranth import *
from amaranth.lib import data, wiring
from amaranth.lib.wiring import In, Out


class NativeFrequencyDetector(wiring.Component):

    """Measure Schmitt rising-crossing periods in native sample frames.

    The input is registered immediately and all counters advance on ``tick``,
    so the reported period is independent of the system-clock frequency.  A
    slowly released min/max envelope supplies an offset-independent midpoint.
    ``rapid`` is deliberately independent of the last measured period: two or
    more rising crossings in a short window flag complex/high-rate activity
    even before a useful long-period measurement is available.
    """

    PERIOD_BITS = 24

    def __init__(
        self,
        *,
        shape,
        n_channels=4,
        envelope_block_samples=1024,
        envelope_release_step=8,
        min_range=160,
        min_hysteresis=64,
        activity_window_samples=4800,
        rapid_crossings=2,
        rapid_hold_windows=20,
    ):
        if envelope_block_samples < 2:
            raise ValueError("envelope_block_samples must be at least two")
        if activity_window_samples < 2:
            raise ValueError("activity_window_samples must be at least two")
        if rapid_crossings < 1:
            raise ValueError("rapid_crossings must be positive")
        if rapid_hold_windows < 1:
            raise ValueError("rapid_hold_windows must be positive")

        self.shape = shape
        self.n_channels = n_channels
        self.envelope_block_samples = envelope_block_samples
        self.envelope_release_step = envelope_release_step
        self.min_range = min_range
        self.min_hysteresis = min_hysteresis
        self.activity_window_samples = activity_window_samples
        self.rapid_crossings = rapid_crossings
        self.rapid_hold_windows = rapid_hold_windows

        super().__init__({
            "sample": In(data.ArrayLayout(shape, n_channels)),
            "tick": In(1),
            "period": Out(unsigned(self.PERIOD_BITS)).array(n_channels),
            "valid": Out(1).array(n_channels),
            "rapid": Out(1).array(n_channels),
        })

    def elaborate(self, platform):
        m = Module()

        period_max = (1 << self.PERIOD_BITS) - 1
        # Keep the detector's state in the fixed-point type's underlying raw
        # integer shape. Dynamic Array indexing returns a normal Amaranth value,
        # which cannot be assigned directly to fixed.Value, while the raw bits
        # retain exactly the same calibrated Q-format and signed comparisons.
        storage_shape = Shape(self.shape.width, signed=self.shape.signed)
        sample_r = Array(Signal(storage_shape, name=f"sample_r{ch}")
                         for ch in range(self.n_channels))
        processing = Signal()
        channel = Signal(range(self.n_channels))
        with m.If(self.tick):
            for ch in range(self.n_channels):
                m.d.sync += sample_r[ch].eq(self.sample[ch])
            m.d.sync += [
                processing.eq(1),
                channel.eq(0),
            ]

        block_count = Signal(range(self.envelope_block_samples))
        activity_window_count = Signal(range(self.activity_window_samples))

        initialized = Array(Signal(name=f"initialized{ch}")
                            for ch in range(self.n_channels))
        block_low = Array(Signal(storage_shape, name=f"block_low{ch}")
                          for ch in range(self.n_channels))
        block_high = Array(Signal(storage_shape, name=f"block_high{ch}")
                           for ch in range(self.n_channels))
        envelope_low = Array(Signal(storage_shape, name=f"envelope_low{ch}")
                             for ch in range(self.n_channels))
        envelope_high = Array(Signal(storage_shape, name=f"envelope_high{ch}")
                              for ch in range(self.n_channels))
        threshold_low = Array(Signal(storage_shape, name=f"threshold_low{ch}")
                              for ch in range(self.n_channels))
        threshold_high = Array(Signal(storage_shape, name=f"threshold_high{ch}")
                               for ch in range(self.n_channels))
        threshold_valid = Array(Signal(name=f"threshold_valid{ch}")
                                for ch in range(self.n_channels))

        armed_below = Array(Signal(name=f"armed_below{ch}")
                            for ch in range(self.n_channels))
        have_crossing = Array(Signal(name=f"have_crossing{ch}")
                              for ch in range(self.n_channels))
        elapsed = Array(Signal(unsigned(self.PERIOD_BITS), name=f"elapsed{ch}")
                        for ch in range(self.n_channels))
        live_period = Array(Signal(unsigned(self.PERIOD_BITS), name=f"period{ch}")
                            for ch in range(self.n_channels))
        live_valid = Array(Signal(name=f"valid{ch}")
                           for ch in range(self.n_channels))
        stale_timeout = Array(
            Signal(unsigned(self.PERIOD_BITS), name=f"stale_timeout{ch}")
            for ch in range(self.n_channels))

        activity_count_shape = range(self.rapid_crossings + 1)
        activity_count = Array(Signal(activity_count_shape, name=f"activity_count{ch}")
                               for ch in range(self.n_channels))
        rapid_hold = Array(Signal(range(self.rapid_hold_windows + 1),
                                  name=f"rapid_hold{ch}")
                           for ch in range(self.n_channels))

        for ch in range(self.n_channels):
            m.d.comb += [
                self.period[ch].eq(live_period[ch]),
                self.valid[ch].eq(live_valid[ch]),
                self.rapid[ch].eq(rapid_hold[ch] != 0),
            ]

        # The four channels are processed on four successive sync clocks. At
        # 192 kHz there are about 312 clocks between sample bundles, so this
        # serialization shares the wide arithmetic without risking backlog.
        sample = Signal(storage_shape)
        block_low_candidate = Signal(storage_shape)
        block_high_candidate = Signal(storage_shape)
        envelope_range = Signal(signed(self.shape.width + 1))
        midpoint = Signal(signed(self.shape.width + 1))
        hysteresis = Signal(unsigned(self.shape.width + 1))
        release_low_target = Signal(signed(self.shape.width + 1))
        release_high_target = Signal(signed(self.shape.width + 1))
        period_candidate = Signal(unsigned(self.PERIOD_BITS + 1))
        timeout_candidate = Signal(unsigned(self.PERIOD_BITS + 3))
        rising = Signal()

        m.d.comb += [
            sample.eq(sample_r[channel]),
            block_low_candidate.eq(Mux(
                sample < block_low[channel], sample, block_low[channel])),
            block_high_candidate.eq(Mux(
                sample > block_high[channel], sample, block_high[channel])),
            envelope_range.eq(envelope_high[channel] - envelope_low[channel]),
            midpoint.eq(envelope_low[channel] + (envelope_range >> 1)),
            hysteresis.eq(Mux(
                (envelope_range >> 4) < self.min_hysteresis,
                self.min_hysteresis,
                envelope_range >> 4,
            )),
            release_low_target.eq(envelope_low[channel] + self.envelope_release_step),
            release_high_target.eq(envelope_high[channel] - self.envelope_release_step),
            period_candidate.eq(elapsed[channel] + 1),
            timeout_candidate.eq(period_candidate + (period_candidate << 1)),
            rising.eq(
                processing & threshold_valid[channel] & armed_below[channel]
                & (sample >= threshold_high[channel])),
        ]

        with m.If(processing):
            with m.If(~initialized[channel]):
                m.d.sync += [
                    initialized[channel].eq(1),
                    block_low[channel].eq(sample),
                    block_high[channel].eq(sample),
                    envelope_low[channel].eq(sample),
                    envelope_high[channel].eq(sample),
                ]
            with m.Else():
                with m.If(block_count == self.envelope_block_samples - 1):
                    # Close the completed block before the current boundary
                    # sample starts the next one. Besides making block ownership
                    # unambiguous, this avoids chaining the boundary-sample
                    # comparison into the wide envelope update path.
                    # Attack new extrema immediately; release by a small fixed
                    # amount per block.
                    with m.If(block_low[channel] < envelope_low[channel]):
                        m.d.sync += envelope_low[channel].eq(block_low[channel])
                    with m.Else():
                        m.d.sync += envelope_low[channel].eq(Mux(
                            release_low_target < block_low[channel],
                            release_low_target,
                            block_low[channel],
                        ))
                    with m.If(block_high[channel] > envelope_high[channel]):
                        m.d.sync += envelope_high[channel].eq(block_high[channel])
                    with m.Else():
                        m.d.sync += envelope_high[channel].eq(Mux(
                            release_high_target > block_high[channel],
                            release_high_target,
                            block_high[channel],
                        ))

                    # Registered thresholds isolate envelope arithmetic from
                    # the crossing/counter state path.
                    m.d.sync += [
                        threshold_valid[channel].eq(envelope_range >= self.min_range),
                        threshold_low[channel].eq(midpoint - hysteresis),
                        threshold_high[channel].eq(midpoint + hysteresis),
                        block_low[channel].eq(sample),
                        block_high[channel].eq(sample),
                    ]
                with m.Else():
                    m.d.sync += [
                        block_low[channel].eq(block_low_candidate),
                        block_high[channel].eq(block_high_candidate),
                    ]

            with m.If(~threshold_valid[channel]):
                m.d.sync += [
                    armed_below[channel].eq(0),
                    have_crossing[channel].eq(0),
                    live_valid[channel].eq(0),
                    elapsed[channel].eq(0),
                    stale_timeout[channel].eq(0),
                ]
            with m.Elif(sample <= threshold_low[channel]):
                m.d.sync += armed_below[channel].eq(1)
                with m.If(have_crossing[channel] & (elapsed[channel] != period_max)):
                    m.d.sync += elapsed[channel].eq(elapsed[channel] + 1)
                with m.If(live_valid[channel]):
                    with m.If(stale_timeout[channel] != 0):
                        m.d.sync += stale_timeout[channel].eq(stale_timeout[channel] - 1)
                    with m.Else():
                        m.d.sync += live_valid[channel].eq(0)
            with m.Elif(rising):
                m.d.sync += [
                    armed_below[channel].eq(0),
                    elapsed[channel].eq(0),
                ]
                with m.If(have_crossing[channel]):
                    m.d.sync += [
                        live_period[channel].eq(period_candidate[:self.PERIOD_BITS]),
                        live_valid[channel].eq(period_candidate <= period_max),
                        stale_timeout[channel].eq(Mux(
                            timeout_candidate > period_max,
                            period_max,
                            timeout_candidate[:self.PERIOD_BITS],
                        )),
                    ]
                with m.Else():
                    m.d.sync += have_crossing[channel].eq(1)
            with m.Else():
                with m.If(have_crossing[channel]):
                    with m.If(elapsed[channel] != period_max):
                        m.d.sync += elapsed[channel].eq(elapsed[channel] + 1)
                    with m.Else():
                        m.d.sync += live_valid[channel].eq(0)
                with m.If(live_valid[channel]):
                    with m.If(stale_timeout[channel] != 0):
                        m.d.sync += stale_timeout[channel].eq(stale_timeout[channel] - 1)
                    with m.Else():
                        m.d.sync += live_valid[channel].eq(0)

            with m.If(activity_window_count == self.activity_window_samples - 1):
                with m.If(activity_count[channel] + rising >= self.rapid_crossings):
                    m.d.sync += rapid_hold[channel].eq(self.rapid_hold_windows)
                with m.Elif(rapid_hold[channel] != 0):
                    m.d.sync += rapid_hold[channel].eq(rapid_hold[channel] - 1)
                m.d.sync += activity_count[channel].eq(0)
            with m.Elif(rising & (activity_count[channel] < self.rapid_crossings)):
                m.d.sync += activity_count[channel].eq(activity_count[channel] + 1)

            with m.If(channel == self.n_channels - 1):
                m.d.sync += processing.eq(0)
                with m.If(block_count == self.envelope_block_samples - 1):
                    m.d.sync += block_count.eq(0)
                with m.Else():
                    m.d.sync += block_count.eq(block_count + 1)
                with m.If(activity_window_count == self.activity_window_samples - 1):
                    m.d.sync += activity_window_count.eq(0)
                with m.Else():
                    m.d.sync += activity_window_count.eq(activity_window_count + 1)
            with m.Else():
                m.d.sync += channel.eq(channel + 1)

        return m
