# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr
from amaranth_future import fixed

from .. import dsp
from . import PSQ, PSQ_BASE_FBITS, psq_from_volts
from .scope_capture import MAX_CAPTURE_COLS, ENVELOPE_WORD_BITS, ColumnCapture


# Preserve the ramp's eight integer bits while adding four fractional bits for
# 16x finer slow-timebase increments. ``Ramp`` keeps its accumulator scaled by
# 2**6 and therefore restarts at an internal value of -64; Q4.28 cannot
# represent that value and wrapped the restart to zero, preventing a complete
# left-to-right capture sweep. The CSR remains 32 bits because only the
# positive increment is written by firmware; it is zero-extended into this
# wider internal accumulator shape.
SCOPE_TIMEBASE_SQ = fixed.SQ(8, 28)


class _SampleTap(wiring.Component):

    """Always-ready sink so ``connect_peek`` taps keep the merge outputs flowing."""

    def __init__(self, *, shape):
        super().__init__({"i": In(stream.Signature(shape))})

    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.i.ready.eq(1)
        return m


class DigitalScopePeripheral(wiring.Component):

    """
    Four-channel digital oscilloscope capture engine.

    Capture accumulates per-column min/max while the ramp sweeps. Completed
    envelopes are handed to a scanout overlay, which swaps them atomically at
    vertical blank. NORM mode waits for a trigger edge before capture.
    """

    AUTO_TRIGGER_TIMEOUT_S = 0.050

    class Flags(csr.Register, access="w"):
        enable: csr.Field(csr.action.W, unsigned(1))
        trigger_always: csr.Field(csr.action.W, unsigned(1))
        trigger_falling: csr.Field(csr.action.W, unsigned(1))
        trigger_ch: csr.Field(csr.action.W, unsigned(2))
        trigger_filter: csr.Field(csr.action.W, unsigned(3))
        trigger_auto: csr.Field(csr.action.W, unsigned(1))

    class Hue(csr.Register, access="w"):
        hue: csr.Field(csr.action.W, unsigned(8))

    class Intensity(csr.Register, access="w"):
        intensity: csr.Field(csr.action.W, unsigned(8))

    class Timebase(csr.Register, access="w"):
        timebase: csr.Field(csr.action.W, unsigned(32))

    class XScale(csr.Register, access="w"):
        xscale: csr.Field(csr.action.W, unsigned(8))

    class YScale(csr.Register, access="w"):
        yscale: csr.Field(csr.action.W, unsigned(8))

    class ChannelEnable(csr.Register, access="w"):
        ch0: csr.Field(csr.action.W, unsigned(1))
        ch1: csr.Field(csr.action.W, unsigned(1))
        ch2: csr.Field(csr.action.W, unsigned(1))
        ch3: csr.Field(csr.action.W, unsigned(1))

    class TriggerLevel(csr.Register, access="w"):
        trigger_level: csr.Field(csr.action.W, unsigned(16))

    class XPosition(csr.Register, access="w"):
        xpos: csr.Field(csr.action.W, unsigned(16))

    class YPosition(csr.Register, access="w"):
        ypos: csr.Field(csr.action.W, unsigned(16))

    class PlotBound(csr.Register, access="w"):
        value: csr.Field(csr.action.W, signed(16))

    class PixelsPerVolt(csr.Register, access="r"):
        pixels_per_volt: csr.Field(csr.action.R, unsigned(16))

    class Fs(csr.Register, access="r"):
        fs: csr.Field(csr.action.R, unsigned(32))

    class DisplayMode(csr.Register, access="w"):
        progressive: csr.Field(csr.action.W, unsigned(1))
        clean: csr.Field(csr.action.W, unsigned(1))

    class RampEnd(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(16))

    def __init__(self, n_channels=4, fs=48000):

        self.fs = fs
        self.n_channels = n_channels

        regs = csr.Builder(addr_width=7, data_width=8)
        self._flags          = regs.add("flags",          self.Flags(),         offset=0x0)
        self._hue            = regs.add("hue",            self.Hue(),           offset=0x4)
        self._intensity      = regs.add("intensity",      self.Intensity(),     offset=0x8)
        self._timebase       = regs.add("timebase",       self.Timebase(),      offset=0xC)
        self._xscale         = regs.add("xscale",         self.XScale(),        offset=0x10)
        self._yscale         = [regs.add(f"yscale{i}",   self.YScale(),
                                offset=(0x14 if i == 0 else 0x48 + (i - 1) * 4))
                                for i in range(self.n_channels)]
        self._trigger_lvl    = regs.add("trigger_lvl",    self.TriggerLevel(),  offset=0x18)
        self._xpos           = regs.add("xpos",           self.XPosition(),     offset=0x1C)
        self._ypos           = [regs.add(f"ypos{i}",      self.YPosition(),
                                offset=(0x20+i*4)) for i in range(self.n_channels)]
        self._pixels_per_volt = regs.add("pixels_per_volt", self.PixelsPerVolt(), offset=0x30)
        self._fs              = regs.add("fs",              self.Fs(),             offset=0x34)
        self._plot_x_lo       = regs.add("plot_x_lo",     self.PlotBound(),      offset=0x38)
        self._plot_x_hi       = regs.add("plot_x_hi",     self.PlotBound(),      offset=0x3C)
        self._plot_y_lo       = regs.add("plot_y_lo",     self.PlotBound(),      offset=0x40)
        self._plot_y_hi       = regs.add("plot_y_hi",     self.PlotBound(),      offset=0x44)
        self._channel_en      = regs.add("channel_en",    self.ChannelEnable(),  offset=0x54)
        self._display_mode    = regs.add("display_mode",   self.DisplayMode(),     offset=0x74)
        self._ramp_end        = regs.add("ramp_end",       self.RampEnd(),          offset=0x78)

        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__({
            "i": In(stream.Signature(data.ArrayLayout(PSQ, self.n_channels))),
            "bus": In(csr.Signature(addr_width=7, data_width=8)),
            "soc_en": Out(unsigned(1), init=1),
            "capture_active": In(1),
            "capture_clear": In(1),
            "swap_done": In(1),
            "flush_valid": Out(1),
            "flush_col": Out(range(MAX_CAPTURE_COLS)),
            "flush_word": Out(unsigned(ENVELOPE_WORD_BITS)),
            "sweep_done": Out(1),
            "plot_x_lo_o": Out(signed(16)),
            "progressive_o": Out(1),
            "clean_o": Out(1),
            "capture_max_col_o": Out(range(MAX_CAPTURE_COLS)),
            "capture_progress_valid_o": Out(1),
            "hue_o": Out(unsigned(4)).array(self.n_channels),
            "intensity_o": Out(unsigned(4)).array(self.n_channels),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()

        trigger_lvl = Signal(shape=PSQ)
        trigger_always = Signal()
        trigger_falling = Signal()
        trigger_ch = Signal(2)
        trigger_filter = Signal(3)
        trigger_auto = Signal()

        scale_x = Signal(unsigned(4))
        scale_y = Array(Signal(unsigned(3)) for _ in range(self.n_channels))
        x_offset = Signal(signed(16))
        y_offset = Array(Signal(signed(16)) for _ in range(self.n_channels))
        hue = Array(Signal(unsigned(4)) for _ in range(self.n_channels))
        intensity = Array(Signal(unsigned(4)) for _ in range(self.n_channels))
        visible = Array(Signal() for _ in range(self.n_channels))
        progressive = Signal()
        clean = Signal(init=1)
        capture_progress_valid = Signal()

        plot_x_lo = Signal(signed(16))
        plot_x_hi = Signal(signed(16))
        plot_y_lo = Signal(signed(16))
        plot_y_hi = Signal(signed(16))

        self.isplit4 = dsp.Split(self.n_channels, shape=PSQ)
        wiring.connect(m, wiring.flipped(self.i), self.isplit4.i)

        m.submodules.bridge = self._bridge
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        m.d.comb += self._pixels_per_volt.f.pixels_per_volt.r_data.eq(
            psq_from_volts(1).reshape(PSQ_BASE_FBITS))
        m.d.comb += self._fs.f.fs.r_data.eq(self.fs)

        m.submodules.isplit4 = self.isplit4

        m.submodules.irep2 = irep2 = dsp.Split(2, replicate=True, source=self.isplit4.o[0], shape=PSQ)

        # A small Schmitt re-arm margin rejects threshold chatter around the
        # opposite edge. Without this, a noisy recrossing near a sine wave's
        # falling zero crossing can qualify as a rising trigger (or vice versa),
        # producing an occasional 180-degree phase flip.
        m.submodules.trig = trig = dsp.Trigger(
            shape=PSQ, hysteresis=0.016 / 8.192)
        m.d.comb += trig.falling.eq(trigger_falling)
        m.submodules.trig_filter = trig_filter = dsp.TriggerLowPass(shape=PSQ)
        m.d.comb += trig_filter.mode.eq(trigger_filter)
        m.submodules.ramp = ramp = dsp.Ramp(
            shape=PSQ, timebase_shape=SCOPE_TIMEBASE_SQ)
        timebase = Signal(shape=SCOPE_TIMEBASE_SQ)
        ramp_end = Signal(shape=PSQ, init=0.985)
        m.d.comb += ramp.end.eq(ramp_end)

        # NORM trigger path (classic hold-at-top scope):
        #   - Mid-sweep crossings are ignored; only a fresh edge while the ramp
        #     is waiting at top restarts the sweep.
        #   - ``trigger_always`` (FREE) restarts as soon as the ramp reaches top.
        ramp_at_top = Signal()
        trig_seen = Signal()
        norm_fire = Signal()
        auto_fire = Signal()
        ramp_fire = Signal()

        m.submodules.auto_trigger = auto_trigger = dsp.AutoTrigger(
            timeout_cycles=max(2, round(self.fs * self.AUTO_TRIGGER_TIMEOUT_S)))

        m.d.comb += [
            ramp_at_top.eq(ramp.o.payload >= ramp_end),
            trig_seen.eq(trig.o.payload & trig.i.valid & trig.o.ready),
            norm_fire.eq(trig_seen & ramp_at_top & ~trigger_always),
            auto_trigger.edge.eq(norm_fire),
            auto_trigger.enable.eq(trigger_auto & ~trigger_always),
            # Count only while a timeout can be consumed. In particular, do
            # not let a display-bank swap expire the timer invisibly.
            auto_trigger.waiting.eq(
                ramp_at_top & self.capture_active & self.soc_en),
            auto_fire.eq(auto_trigger.o & ~trigger_always),
            # The buffer controller briefly drops capture_active while a
            # completed sweep is swapped/cleared. Keep Ramp parked at top
            # during that interval; otherwise it can restart unseen and the
            # next capture misses an entire slow sweep.
            ramp_fire.eq((trigger_always | auto_fire) &
                         self.capture_active & self.soc_en),
        ]
        trig_sample = Signal(shape=PSQ)
        with m.Switch(trigger_ch):
            for ch in range(self.n_channels):
                with m.Case(ch):
                    m.d.comb += trig_sample.eq(self.isplit4.o[ch].payload)

        dsp.connect_remap(m, irep2.o[0], trig_filter.i, lambda o, i: [
            i.payload.eq(trig_sample),
        ])
        dsp.connect_remap(m, trig_filter.o, trig.i, lambda o, i: [
            i.payload.sample.eq(o.payload),
            i.payload.threshold.eq(trigger_lvl),
        ])
        dsp.connect_remap(m, trig.o, ramp.i, lambda o, i: [
            i.payload.trigger.eq(ramp_fire),
            i.payload.td.eq(timebase),
        ])

        m.submodules.rampsplit4 = rampsplit4 = dsp.Split(
            self.n_channels, replicate=True, source=ramp.o, shape=PSQ)

        m.submodules.ch0_merge4 = ch0_merge4 = dsp.Merge(4, shape=PSQ)
        ch0_merge4.wire_valid(m, [2, 3])
        wiring.connect(m, rampsplit4.o[0], ch0_merge4.i[0])
        wiring.connect(m, irep2.o[1], ch0_merge4.i[1])

        ch_merges = [ch0_merge4]
        for ch in range(1, self.n_channels):
            ch_merge4 = dsp.Merge(4, shape=PSQ)
            m.submodules += ch_merge4
            ch_merge4.wire_valid(m, [2, 3])
            wiring.connect(m, rampsplit4.o[ch], ch_merge4.i[0])
            wiring.connect(m, self.isplit4.o[ch], ch_merge4.i[1])
            ch_merges.append(ch_merge4)

        for ch, merge in enumerate(ch_merges):
            tap = _SampleTap(shape=data.ArrayLayout(PSQ, 4))
            setattr(m.submodules, f"sample_tap{ch}", tap)
            dsp.connect_peek(m, merge.o, tap.i, always_ready=True)

        m.submodules.capture = capture = ColumnCapture()
        m.d.comb += [
            capture.active.eq(self.capture_active & self.soc_en),
            capture.clear.eq(self.capture_clear),
            capture.plot_x_lo.eq(plot_x_lo),
            capture.plot_x_hi.eq(plot_x_hi),
            capture.scale_x.eq(scale_x),
            capture.x_offset.eq(x_offset),
            capture.sample_valid.eq(ch0_merge4.o.valid),
            capture.ramp.eq(ch0_merge4.o.payload[0]),
            capture.ramp_end.eq(ramp_end),
            capture.audio[0].eq(ch0_merge4.o.payload[1]),
            capture.audio[1].eq(ch_merges[1].o.payload[1]),
            capture.audio[2].eq(ch_merges[2].o.payload[1]),
            capture.audio[3].eq(ch_merges[3].o.payload[1]),
            self.flush_valid.eq(capture.flush_valid),
            self.flush_col.eq(capture.flush_col),
            self.flush_word.eq(capture.flush_word),
            self.sweep_done.eq(capture.sweep_done),
            self.plot_x_lo_o.eq(plot_x_lo),
            self.progressive_o.eq(progressive),
            self.clean_o.eq(clean),
            self.capture_max_col_o.eq(capture.max_col),
            self.capture_progress_valid_o.eq(capture_progress_valid),
        ]

        with m.If(self.capture_clear | self.swap_done):
            m.d.sync += capture_progress_valid.eq(0)
        with m.Elif(capture.flush_valid):
            m.d.sync += capture_progress_valid.eq(1)
        for ch in range(self.n_channels):
            m.d.comb += [
                capture.scale_y[ch].eq(scale_y[ch]),
                capture.y_offset[ch].eq(y_offset[ch]),
                capture.visible[ch].eq(visible[ch]),
                self.hue_o[ch].eq(hue[ch]),
                self.intensity_o[ch].eq(Mux(visible[ch], intensity[ch], 0)),
            ]

        with m.If(self._flags.f.trigger_always.w_stb):
            m.d.sync += trigger_always.eq(self._flags.f.trigger_always.w_data)
        with m.If(self._flags.f.trigger_falling.w_stb):
            m.d.sync += trigger_falling.eq(self._flags.f.trigger_falling.w_data)
        with m.If(self._flags.f.trigger_ch.w_stb):
            m.d.sync += trigger_ch.eq(self._flags.f.trigger_ch.w_data)
        with m.If(self._flags.f.trigger_filter.w_stb):
            m.d.sync += trigger_filter.eq(self._flags.f.trigger_filter.w_data)
        with m.If(self._flags.f.trigger_auto.w_stb):
            m.d.sync += trigger_auto.eq(self._flags.f.trigger_auto.w_data)

        with m.If(self._hue.f.hue.w_stb):
            for ch in range(self.n_channels):
                m.d.sync += hue[ch].eq(self._hue.f.hue.w_data + ch*3)

        with m.If(self._intensity.f.intensity.w_stb):
            for ch in range(self.n_channels):
                m.d.sync += intensity[ch].eq(self._intensity.f.intensity.w_data)

        with m.If(self._timebase.f.timebase.w_stb):
            m.d.sync += timebase.as_value().eq(self._timebase.f.timebase.w_data)

        with m.If(self._display_mode.f.progressive.w_stb):
            m.d.sync += progressive.eq(self._display_mode.f.progressive.w_data)
        with m.If(self._display_mode.f.clean.w_stb):
            m.d.sync += clean.eq(self._display_mode.f.clean.w_data)

        with m.If(self._ramp_end.f.value.w_stb):
            m.d.sync += ramp_end.as_value().eq(
                self._ramp_end.f.value.w_data.as_signed())

        with m.If(self._xscale.f.xscale.w_stb):
            m.d.sync += scale_x.eq(self._xscale.f.xscale.w_data)

        for i, yscale_reg in enumerate(self._yscale):
            with m.If(yscale_reg.f.yscale.w_stb):
                m.d.sync += scale_y[i].eq(yscale_reg.f.yscale.w_data)

        with m.If(self._channel_en.f.ch0.w_stb):
            m.d.sync += visible[0].eq(self._channel_en.f.ch0.w_data)
        with m.If(self._channel_en.f.ch1.w_stb):
            m.d.sync += visible[1].eq(self._channel_en.f.ch1.w_data)
        with m.If(self._channel_en.f.ch2.w_stb):
            m.d.sync += visible[2].eq(self._channel_en.f.ch2.w_data)
        with m.If(self._channel_en.f.ch3.w_stb):
            m.d.sync += visible[3].eq(self._channel_en.f.ch3.w_data)

        with m.If(self._trigger_lvl.f.trigger_level.w_stb):
            m.d.sync += trigger_lvl.as_value().eq(
                self._trigger_lvl.f.trigger_level.w_data.as_signed() >> (PSQ_BASE_FBITS - PSQ.f_bits))

        with m.If(self._xpos.f.xpos.w_stb):
            m.d.sync += x_offset.eq(self._xpos.f.xpos.w_data)

        for i, ypos_reg in enumerate(self._ypos):
            with m.If(ypos_reg.f.ypos.w_stb):
                m.d.sync += y_offset[i].eq(ypos_reg.f.ypos.w_data)

        with m.If(self._plot_x_lo.f.value.w_stb):
            m.d.sync += plot_x_lo.eq(self._plot_x_lo.f.value.w_data)
        with m.If(self._plot_x_hi.f.value.w_stb):
            m.d.sync += plot_x_hi.eq(self._plot_x_hi.f.value.w_data)
        with m.If(self._plot_y_lo.f.value.w_stb):
            m.d.sync += plot_y_lo.eq(self._plot_y_lo.f.value.w_data)
        with m.If(self._plot_y_hi.f.value.w_stb):
            m.d.sync += plot_y_hi.eq(self._plot_y_hi.f.value.w_data)

        with m.If(self._flags.f.enable.w_stb):
            m.d.sync += self.soc_en.eq(self._flags.f.enable.w_data)

        with m.If(~self.soc_en):
            m.d.comb += self.i.ready.eq(0)

        return m
