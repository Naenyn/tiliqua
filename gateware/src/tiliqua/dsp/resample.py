# Copyright (c) 2024 S. Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

import math

from amaranth import *
from amaranth.lib import stream, wiring
from amaranth.lib.wiring import In, Out

from . import ASQ
from .filters import FIR


class Resample(wiring.Component):

    """
    Polyphase fractional resampler.

    Upsamples by factor N, filters the result, then downsamples by factor M.
    The upsampling action zero-pads before applying the low-pass filter, so
    the low-pass filter coefficients are prescaled by N to preserve total energy.

    The underlying FIR interpolator only performs MACs on non-padded input samples,
    (and for output samples which are not discarded), which can make a big difference
    for large upsampling/interpolating ratios, and is what makes this a polyphase
    resampler - time complexity per output sample proportional to O(fir_order/N).

    Members
    -------
    i : :py:`In(stream.Signature(ASQ))`
        Input stream for sending samples to the resampler at sample rate :py:`fs_in`.
    o : :py:`In(stream.Signature(ASQ))`
        Output stream for getting samples from the resampler. Samples are produced
        at a rate determined by :py:`fs_in * (n_up / m_down)`.
    """

    def __init__(self,
                 fs_in:      int,
                 n_up:       int,
                 m_down:     int,
                 bw:         float=0.4,
                 order_mult: int=5,
                 shape=ASQ):
        """
        fs_in : int
            Expected sample rate of incoming samples, used for calculating filter coefficients.
        n_up : int
            Numerator of the resampling ratio. Samples are produced at :py:`fs_in * (n_up / m_down)`.
            If :py:`n_up` and :py:`m_down` share a common factor, the internal resampling ratio is reduced.
        m_down : int
            Denominator of the resampling ratio. Samples are produced at :py:`fs_in * (n_up / m_down)`.
            If :py:`n_up` and :py:`m_down` share a common factor, the internal resampling ratio is reduced.
        bw : float
            Bandwidth (0 to 1, proportion of the nyquist frequency) of the resampling filter.
        order_mult : int
            Filter order multiplier, determines number of taps in underlying FIR filter. The
            underlying tap count is determined as :py:`order_factor*max(self.n_up, self.m_down)`,
            rounded up to the next multiple of :py:`n_up` (required for even zero padding).
        shape : fixed.Shape
            Fixed-point shape for input/output samples. Defaults to ASQ.
        """

        gcd = math.gcd(n_up, m_down)
        if gcd > 1:
            print(f"WARN: Resample {n_up}/{m_down} has GCD {gcd}. Using {n_up//gcd}/{m_down//gcd}.")
            n_up = n_up//gcd
            m_down = m_down//gcd

        self.fs_in  = fs_in
        self.n_up   = n_up
        self.m_down = m_down
        self.bw     = bw

        filter_order = order_mult*max(self.n_up, self.m_down)
        if filter_order % self.n_up != 0:
            # If the filter is not divisible by n_up, choose the next largest filter
            # order that is, so that we can use FIR 'stride' (polyphase resampling
            # optimization based on known zero padding).
            filter_order = self.n_up * ((filter_order // self.n_up) + 1)

        self.filt = FIR(
            fs=self.fs_in*self.n_up,
            filter_cutoff_hz=min(self.fs_in*self.bw,
                                 int((self.fs_in*self.bw)*(self.n_up/self.m_down))),
            filter_order=filter_order,
            prescale=self.n_up,
            stride_i=self.n_up,
            stride_o=self.m_down,
            shape=shape)

        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):

        m = Module()

        m.submodules.filt = filt = self.filt

        upsample_counter  = Signal(range(self.n_up))

        m.d.comb += [
            self.i.ready.eq((upsample_counter == 0) & filt.i.ready),
        ]

        with m.If(filt.i.ready):
            with m.If(self.i.valid & self.i.ready):
                m.d.comb += [
                    filt.i.payload.eq(self.i.payload),
                    filt.i.valid.eq(1),
                ]
                m.d.sync += upsample_counter.eq(self.n_up - 1)
            with m.Elif(upsample_counter > 0):
                m.d.comb += [
                    filt.i.payload.eq(0),
                    filt.i.valid.eq(1),
                ]
                m.d.sync += upsample_counter.eq(upsample_counter - 1)


        wiring.connect(m, filt.o, wiring.flipped(self.o))

        return m


class LinearResample(wiring.Component):

    """Power-of-two linear interpolator for display/visualization paths.

    Emits ``n_up`` evenly-spaced samples between each pair of input samples,
    including the new endpoint. Unlike the band-limited FIR resampler, linear
    interpolation is monotonic and cannot create Gibbs overshoot at waveform
    discontinuities such as saw resets.
    """

    def __init__(self, *, n_up, shape=ASQ):
        assert n_up >= 2 and (n_up & (n_up - 1)) == 0
        self.n_up = n_up
        self.shape = shape
        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        shift = int(math.log2(self.n_up))
        prev = Signal(self.shape)
        target = Signal(self.shape)
        have_prev = Signal()
        active = Signal()
        phase = Signal(range(self.n_up + 1))

        current = Signal(signed(self.shape.width + 1))
        step = Signal(signed(self.shape.width + 1))
        next_value = Signal(signed(self.shape.width + 1))
        m.d.comb += [
            next_value.eq(current + step),
            self.i.ready.eq(~active),
            self.o.valid.eq(active),
            self.o.payload.as_value().eq(
                Mux(phase == self.n_up, target.as_value(), next_value)
            ),
        ]

        with m.If(~active & self.i.valid):
            with m.If(~have_prev):
                m.d.sync += [
                    prev.eq(self.i.payload),
                    have_prev.eq(1),
                ]
            with m.Else():
                m.d.sync += [
                    target.eq(self.i.payload),
                    current.eq(prev.as_value()),
                    step.eq(
                        (self.i.payload.as_value() - prev.as_value()) >> shift
                    ),
                    phase.eq(1),
                    active.eq(1),
                ]

        with m.If(active & self.o.ready):
            with m.If(phase == self.n_up):
                m.d.sync += [
                    prev.eq(target),
                    active.eq(0),
                ]
            with m.Else():
                m.d.sync += [
                    current.eq(next_value),
                    phase.eq(phase + 1),
                ]

        return m


class EdgeAwareResample(wiring.Component):

    """Linear interpolator that preserves isolated waveform discontinuities.

    Ordinary sample pairs are linearly interpolated, removing the visible
    sample-and-hold staircase at fast display timebases. A new delta is treated
    as a hard edge when it exceeds ``min_step`` and is more than eight times
    the preceding delta. Those segments hold the old value until the new
    endpoint, retaining sharp square transitions and saw resets without FIR
    ringing.
    """

    def __init__(self, *, n_up, shape=ASQ, min_step=0.05):
        assert n_up >= 2 and (n_up & (n_up - 1)) == 0
        self.n_up = n_up
        self.shape = shape
        self.min_step = int(min_step * (1 << shape.f_bits))
        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        shift = int(math.log2(self.n_up))
        width = self.shape.width
        prev_prev = Signal(self.shape)
        prev = Signal(self.shape)
        target = Signal(self.shape)
        have_prev = Signal()
        have_prev_delta = Signal()
        active = Signal()
        edge_segment = Signal()
        phase = Signal(range(self.n_up + 1))

        def extended(value):
            raw = value.as_value()
            return Cat(raw, raw[-1]).as_signed()

        delta = Signal(signed(width + 1))
        prev_delta = Signal(signed(width + 1))
        delta_magnitude = Signal(unsigned(width + 1))
        prev_delta_magnitude = Signal(unsigned(width + 1))
        current = Signal(signed(width + 1))
        emitted = Signal(self.shape)
        step = Signal(signed(width + 1))
        next_value = Signal(signed(width + 1))
        hard_edge = Signal()

        m.d.comb += [
            delta.eq(extended(self.i.payload) - extended(prev)),
            prev_delta.eq(extended(prev) - extended(prev_prev)),
            delta_magnitude.eq(Mux(delta < 0, -delta, delta)),
            prev_delta_magnitude.eq(
                Mux(prev_delta < 0, -prev_delta, prev_delta)),
            hard_edge.eq(
                have_prev_delta &
                (delta_magnitude >= self.min_step) &
                ((delta_magnitude >> 3) > prev_delta_magnitude)
            ),
            next_value.eq(current + step),
            self.i.ready.eq(~active),
            self.o.valid.eq(active),
            self.o.payload.eq(emitted),
        ]

        with m.If(~active & self.i.valid):
            with m.If(~have_prev):
                m.d.sync += [
                    prev.eq(self.i.payload),
                    have_prev.eq(1),
                ]
            with m.Else():
                m.d.sync += [
                    target.eq(self.i.payload),
                    current.eq(extended(prev) + (delta >> shift)),
                    emitted.eq(Mux(
                        hard_edge,
                        prev.as_value(),
                        extended(prev) + (delta >> shift),
                    )),
                    step.eq(delta >> shift),
                    edge_segment.eq(hard_edge),
                    phase.eq(1),
                    active.eq(1),
                ]

        with m.If(active & self.o.ready):
            with m.If(phase == self.n_up):
                m.d.sync += [
                    prev_prev.eq(prev),
                    prev.eq(target),
                    have_prev_delta.eq(1),
                    active.eq(0),
                ]
            with m.Elif(phase == self.n_up - 1):
                m.d.sync += [
                    current.eq(extended(target)),
                    emitted.eq(target),
                    edge_segment.eq(0),
                    phase.eq(phase + 1),
                ]
            with m.Else():
                m.d.sync += [
                    current.eq(next_value),
                    emitted.eq(Mux(edge_segment, prev.as_value(), next_value)),
                    phase.eq(phase + 1),
                ]

        return m


class HoldResample(wiring.Component):

    """Repeat each input sample ``n_up`` times (zero-order hold).

    Unlike :class:`LinearResample`, discontinuities are not softened into
    ramps, so square and saw edges stay sharp at the source sample grid.
    """

    def __init__(self, *, n_up, shape=ASQ):
        assert n_up >= 1 and (n_up & (n_up - 1)) == 0
        self.n_up = n_up
        self.shape = shape
        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        hold = Signal(self.shape)
        active = Signal()
        phase = Signal(range(self.n_up))

        m.d.comb += [
            self.i.ready.eq(~active),
            self.o.valid.eq(active),
            self.o.payload.eq(hold),
        ]

        with m.If(~active & self.i.valid):
            m.d.sync += [
                hold.eq(self.i.payload),
                phase.eq(0),
                active.eq(1),
            ]

        with m.If(active & self.o.ready):
            with m.If(phase == self.n_up - 1):
                m.d.sync += active.eq(0)
            with m.Else():
                m.d.sync += phase.eq(phase + 1)

        return m


class DiscontinuityReconstruct(wiring.Component):

    """Sharpen hard display edges without modifying smooth waveforms.

    The center of a seventeen-sample window is replaced by its nearer endpoint only
    when the endpoint separation is much larger than the local motion at both
    ends. This removes short codec settling/overshoot around square and saw
    transitions, while a sine or ramp fails the 32:1 step-to-slope test and is
    passed through unchanged. The visual path gains eight input samples of
    latency; sample rate and throughput are unchanged.
    """

    def __init__(self, *, shape=ASQ, min_step=0.02):
        self.shape = shape
        self.min_step = int(min_step * (1 << shape.f_bits))
        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        width = self.shape.width
        history = Array(Signal(self.shape, name=f"history{n}")
                        for n in range(16))
        fill = Signal(range(17))
        pending = Signal()
        result = Signal(self.shape)

        def extended(value):
            raw = value.as_value()
            return Cat(raw, raw[-1]).as_signed()

        left = extended(history[0])
        left_next = extended(history[1])
        center = extended(history[8])
        right_prev = extended(history[15])
        right = extended(self.i.payload)

        left_delta = Signal(signed(width + 2))
        right_delta = Signal(signed(width + 2))
        step_delta = Signal(signed(width + 2))
        center_left_delta = Signal(signed(width + 2))
        center_right_delta = Signal(signed(width + 2))
        left_motion = Signal(unsigned(width + 2))
        right_motion = Signal(unsigned(width + 2))
        step = Signal(unsigned(width + 2))
        center_left = Signal(unsigned(width + 2))
        center_right = Signal(unsigned(width + 2))

        m.d.comb += [
            left_delta.eq(left_next - left),
            right_delta.eq(right - right_prev),
            step_delta.eq(right - left),
            center_left_delta.eq(center - left),
            center_right_delta.eq(center - right),
            left_motion.eq(Mux(left_delta < 0, -left_delta, left_delta)),
            right_motion.eq(Mux(right_delta < 0, -right_delta, right_delta)),
            step.eq(Mux(step_delta < 0, -step_delta, step_delta)),
            center_left.eq(Mux(center_left_delta < 0,
                               -center_left_delta, center_left_delta)),
            center_right.eq(Mux(center_right_delta < 0,
                                -center_right_delta, center_right_delta)),
            self.i.ready.eq(~pending | self.o.ready),
            self.o.valid.eq(pending),
            self.o.payload.eq(result),
        ]

        reconstruct = Signal()
        m.d.comb += reconstruct.eq(
            (step >= self.min_step) &
            ((left_motion << 5) < step) &
            ((right_motion << 5) < step)
        )

        accept = Signal()
        m.d.comb += accept.eq(self.i.valid & self.i.ready)
        with m.If(accept):
            for n in range(15):
                m.d.sync += history[n].eq(history[n + 1])
            m.d.sync += history[15].eq(self.i.payload)

            with m.If(fill < 16):
                m.d.sync += [
                    fill.eq(fill + 1),
                    pending.eq(0),
                ]
            with m.Else():
                with m.If(reconstruct):
                    m.d.sync += result.as_value().eq(
                        Mux(center_left <= center_right, left, right))
                with m.Else():
                    m.d.sync += result.eq(history[8])
                m.d.sync += pending.eq(1)
        with m.Elif(pending & self.o.ready):
            m.d.sync += pending.eq(0)

        return m
