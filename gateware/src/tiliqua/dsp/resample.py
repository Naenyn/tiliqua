# Copyright (c) 2024 S. Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

import math

from amaranth import *
from amaranth.lib import data, stream, wiring
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
        # Retain the interpolation remainder in ``shift`` fractional bits.
        # Repeatedly adding ``delta >> shift`` loses the remainder every phase;
        # for negative deltas the arithmetic shift rounds down and can drive the
        # interpolated samples past the target before the final endpoint snap.
        # Accumulating the full delta in this wider numerator makes every phase
        # equal to floor(prev + delta * phase / n_up), without a multiplier.
        accum_width = width + shift + 1
        current = Signal(signed(accum_width))
        emitted = Signal(self.shape)
        segment_delta = Signal(signed(width + 1))
        first_accum = Signal(signed(accum_width))
        next_accum = Signal(signed(accum_width))
        first_value = Signal(signed(width + 1))
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
            first_accum.eq((extended(prev) << shift) + delta),
            next_accum.eq(current + segment_delta),
            first_value.eq(first_accum >> shift),
            next_value.eq(next_accum >> shift),
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
                    current.eq(first_accum),
                    segment_delta.eq(delta),
                    emitted.eq(Mux(
                        hard_edge,
                        prev.as_value(),
                        first_value,
                    )),
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
                    emitted.eq(target),
                    edge_segment.eq(0),
                    phase.eq(phase + 1),
                ]
            with m.Else():
                m.d.sync += [
                    current.eq(next_accum),
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


class MultichannelDiscontinuityReconstruct(wiring.Component):

    """Time-multiplexed multichannel variant of DiscontinuityReconstruct.

    History remains independent for every channel, while the endpoint/slope
    arithmetic is shared and evaluated one channel per sync clock. Audio-rate
    input bundles provide far more idle clocks than this requires, and the
    output remains a channel-aligned bundle.
    """

    def __init__(self, *, n_channels, shape=ASQ, min_step=0.02):
        assert n_channels >= 1
        self.n_channels = n_channels
        self.shape = shape
        self.min_step = int(min_step * (1 << shape.f_bits))
        layout = data.ArrayLayout(shape, n_channels)
        super().__init__({
            "i": In(stream.Signature(layout)),
            "o": Out(stream.Signature(layout)),
            "enable": In(1, init=1),
        })

    def elaborate(self, platform):
        m = Module()

        n_channels = self.n_channels
        width = self.shape.width
        history = [
            [Signal(signed(width), name=f"history{ch}_{n}") for n in range(16)]
            for ch in range(n_channels)
        ]
        incoming = Array(Signal(signed(width), name=f"incoming{ch}")
                         for ch in range(n_channels))
        result = Array(Signal(signed(width), name=f"result{ch}")
                       for ch in range(n_channels))
        channel = Signal(range(n_channels))
        analysis_channel = Signal(range(n_channels))
        fill = Signal(range(17))
        processing = Signal()
        analysis_valid = Signal()
        pending = Signal()

        def history_at(index):
            return Array(history[ch][index] for ch in range(n_channels))[channel]

        def extended(value):
            return Cat(value, value[-1]).as_signed()

        left = extended(history_at(0))
        left_next = extended(history_at(1))
        center = extended(history_at(8))
        right_prev = extended(history_at(15))
        right = extended(incoming[channel])

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

        # Register the measured motions before applying the discontinuity
        # criteria.  At ASQ precision, selecting a channel, subtracting, taking
        # five absolute values, comparing them, and selecting a replacement in
        # one 60 MHz cycle was the final critical path.  Input bundles have
        # ample idle clocks, so this one-stage pipeline has no throughput cost.
        analysis_left = Signal(signed(width + 1))
        analysis_center = Signal(signed(width + 1))
        analysis_right = Signal(signed(width + 1))
        analysis_left_motion = Signal(unsigned(width + 2))
        analysis_right_motion = Signal(unsigned(width + 2))
        analysis_step = Signal(unsigned(width + 2))
        analysis_center_left = Signal(unsigned(width + 2))
        analysis_center_right = Signal(unsigned(width + 2))
        analysis_enable = Signal()
        analysis_reconstruct = Signal()

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
            analysis_reconstruct.eq(
                analysis_enable &
                (analysis_step >= self.min_step) &
                ((analysis_left_motion << 5) < analysis_step) &
                ((analysis_right_motion << 5) < analysis_step)
            ),
            self.i.ready.eq(~processing & ~analysis_valid & ~pending),
            self.o.valid.eq(pending),
        ]
        for ch in range(n_channels):
            m.d.comb += self.o.payload[ch].as_value().eq(result[ch])

        with m.If(self.i.valid & self.i.ready):
            for ch in range(n_channels):
                m.d.sync += incoming[ch].eq(self.i.payload[ch].as_value())
            m.d.sync += [
                channel.eq(0),
                processing.eq(1),
            ]

        m.d.sync += analysis_valid.eq(0)
        with m.If(processing):
            m.d.sync += [
                analysis_channel.eq(channel),
                analysis_left.eq(left),
                analysis_center.eq(center),
                analysis_right.eq(right),
                analysis_left_motion.eq(left_motion),
                analysis_right_motion.eq(right_motion),
                analysis_step.eq(step),
                analysis_center_left.eq(center_left),
                analysis_center_right.eq(center_right),
                analysis_enable.eq(self.enable),
                analysis_valid.eq(1),
            ]
            with m.If(channel == n_channels - 1):
                m.d.sync += processing.eq(0)
            with m.Else():
                m.d.sync += channel.eq(channel + 1)

        with m.If(analysis_valid):
            with m.If(fill == 16):
                m.d.sync += result[analysis_channel].eq(
                    Mux(
                        analysis_reconstruct,
                        Mux(
                            analysis_center_left <= analysis_center_right,
                            analysis_left,
                            analysis_right,
                        ),
                        analysis_center,
                    )
                )
            with m.If(analysis_channel == n_channels - 1):
                for ch in range(n_channels):
                    for n in range(15):
                        m.d.sync += history[ch][n].eq(history[ch][n + 1])
                    m.d.sync += history[ch][15].eq(incoming[ch])
                with m.If(fill < 16):
                    m.d.sync += fill.eq(fill + 1)
                with m.Else():
                    m.d.sync += pending.eq(1)

        with m.If(pending & self.o.ready):
            m.d.sync += pending.eq(0)

        return m


