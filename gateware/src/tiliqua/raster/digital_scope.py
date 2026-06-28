# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import data, memory, stream, wiring
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr
from amaranth_future import fixed

from .. import dsp
from ..dsp import stream_util
from ..video.framebuffer import DMAFramebuffer
from . import PSQ, PSQ_BASE_FBITS, psq_from_volts
from .clear import RegionClear
from .line import LineCmd, _LinePlotter
from .plot import OffsetMode, PlotRequest
from .plot_clip import PlotClip
from .scope_capture import MAX_CAPTURE_COLS, ENVELOPE_SENTINEL, ColumnCapture
from .scope_render import ColumnRenderer


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
    Four-channel digital oscilloscope with acquire-then-render column envelopes.

    Capture accumulates per-column min/max while the ramp sweeps; a separate
    render pass walks left-to-right and redraws one column at a time through
    the line plotter path.  NORM mode waits for a trigger edge before capture.
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

        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__({
            "i": In(stream.Signature(data.ArrayLayout(PSQ, self.n_channels))),
            "bus": In(csr.Signature(addr_width=7, data_width=8)),
            "fbp": In(DMAFramebuffer.Properties()),
            "o": Out(stream.Signature(PlotRequest)).array(self.n_channels),
            "clear_o": Out(stream.Signature(PlotRequest)),
            "soc_en": Out(unsigned(1), init=1),
            "dbg_plotter": In(unsigned(16)),
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

        # "Shown" envelope: what each column currently has on screen, so the
        # renderer can erase only the previously-drawn span.  Init to the
        # sentinel so the very first pass erases nothing.
        shown_mem = memory.Memory(
            data=memory.MemoryData(
                shape=unsigned(128),
                depth=MAX_CAPTURE_COLS,
                init=[ENVELOPE_SENTINEL] * MAX_CAPTURE_COLS,
            )
        )
        m.submodules.shown_mem = shown_mem
        shown_wr = shown_mem.write_port()
        shown_rd = shown_mem.read_port()

        line_fifos = []
        line_plotters = []
        for n in range(self.n_channels):
            line_fifo = stream_util.SyncFIFOBuffered(shape=LineCmd, depth=256)
            line_plotter = _LinePlotter(offset=OffsetMode.CENTER)
            clip = PlotClip()
            setattr(m.submodules, f"line_fifo{n}", line_fifo)
            setattr(m.submodules, f"line_plotter{n}", line_plotter)
            setattr(m.submodules, f"plot_clip{n}", clip)
            line_fifos.append(line_fifo)
            line_plotters.append(line_plotter)
            m.d.comb += [
                clip.x_lo.eq(plot_x_lo),
                clip.x_hi.eq(plot_x_hi),
                clip.y_lo.eq(plot_y_lo),
                clip.y_hi.eq(plot_y_hi),
            ]
            wiring.connect(m, line_fifo.o, line_plotter.i)
            wiring.connect(m, line_plotter.o, clip.i)
            wiring.connect(m, clip.o, wiring.flipped(self.o[n]))

        enable_prev = Signal()
        enable_clear = Signal()
        m.d.comb += enable_clear.eq(self.soc_en & ~enable_prev)
        m.d.sync += enable_prev.eq(self.soc_en)

        # One-time full-rectangle clear at enable so the plot area starts blank.
        # After this the renderer erases incrementally per column (no per-frame
        # full-screen clear, hence no flicker).
        m.submodules.region_clear = region_clear = RegionClear()
        m.submodules.clear_clip = clear_clip = PlotClip()
        wiring.connect(m, region_clear.o, clear_clip.i)
        wiring.connect(m, clear_clip.o, wiring.flipped(self.clear_o))
        m.d.comb += [
            region_clear.start.eq(enable_clear),
            region_clear.x_lo.eq(plot_x_lo),
            region_clear.x_hi.eq(plot_x_hi),
            region_clear.y_lo.eq(plot_y_lo),
            region_clear.y_hi.eq(plot_y_hi),
            clear_clip.x_lo.eq(plot_x_lo),
            clear_clip.x_hi.eq(plot_x_hi),
            clear_clip.y_lo.eq(plot_y_lo),
            clear_clip.y_hi.eq(plot_y_hi),
        ]

        m.submodules.isplit4 = self.isplit4

        m.submodules.irep2 = irep2 = dsp.Split(2, replicate=True, source=self.isplit4.o[0], shape=PSQ)

        m.submodules.trig = trig = dsp.Trigger(shape=PSQ, tap=True)
        m.d.comb += trig.falling.eq(trigger_falling)
        m.submodules.ramp = ramp = dsp.Ramp(shape=PSQ)
        timebase = Signal(shape=dsp.Ramp.TIMEBASE_SQ)

        # NORM trigger path (classic hold-at-top scope):
        #   - Rising edge at top restarts the ramp immediately.
        #   - First mid-sweep edge per sweep is latched; honoured once on
        #     enter-top (not level-held for the whole dwell — that free-ran).
        #   - ``trigger_always`` bypasses latch/holdoff.
        pending_trig = Signal()
        ramp_at_top = Signal()
        prev_ramp_at_top = Signal()
        ramp_restarted = Signal()
        enter_top = Signal()
        trig_seen = Signal()
        pending_fire = Signal()
        norm_fire = Signal()
        ramp_fire = Signal()

        m.d.comb += [
            ramp_at_top.eq(ramp.o.payload > fixed.Const(0.985, shape=PSQ)),
            ramp_restarted.eq(prev_ramp_at_top & ~ramp_at_top),
            enter_top.eq(ramp_at_top & ~prev_ramp_at_top),
            trig_seen.eq(trig.o.payload & trig.i.valid & trig.o.ready),
            pending_fire.eq(pending_trig & enter_top),
            norm_fire.eq(trig_seen & ramp_at_top & ~trigger_always),
            ramp_fire.eq(trigger_always | pending_fire | norm_fire),
        ]
        m.d.sync += prev_ramp_at_top.eq(ramp_at_top)

        with m.If(enable_clear | ramp_restarted):
            m.d.sync += pending_trig.eq(0)
        with m.Elif(trig_seen & ~trigger_always & ~ramp_at_top & ~pending_trig):
            m.d.sync += pending_trig.eq(1)

        m.d.comb += [
            trig.i.valid.eq(self.isplit4.o[0].valid),
            trig.i.payload.threshold.eq(trigger_lvl),
        ]
        with m.Switch(trigger_ch):
            for ch in range(self.n_channels):
                with m.Case(ch):
                    m.d.comb += trig.i.payload.sample.eq(self.isplit4.o[ch].payload)
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
        m.submodules.renderer = renderer = ColumnRenderer()

        # Progressive rendering: each column finished by the capture is pushed
        # into this FIFO and drawn immediately by the renderer, so the trace
        # paints live left-to-right as the ramp sweeps instead of waiting for a
        # whole acquire-then-render cycle.  Flushes are dropped if the FIFO is
        # full, which only happens at very fast timebases.
        flush_layout = data.StructLayout({
            "col": range(MAX_CAPTURE_COLS),
            "word": unsigned(128),
        })
        m.submodules.flush_fifo = flush_fifo = stream_util.SyncFIFOBuffered(
            shape=flush_layout, depth=256)

        # Capture runs continuously while enabled (after the power-on clear); it
        # rides the ramp and the internal ``armed`` gate restricts accumulation
        # to clean, complete, trigger-aligned sweeps.
        capturing = Signal()
        m.d.comb += capturing.eq(self.soc_en & ~region_clear.busy)

        m.d.comb += [
            capture.active.eq(capturing),
            capture.clear.eq(enable_clear),
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
            flush_fifo.i.valid.eq(capture.flush_valid),
            flush_fifo.i.payload.col.eq(capture.flush_col),
            flush_fifo.i.payload.word.eq(capture.flush_word),
            renderer.col_valid.eq(flush_fifo.o.valid),
            renderer.col.eq(flush_fifo.o.payload.col),
            renderer.word.eq(flush_fifo.o.payload.word),
            flush_fifo.o.ready.eq(renderer.col_ready),
            shown_rd.en.eq(renderer.s_en),
            shown_rd.addr.eq(renderer.s_addr),
            renderer.s_data.eq(shown_rd.data),
            shown_wr.en.eq(renderer.sw_en),
            shown_wr.addr.eq(renderer.sw_addr),
            shown_wr.data.eq(renderer.sw_data),
        ]
        for ch in range(self.n_channels):
            m.d.comb += [
                capture.scale_y[ch].eq(scale_y[ch]),
                capture.y_offset[ch].eq(y_offset[ch]),
                capture.visible[ch].eq(visible[ch]),
            ]


        m.d.comb += renderer.plot_x_lo.eq(plot_x_lo)
        for ch in range(self.n_channels):
            m.d.comb += [
                renderer.hue[ch].eq(hue[ch]),
                renderer.intensity[ch].eq(intensity[ch]),
                renderer.visible[ch].eq(visible[ch]),
            ]
            wiring.connect(m, renderer.line_o[ch], line_fifos[ch].i)

        rendering = Signal()
        m.d.comb += rendering.eq(renderer.busy)
        fsm_state = Signal(2)
        m.d.comb += fsm_state.eq(Cat(capturing, rendering))

        capture_done_cnt = Signal(8)
        # Per-sweep debug bytes (reset on each ``capture.sweep_done``):
        #   trigger_edges (top byte of ``ct``): column flushes dropped this sweep
        #   col_writes: column flushes emitted this sweep
        #   render_done: column flushes accepted by the renderer this sweep
        # Comparing drop vs flush counts shows render headroom; disabling channels
        # should lower both flush and drop counts at render-bound timebases.
        drop_sweep_cnt = Signal(8)
        flush_sweep_cnt = Signal(8)
        render_sweep_cnt = Signal(8)
        trig_sweep_cnt = Signal(8)
        ramp_restart_sweep_cnt = Signal(8)
        pen_lift_sweep_cnt = Signal(8)
        end_reached_sweep_cnt = Signal(8)
        flush_drop = Signal()
        flush_accept = Signal()
        trig_pulse = Signal()
        m.d.comb += [
            flush_drop.eq(capture.flush_valid & ~flush_fifo.i.ready),
            flush_accept.eq(flush_fifo.o.valid & renderer.col_ready),
            trig_pulse.eq(norm_fire | pending_fire),
        ]

        with m.If(capture.sweep_done):
            m.d.sync += [
                capture_done_cnt.eq(capture_done_cnt + 1),
                drop_sweep_cnt.eq(0),
                flush_sweep_cnt.eq(0),
                render_sweep_cnt.eq(0),
                trig_sweep_cnt.eq(0),
                ramp_restart_sweep_cnt.eq(0),
                pen_lift_sweep_cnt.eq(0),
                end_reached_sweep_cnt.eq(0),
            ]
        with m.If(flush_drop):
            m.d.sync += drop_sweep_cnt.eq(drop_sweep_cnt + 1)
        with m.If(capture.flush_valid):
            m.d.sync += flush_sweep_cnt.eq(flush_sweep_cnt + 1)
        with m.If(flush_accept):
            m.d.sync += render_sweep_cnt.eq(render_sweep_cnt + 1)
        with m.If(trig_pulse):
            m.d.sync += trig_sweep_cnt.eq(trig_sweep_cnt + 1)
        with m.If(ramp_restarted):
            m.d.sync += ramp_restart_sweep_cnt.eq(ramp_restart_sweep_cnt + 1)
        with m.If(capture.dbg_pen_lift):
            m.d.sync += pen_lift_sweep_cnt.eq(pen_lift_sweep_cnt + 1)
        with m.If(capture.dbg_end_reached):
            m.d.sync += end_reached_sweep_cnt.eq(end_reached_sweep_cnt + 1)

        # Render-path diagnostics: select the per-channel handshake signals for
        # whichever channel the renderer is currently drawing, and pack them into
        # a single word that we surface through the debug probe during render.
        sel_fifo_valid = Signal()
        sel_fifo_ready = Signal()
        sel_plotter_iready = Signal()
        sel_o_valid = Signal()
        sel_o_ready = Signal()
        with m.Switch(renderer.dbg_draw_ch):
            for ch in range(self.n_channels):
                with m.Case(ch):
                    m.d.comb += [
                        sel_fifo_valid.eq(line_fifos[ch].o.valid),
                        sel_fifo_ready.eq(line_fifos[ch].i.ready),
                        sel_plotter_iready.eq(line_plotters[ch].i.ready),
                        sel_o_valid.eq(self.o[ch].valid),
                        sel_o_ready.eq(self.o[ch].ready),
                    ]

        dbg_render_word = Signal(16)
        m.d.comb += dbg_render_word.eq(Cat(
            renderer.dbg_state,        # bits  2:0  render FSM state
            renderer.dbg_draw_ch,      # bits  4:3  channel being drawn
            renderer.dbg_pending,      # bit   5    LineCmd pending to emit
            sel_fifo_valid,            # bit   6    line FIFO has output
            sel_fifo_ready,            # bit   7    line FIFO accepts input
            sel_plotter_iready,        # bit   8    line plotter idle/ready
            sel_o_valid,               # bit   9    plotter port o.valid
            sel_o_ready,               # bit  10    plotter port o.ready (arbiter grant)
            renderer.dbg_pending,      # bit  11    renderer pending/erasing
        ))

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
            self._debug_status.f.renderer_busy.r_data.eq(renderer.busy),
            self._debug_status.f.renderer_done.r_data.eq(~renderer.busy),
            self._debug_status.f.ramp_at_top.r_data.eq(ramp_at_top),
            self._debug_status.f.armed.r_data.eq(capture.dbg_armed),
            self._debug_status.f.pending_trig.r_data.eq(pending_trig),
            self._debug_status.f.trig_pulse.r_data.eq(trig_pulse),
            self._debug_status.f.soc_en.r_data.eq(self.soc_en),
            self._debug_count.f.capture_done.r_data.eq(capture_done_cnt),
            self._debug_count.f.render_done.r_data.eq(render_sweep_cnt),
            self._debug_count.f.col_writes.r_data.eq(flush_sweep_cnt),
            self._debug_count.f.flush_drops.r_data.eq(drop_sweep_cnt),
            self._debug_trig.f.trig_edges.r_data.eq(trig_sweep_cnt),
            self._debug_trig.f.ramp_restarts.r_data.eq(ramp_restart_sweep_cnt),
            self._debug_trig.f.pen_lifts.r_data.eq(pen_lift_sweep_cnt),
            self._debug_trig.f.end_reached.r_data.eq(end_reached_sweep_cnt),
            self._debug_probe.f.in_x.r_data.eq(
                Mux(rendering, renderer.dbg_col, capture.dbg_in_x)
            ),
            self._debug_probe.f.in_y0.r_data.eq(
                Mux(rendering, dbg_render_word.as_signed(), capture.dbg_in_y0)
            ),
            self._debug_ncols.f.ncols.r_data.eq(
                Mux(rendering, self.dbg_plotter, ncols)
            ),
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
