"""Bounded waveform-repetition check accompanying the crossing counter.

One shared read port, 2048 signed samples, no divider and one interpolation
multiply. Prefer the shortest candidate within a small residual margin of the
best match; crossing a hard threshold alone is not evidence of a subharmonic.
This is a limited candidate verifier, not a general fundamental estimator.
"""
from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.memory import Memory
from amaranth.lib.wiring import In, Out


class PeriodVerifier(wiring.Component):
    DEPTH = 2048
    GUARD = 32
    PAIRS = 256
    def __init__(self, *, decimation=8, adaptive=False):
        if decimation not in (1,2,4,8):
            raise ValueError("decimation must be 1, 2, 4 or 8")
        self.decimation = decimation
        self.adaptive = adaptive
        super().__init__({
            "sample": In(signed(16)), "accept": In(1), "clear": In(1),
            "request": In(1), "lag_q8": In(24),
            "busy": Out(1), "done": Out(1), "factor": Out(3),
            "result_lag_q8": Out(24),
            "first_error": Out(26), "first_span": Out(19),
            "capture_arm": In(1), "capture_address": In(11),
            "capture_sample": Out(signed(16)), "capture_frozen": Out(1),
            "capture_ready": Out(1),
            "capture_mode": In(2), "capture_divisor": Out(8),
        })

    def elaborate(self, platform):
        m = Module()
        mem = Memory(shape=signed(16), depth=self.DEPTH, init=[])
        m.submodules.history = mem
        wr = mem.write_port()
        rd = mem.read_port()
        head = Signal(11)
        filled = Signal(range(self.DEPTH+1))
        base_shift = self.decimation.bit_length()-1
        shifts = [base_shift, 0, base_shift+2, base_shift+4] if self.adaptive else [base_shift]*4
        shift = Array(Const(s,3) for s in shifts)[self.capture_mode]
        last_mode = Signal(2)
        last_arm = Signal()
        snapshot_head = Signal(11)
        m.d.sync += last_arm.eq(self.capture_arm)
        m.d.sync += last_mode.eq(self.capture_mode)
        clear = self.clear | (last_mode != self.capture_mode) | (last_arm & ~self.capture_arm)
        # Freeze on a clear AFTER firmware arms a rejected point. The output
        # command that ends/retries CAL clears this lane, so retain the history
        # just before zero is applied, without interfering with recovery retries.
        with m.If(self.capture_arm & clear & ~self.capture_frozen):
            m.d.sync += [snapshot_head.eq(head), self.capture_frozen.eq(1),
                         self.capture_ready.eq(filled == self.DEPTH)]
        with m.If(~self.capture_arm):
            m.d.sync += [self.capture_frozen.eq(0), self.capture_ready.eq(0)]
        max_shift = max(shifts)
        box_count = Signal(max(1,max_shift))
        box_sum = Signal(signed(16+max_shift))
        divisor = Array(Const(1 << s,8) for s in shifts)[self.capture_mode]
        m.d.comb += self.capture_divisor.eq(divisor)
        write = Signal()
        m.d.comb += [write.eq(self.accept & (box_count == divisor-1) & ~clear & ~self.capture_frozen),
                     wr.en.eq(write), wr.addr.eq(head),
                     wr.data.eq((box_sum + self.sample) >> shift)]
        with m.If(self.accept & ~self.capture_frozen):
            m.d.sync += box_count.eq(box_count+1)
            with m.If(box_count == divisor-1):
                m.d.sync += [box_sum.eq(0), box_count.eq(0), head.eq(head+1)]
                with m.If(filled < self.DEPTH):
                    m.d.sync += filled.eq(filled+1)
            with m.Else():
                m.d.sync += box_sum.eq(box_sum+self.sample)

        # At most 32 new capture samples may arrive while reading a snapshot.
        # Abort rather than let circular-buffer overwrite produce a false match.
        writes = Signal(6)
        origin = Signal(11)
        candidate = Signal(3)
        base = Signal(24)
        lag_q8 = Signal(26)
        lag = lag_q8[8:]
        fraction = lag_q8[:8]
        available = Signal(12)
        offset_q8 = Signal(20)
        point = Signal(8)
        address = Signal(11)
        current = Signal(signed(16))
        previous = Signal(signed(16))
        delta = Signal(signed(17))
        product = Signal(signed(26))
        delayed = Signal(signed(18))
        difference = Signal(signed(19))
        error = Signal(26)
        low = Signal(signed(18))
        high = Signal(signed(18))
        span = Signal(19)
        # Compare candidate errors against the SAME amplitude reference. This
        # avoids per-candidate normalization dividers and prevents a slightly
        # larger sampled span from making a longer period win by accident.
        scores = Array(Signal(26, name=f"score{n}") for n in range(4))
        best = Signal(26)
        invalid_score = (1 << 26)-1
        m.d.comb += [address.eq(origin-1-(offset_q8 >> 8)),
                     difference.eq(current-delayed), span.eq(high-low),
                     rd.en.eq(1)]
        # Explicit states allow clear/overrun to override every in-flight stage.
        state = Signal(range(11))
        IDLE, SETUP, CURRENT, DELAY0, DELAY1, INTERPOLATE, MULTIPLY, RESOLVE, ACCUMULATE, EVALUATE, SELECT = range(11)
        with m.Switch(state):
            with m.Case(IDLE):
                with m.If(self.request):
                    m.d.sync += [self.done.eq(0), self.factor.eq(0),
                                 self.first_error.eq(0), self.first_span.eq(0),
                                 self.result_lag_q8.eq(self.lag_q8)]
                    m.d.sync += [best.eq(invalid_score), *(s.eq(invalid_score) for s in scores)]
                    with m.If(filled == self.DEPTH):
                        m.d.sync += [base.eq(self.lag_q8), lag_q8.eq(self.lag_q8),
                                     candidate.eq(1), origin.eq(head), writes.eq(0),
                                     self.busy.eq(1), state.eq(SETUP)]
                    with m.Else():
                        m.d.sync += self.done.eq(1)
            with m.Case(SETUP):
                # Below six capture samples per crossing, linear interpolation
                # cannot reliably verify the high-frequency waveform. Bypass.
                with m.If((base < 6*256) | (lag >= self.DEPTH-self.GUARD-self.PAIRS-1)):
                    m.d.sync += state.eq(SELECT)
                with m.Else():
                    m.d.sync += [available.eq(self.DEPTH-self.GUARD-lag-1),
                                 offset_q8.eq(0), point.eq(0), error.eq(0),
                                 low.eq(32767), high.eq(-32768), state.eq(CURRENT)]
            with m.Case(CURRENT):
                m.d.comb += rd.addr.eq(address)
                m.d.sync += state.eq(DELAY0)
            with m.Case(DELAY0):
                m.d.comb += rd.addr.eq(address-lag)
                m.d.sync += [current.eq(rd.data), state.eq(DELAY1)]
            with m.Case(DELAY1):
                m.d.comb += rd.addr.eq(address-lag-1)
                m.d.sync += [previous.eq(rd.data), state.eq(INTERPOLATE)]
            with m.Case(INTERPOLATE):
                m.d.sync += [delta.eq(rd.data-previous), state.eq(MULTIPLY)]
            with m.Case(MULTIPLY):
                m.d.sync += [product.eq(delta * Cat(fraction, Const(0, 1)).as_signed()),
                             state.eq(RESOLVE)]
            with m.Case(RESOLVE):
                m.d.sync += [delayed.eq(previous + ((product+128) >> 8)),
                             state.eq(ACCUMULATE)]
            with m.Case(ACCUMULATE):
                m.d.sync += error.eq(error + Mux(difference < 0, -difference, difference))
                with m.If(current < low):
                    m.d.sync += low.eq(current)
                with m.If(delayed < Mux(current < low, current, low)):
                    m.d.sync += low.eq(delayed)
                with m.If(current > high):
                    m.d.sync += high.eq(current)
                with m.If(delayed > Mux(current > high, current, high)):
                    m.d.sync += high.eq(delayed)
                with m.If(point == self.PAIRS-1):
                    m.d.sync += state.eq(EVALUATE)
                with m.Else():
                    m.d.sync += [point.eq(point+1), offset_q8.eq(offset_q8+available-1),
                                 state.eq(CURRENT)]
            with m.Case(EVALUATE):
                m.d.sync += scores[candidate-1].eq(error)
                with m.If(error < best):
                    m.d.sync += best.eq(error)
                with m.If(candidate == 1):
                    m.d.sync += [self.first_error.eq(error), self.first_span.eq(span)]
                # Keep the cheap first-period fast path. Only borderline or
                # harmonic-rich windows need the full bounded candidate search.
                with m.If((candidate == 1) & (span >= 64) &
                          ((error << 4)+(error << 2) <= (span << 8))):
                    m.d.sync += [self.factor.eq(1), self.busy.eq(0),
                                 self.done.eq(1), state.eq(IDLE)]
                with m.Elif(candidate == 4):
                    m.d.sync += state.eq(SELECT)
                with m.Else():
                    m.d.sync += [candidate.eq(candidate+1), lag_q8.eq(lag_q8+base),
                                 state.eq(SETUP)]
            with m.Case(SELECT):
                m.d.sync += [self.busy.eq(0), self.done.eq(1), state.eq(IDLE)]
                # At least one candidate must still meet the 5% quality gate.
                # Prefer a shorter period if its residual is within 1/128 of
                # peak-to-peak (0.78125 percentage points) of the best. With
                # 256 pairs this is just 2*span, no added DSP or division.
                with m.If((self.first_span >= 64) &
                          ((best << 4)+(best << 2) <= (self.first_span << 8))):
                    for n in reversed(range(4)):
                        with m.If(scores[n] <= best+(self.first_span << 1)):
                            m.d.sync += self.factor.eq(n+1)

        with m.If(self.busy & write):
            m.d.sync += writes.eq(writes+1)
            with m.If(writes >= self.GUARD-1):
                m.d.sync += [self.busy.eq(0), self.done.eq(1), self.factor.eq(0), state.eq(IDLE)]
        with m.If(clear):
            m.d.sync += [head.eq(0), filled.eq(0), box_count.eq(0), box_sum.eq(0),
                         self.busy.eq(0), self.done.eq(0), self.factor.eq(0),
                         self.result_lag_q8.eq(0), state.eq(IDLE)]
            m.d.sync += [self.first_error.eq(0), self.first_span.eq(0)]
        m.d.comb += self.capture_sample.eq(rd.data)
        with m.If(self.capture_frozen):
            m.d.comb += rd.addr.eq(snapshot_head+self.capture_address)
            m.d.sync += [self.busy.eq(0), self.done.eq(0), self.factor.eq(0), state.eq(IDLE)]
        return m