class MultichannelFixedPointConvert(wiring.Component):

    """Channel-aligned, rounded fixed-point narrowing.

    Values are rounded to nearest with symmetric handling around zero and
    saturated at the destination endpoints. This is intended for display paths
    where silently truncating calibrated audio introduces a small DC bias.
    """

    def __init__(self, *, n_channels, input_shape, output_shape):
        assert n_channels >= 1
        assert input_shape.f_bits >= output_shape.f_bits
        self.n_channels = n_channels
        self.input_shape = input_shape
        self.output_shape = output_shape
        self.shift = input_shape.f_bits - output_shape.f_bits
        super().__init__({
            "i": In(stream.Signature(data.ArrayLayout(input_shape, n_channels))),
            "o": Out(stream.Signature(data.ArrayLayout(output_shape, n_channels))),
        })

    def elaborate(self, platform):
        m = Module()

        shift = self.shift
        out_width = self.output_shape.width
        out_min = -(1 << (out_width - 1))
        out_max = (1 << (out_width - 1)) - 1
        pending = Signal()
        converted = Array(
            Signal(self.output_shape, name=f"converted{ch}")
            for ch in range(self.n_channels)
        )
        m.d.comb += [
            self.o.valid.eq(pending),
            # A consumed value can be replaced without an idle cycle.
            self.i.ready.eq(~pending | self.o.ready),
        ]
        for ch in range(self.n_channels):
            m.d.comb += self.o.payload[ch].eq(converted[ch])

        accept = self.i.valid & self.i.ready
        with m.If(accept):
            m.d.sync += pending.eq(1)
        with m.Elif(self.o.ready):
            m.d.sync += pending.eq(0)

        for ch in range(self.n_channels):
            raw = self.i.payload[ch].as_value()
            extended = Cat(raw, raw[-1]).as_signed()
            if shift:
                magnitude = Mux(extended < 0, -extended, extended)
                rounded_magnitude = (magnitude + (1 << (shift - 1))) >> shift
                rounded = Mux(extended < 0, -rounded_magnitude, rounded_magnitude)
            else:
                rounded = extended
            clipped = Mux(
                rounded < out_min,
                Const(out_min, signed(out_width)),
                Mux(rounded > out_max,
                    Const(out_max, signed(out_width)), rounded),
            )
            with m.If(accept):
                m.d.sync += converted[ch].as_value().eq(clipped)

        return m


