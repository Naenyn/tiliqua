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
from .scope_capture import MAX_CAPTURE_COLS, ColumnCapture


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

    class Flags(csr.Register, access="w"):
        enable: csr.Field(csr.action.W, unsigned(1))
        trigger_always: csr.Field(csr.action.W, unsigned(1))
        trigger_falling: csr.Field(csr.action.W, unsigned(1))
        trigger_ch: csr.Field(csr.action.W, unsigned(2))

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

    class DebugStatus(csr.Register, access="r"):
        fsm: csr.Field(csr.action.R, unsigned(2))
        capturing: csr.Field(csr.action.R, unsigned(1))
        rendering: csr.Field(csr.action.R, unsigned(1))
        sample_valid: csr.Field(csr.action.R, unsigned(1))
        in_plot: csr.Field(csr.action.R, unsigned(1))
        at_end: csr.Field(csr.action.R, unsigned(1))
        sweeping: csr.Field(csr.action.R, unsigned(1))
        has_col: csr.Field(csr.action.R, unsigned(1))
        sweep_end: csr.Field(csr.action.R, unsigned(1))
        renderer_busy: csr.Field(csr.action.R, unsigned(1))
        renderer_done: csr.Field(csr.action.R, unsigned(1))
        ramp_at_top: csr.Field(csr.action.R, unsigned(1))
        armed: csr.Field(csr.action.R, unsigned(1))
        pending_trig: csr.Field(csr.action.R, unsigned(1))
        trig_pulse: csr.Field(csr.action.R, unsigned(1))
        sweep_holdoff: csr.Field(csr.action.R, unsigned(1))
        soc_en: csr.Field(csr.action.R, unsigned(1))

    class DebugCount(csr.Register, access="r"):
        capture_done: csr.Field(csr.action.R, unsigned(8))
        render_done: csr.Field(csr.action.R, unsigned(8))
        col_writes: csr.Field(csr.action.R, unsigned(8))
        flush_drops: csr.Field(csr.action.R, unsigned(8))

    class DebugTrig(csr.Register, access="r"):
        trig_edges: csr.Field(csr.action.R, unsigned(8))
        ramp_restarts: csr.Field(csr.action.R, unsigned(8))
        pen_lifts: csr.Field(csr.action.R, unsigned(8))
        end_reached: csr.Field(csr.action.R, unsigned(8))

    class DebugProbe(csr.Register, access="r"):
        in_x: csr.Field(csr.action.R, signed(16))
        in_y0: csr.Field(csr.action.R, signed(16))

    class DebugNcols(csr.Register, access="r"):
        ncols: csr.Field(csr.action.R, unsigned(16))

    class DebugCtl(csr.Register, access="w"):
        test_render: csr.Field(csr.action.W, unsigned(1))

    class DebugTimebase(csr.Register, access="r"):
        td: csr.Field(csr.action.R, unsigned(32))

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
        self._debug_status    = regs.add("debug_status",  self.DebugStatus(),    offset=0x58)
        self._debug_count     = regs.add("debug_count",   self.DebugCount(),     offset=0x5C)
        self._debug_probe     = regs.add("debug_probe",   self.DebugProbe(),     offset=0x60)
        self._debug_ncols     = regs.add("debug_ncols",   self.DebugNcols(),     offset=0x64)
        self._debug_ctl       = regs.add("debug_ctl",     self.DebugCtl(),       offset=0x68)
        self._debug_timebase  = regs.add("debug_timebase", self.DebugTimebase(), offset=0x6C)
        self._debug_trig      = regs.add("debug_trig",    self.DebugTrig(),      offset=0x70)
        self._display_mode    = regs.add("display_mode",   self.DisplayMode(),     offset=0x74)

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
            "flush_word": Out(unsigned(128)),
            "sweep_done": Out(1),
            "plot_x_lo_o": Out(signed(16)),
            "progressive_o": Out(1),
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

        scale_x = Signal(unsigned(4))
        scale_y = Array(Signal(unsigned(3)) for _ in range(self.n_channels))
        x_offset = Signal(signed(16))
        y_offset = Array(Signal(signed(16)) for _ in range(self.n_channels))
        hue = Array(Signal(unsigned(4)) for _ in range(self.n_channels))
        intensity = Array(Signal(unsigned(4)) for _ in range(self.n_channels))
        visible = Array(Signal() for _ in range(self.n_channels))
        progressive = Signal()
        capture_progress_valid = Signal()

        plot_x_lo = Signal(signed(16))
        plot_x_hi = Signal(signed(16))
        plot_y_lo = Signal(signed(16))
        plot_y_hi = Signal(signed(16))

        plot_width = Signal(signed(17))
        ncols = Signal(range(MAX_CAPTURE_COLS + 1))
        m.d.comb += plot_width.eq(plot_x_hi - plot_x_lo)
        with m.If(plot_width > MAX_CAPTURE_COLS):
            m.d.comb += ncols.eq(MAX_CAPTURE_COLS)
        with m.Else():
            m.d.comb += ncols.eq(plot_width.as_unsigned())

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
        m.submodules.ramp = ramp = dsp.Ramp(shape=PSQ)
        timebase = Signal(shape=dsp.Ramp.TIMEBASE_SQ)

        # NORM trigger path (classic hold-at-top scope):
        #   - Mid-sweep crossings are ignored; only a fresh edge while the ramp
        #     is waiting at top restarts the sweep.
        #   - ``trigger_always`` (FREE) restarts as soon as the ramp reaches top.
        ramp_at_top = Signal()
        prev_ramp_at_top = Signal()
        ramp_restarted = Signal()
        trig_seen = Signal()
        norm_fire = Signal()
        ramp_fire = Signal()

        m.d.comb += [
            ramp_at_top.eq(ramp.o.payload > fixed.Const(0.985, shape=PSQ)),
            ramp_restarted.eq(prev_ramp_at_top & ~ramp_at_top),
            trig_seen.eq(trig.o.payload & trig.i.valid & trig.o.ready),
            norm_fire.eq(trig_seen & ramp_at_top & ~trigger_always),
            # The buffer controller briefly drops capture_active while a
            # completed sweep is swapped/cleared. Keep Ramp parked at top
            # during that interval; otherwise it can restart unseen and the
            # next capture misses an entire slow sweep.
            ramp_fire.eq((trigger_always | norm_fire) &
                         self.capture_active & self.soc_en),
        ]
        m.d.sync += prev_ramp_at_top.eq(ramp_at_top)

        trig_sample = Signal(shape=PSQ)
        with m.Switch(trigger_ch):
            for ch in range(self.n_channels):
                with m.Case(ch):
                    m.d.comb += trig_sample.eq(self.isplit4.o[ch].payload)

        dsp.connect_remap(m, irep2.o[0], trig.i, lambda o, i: [
            i.payload.sample.eq(trig_sample),
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

        capturing = Signal()
        rendering = Signal()
        fsm_state = Signal(2)
        m.d.comb += [
            capturing.eq(self.capture_active & self.soc_en),
            rendering.eq(self.soc_en & ~self.capture_active),
            fsm_state.eq(Cat(capturing, rendering)),
        ]

        capture_done_cnt = Signal(8)
        flush_sweep_cnt = Signal(8)
        render_sweep_cnt = Signal(8)
        trig_sweep_cnt = Signal(8)
        ramp_restart_sweep_cnt = Signal(8)
        pen_lift_sweep_cnt = Signal(8)
        end_reached_sweep_cnt = Signal(8)
        trig_pulse = Signal()
        m.d.comb += trig_pulse.eq(norm_fire)

        with m.If(capture.sweep_done):
            m.d.sync += [
                capture_done_cnt.eq(capture_done_cnt + 1),
                flush_sweep_cnt.eq(0),
                render_sweep_cnt.eq(0),
                trig_sweep_cnt.eq(0),
                ramp_restart_sweep_cnt.eq(0),
                pen_lift_sweep_cnt.eq(0),
                end_reached_sweep_cnt.eq(0),
            ]
        with m.If(capture.flush_valid):
            m.d.sync += flush_sweep_cnt.eq(flush_sweep_cnt + 1)
        with m.If(self.swap_done):
            m.d.sync += render_sweep_cnt.eq(render_sweep_cnt + 1)
        with m.If(trig_pulse):
            m.d.sync += trig_sweep_cnt.eq(trig_sweep_cnt + 1)
        with m.If(ramp_restarted):
            m.d.sync += ramp_restart_sweep_cnt.eq(ramp_restart_sweep_cnt + 1)
        with m.If(capture.dbg_pen_lift):
            m.d.sync += pen_lift_sweep_cnt.eq(pen_lift_sweep_cnt + 1)
        with m.If(capture.dbg_end_reached):
            m.d.sync += end_reached_sweep_cnt.eq(end_reached_sweep_cnt + 1)

        m.d.comb += [
            self._debug_status.f.fsm.r_data.eq(fsm_state),
            self._debug_status.f.capturing.r_data.eq(capturing),
            self._debug_status.f.rendering.r_data.eq(rendering),
            self._debug_status.f.sample_valid.r_data.eq(ch0_merge4.o.valid),
            self._debug_status.f.in_plot.r_data.eq(capture.dbg_in_plot),
            self._debug_status.f.at_end.r_data.eq(capture.dbg_at_end),
            self._debug_status.f.sweeping.r_data.eq(capture.dbg_sweeping),
            self._debug_status.f.has_col.r_data.eq(capture.dbg_has_col),
            self._debug_status.f.sweep_end.r_data.eq(capture.dbg_sweep_end),
            self._debug_status.f.renderer_busy.r_data.eq(rendering),
            self._debug_status.f.renderer_done.r_data.eq(~rendering),
            self._debug_status.f.ramp_at_top.r_data.eq(ramp_at_top),
            self._debug_status.f.armed.r_data.eq(capture.dbg_armed),
            self._debug_status.f.pending_trig.r_data.eq(0),
            self._debug_status.f.trig_pulse.r_data.eq(trig_pulse),
            self._debug_status.f.sweep_holdoff.r_data.eq(0),
            self._debug_status.f.soc_en.r_data.eq(self.soc_en),
            self._debug_count.f.capture_done.r_data.eq(capture_done_cnt),
            self._debug_count.f.render_done.r_data.eq(render_sweep_cnt),
            self._debug_count.f.col_writes.r_data.eq(flush_sweep_cnt),
            self._debug_count.f.flush_drops.r_data.eq(0),
            self._debug_trig.f.trig_edges.r_data.eq(trig_sweep_cnt),
            self._debug_trig.f.ramp_restarts.r_data.eq(ramp_restart_sweep_cnt),
            self._debug_trig.f.pen_lifts.r_data.eq(pen_lift_sweep_cnt),
            self._debug_trig.f.end_reached.r_data.eq(end_reached_sweep_cnt),
            self._debug_probe.f.in_x.r_data.eq(capture.dbg_in_x),
            self._debug_probe.f.in_y0.r_data.eq(capture.dbg_in_y0),
            self._debug_ncols.f.ncols.r_data.eq(ncols),
            self._debug_timebase.f.td.r_data.eq(timebase.as_value()),
        ]

        with m.If(self._flags.f.trigger_always.w_stb):
            m.d.sync += trigger_always.eq(self._flags.f.trigger_always.w_data)
        with m.If(self._flags.f.trigger_falling.w_stb):
            m.d.sync += trigger_falling.eq(self._flags.f.trigger_falling.w_data)
        with m.If(self._flags.f.trigger_ch.w_stb):
            m.d.sync += trigger_ch.eq(self._flags.f.trigger_ch.w_data)

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