class MultichannelEdgeAwareResample(wiring.Component):

    """Time-multiplexed, channel-aligned EdgeAwareResample.

    The hard-edge decision and interpolation adder are shared across channels.
    State is retained independently, and an output bundle is asserted only
    after all channel values for that interpolation phase are ready.
    """

    def __init__(self, *, n_channels, n_up, shape=ASQ, min_step=0.05):
        assert n_channels >= 1
        assert n_up >= 2 and (n_up & (n_up - 1)) == 0
        self.n_channels = n_channels
        self.n_up = n_up
        self.shape = shape
        self.min_step = int(min_step * (1 << shape.f_bits))
        layout = data.ArrayLayout(shape, n_channels)
        super().__init__({
            "i": In(stream.Signature(layout)),
            "o": Out(stream.Signature(layout)),
        })

    def elaborate(self, platform):
        m = Module()

        n_channels = self.n_channels
        n_up = self.n_up
        shift = int(math.log2(n_up))
        width = self.shape.width
        incoming = Array(Signal(signed(width), name=f"incoming{ch}")
                         for ch in range(n_channels))
        prev_prev = Array(Signal(signed(width), name=f"prev_prev{ch}")
                          for ch in range(n_channels))
        prev = Array(Signal(signed(width), name=f"prev{ch}")
                     for ch in range(n_channels))
        target = Array(Signal(signed(width), name=f"target{ch}")
                       for ch in range(n_channels))
        # Keep the interpolation numerator at ``shift`` extra fractional bits
        # so signed division rounding is applied once per output value instead
        # of being accumulated once per phase.
        accum_width = width + shift + 1
        current = Array(Signal(signed(accum_width), name=f"current{ch}")
                        for ch in range(n_channels))
        emitted = Array(Signal(signed(width), name=f"emitted{ch}")
                        for ch in range(n_channels))
        delta_by_ch = Array(Signal(signed(width + 1), name=f"delta{ch}")
                            for ch in range(n_channels))
        edge_segment = Array(Signal(name=f"edge_segment{ch}")
                             for ch in range(n_channels))

        have_prev = Signal()
        have_prev_delta = Signal()
        setup_active = Signal()
        update_active = Signal()
        output_valid = Signal()
        channel = Signal(range(n_channels))
        phase = Signal(range(n_up + 1))

        def extended(value):
            return Cat(value, value[-1]).as_signed()

        delta = Signal(signed(width + 1))
        prev_delta = Signal(signed(width + 1))
        delta_magnitude = Signal(unsigned(width + 1))
        prev_delta_magnitude = Signal(unsigned(width + 1))
        first_accum = Signal(signed(accum_width))
        next_accum = Signal(signed(accum_width))
        first_value = Signal(signed(width + 1))
        next_value = Signal(signed(width + 1))
        hard_edge = Signal()
        m.d.comb += [
            delta.eq(extended(incoming[channel]) - extended(prev[channel])),
            prev_delta.eq(
                extended(prev[channel]) - extended(prev_prev[channel])),
            delta_magnitude.eq(Mux(delta < 0, -delta, delta)),
            prev_delta_magnitude.eq(
                Mux(prev_delta < 0, -prev_delta, prev_delta)),
            hard_edge.eq(
                have_prev_delta &
                (delta_magnitude >= self.min_step) &
                ((delta_magnitude >> 3) > prev_delta_magnitude)
            ),
            first_accum.eq((extended(prev[channel]) << shift) + delta),
            next_accum.eq(current[channel] + delta_by_ch[channel]),
            first_value.eq(first_accum >> shift),
            next_value.eq(next_accum >> shift),
            self.i.ready.eq(~setup_active & ~update_active & ~output_valid),
            self.o.valid.eq(output_valid),
        ]
        for ch in range(n_channels):
            m.d.comb += self.o.payload[ch].as_value().eq(emitted[ch])

        with m.If(self.i.valid & self.i.ready):
            with m.If(~have_prev):
                for ch in range(n_channels):
                    m.d.sync += prev[ch].eq(self.i.payload[ch].as_value())
                m.d.sync += have_prev.eq(1)
            with m.Else():
                for ch in range(n_channels):
                    m.d.sync += incoming[ch].eq(self.i.payload[ch].as_value())
                m.d.sync += [
                    channel.eq(0),
                    setup_active.eq(1),
                ]

        with m.If(setup_active):
            m.d.sync += [
                target[channel].eq(incoming[channel]),
                current[channel].eq(first_accum),
                emitted[channel].eq(
                    Mux(hard_edge, prev[channel], first_value)),
                delta_by_ch[channel].eq(delta),
                edge_segment[channel].eq(hard_edge),
            ]
            with m.If(channel == n_channels - 1):
                m.d.sync += [
                    setup_active.eq(0),
                    output_valid.eq(1),
                    phase.eq(1),
                ]
            with m.Else():
                m.d.sync += channel.eq(channel + 1)

        with m.If(output_valid & self.o.ready):
            with m.If(phase == n_up):
                for ch in range(n_channels):
                    m.d.sync += [
                        prev_prev[ch].eq(prev[ch]),
                        prev[ch].eq(target[ch]),
                    ]
                m.d.sync += [
                    have_prev_delta.eq(1),
                    output_valid.eq(0),
                ]
            with m.Elif(phase == n_up - 1):
                for ch in range(n_channels):
                    m.d.sync += [
                        emitted[ch].eq(target[ch]),
                        edge_segment[ch].eq(0),
                    ]
                m.d.sync += phase.eq(phase + 1)
            with m.Else():
                m.d.sync += [
                    output_valid.eq(0),
                    update_active.eq(1),
                    channel.eq(0),
                ]

        with m.If(update_active):
            m.d.sync += [
                current[channel].eq(next_accum),
                emitted[channel].eq(
                    Mux(edge_segment[channel], prev[channel], next_value)),
            ]
            with m.If(channel == n_channels - 1):
                m.d.sync += [
                    update_active.eq(0),
                    output_valid.eq(1),
                    phase.eq(phase + 1),
                ]
            with m.Else():
                m.d.sync += channel.eq(channel + 1)

        return m
