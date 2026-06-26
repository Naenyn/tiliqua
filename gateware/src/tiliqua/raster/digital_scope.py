# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr

from .. import dsp
from ..dsp import stream_util
from ..video.framebuffer import DMAFramebuffer
from . import PSQ, PSQ_BASE_FBITS, psq_from_volts
from .clear import RegionClear
from .line import LineCmd, _LinePlotter
from .plot import OffsetMode, PlotRequest
from .plot_clip import PlotClip
from .trace import VectorTrace


class DigitalScopePeripheral(wiring.Component):

    """
    Four-channel digital oscilloscope with vector-trace rendering.

    Waveform erase/draw is confined to the plot rectangle programmed by the SoC.
    """

    class Flags(csr.Register, access="w"):
        enable: csr.Field(csr.action.W, unsigned(1))
        trigger_always: csr.Field(csr.action.W, unsigned(1))

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

    def __init__(self, n_channels=4, fs=48000):

        self.fs = fs
        self.n_channels = n_channels
        self.traces = [VectorTrace() for _ in range(self.n_channels)]

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

        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__({
            "i": In(stream.Signature(data.ArrayLayout(PSQ, self.n_channels))),
            "bus": In(csr.Signature(addr_width=7, data_width=8)),
            "fbp": In(DMAFramebuffer.Properties()),
            "o": Out(stream.Signature(PlotRequest)).array(self.n_channels),
            "clear_o": Out(stream.Signature(PlotRequest)),
            "soc_en": Out(unsigned(1), init=1),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()

        trigger_lvl = Signal(shape=PSQ)
        trigger_always = Signal()

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

        m.submodules += self.traces

        for n, trace in enumerate(self.traces):
            line_fifo = stream_util.SyncFIFOBuffered(shape=LineCmd, depth=256)
            line_plotter = _LinePlotter(offset=OffsetMode.CENTER)
            clip = PlotClip()
            setattr(m.submodules, f"line_fifo{n}", line_fifo)
            setattr(m.submodules, f"line_plotter{n}", line_plotter)
            setattr(m.submodules, f"plot_clip{n}", clip)
            m.d.comb += [
                clip.x_lo.eq(plot_x_lo),
                clip.x_hi.eq(plot_x_hi),
                clip.y_lo.eq(plot_y_lo),
                clip.y_hi.eq(plot_y_hi),
            ]
            wiring.connect(m, trace.line_o, line_fifo.i)
            wiring.connect(m, line_fifo.o, line_plotter.i)
            wiring.connect(m, line_plotter.o, clip.i)
            wiring.connect(m, clip.o, wiring.flipped(self.o[n]))

        enable_prev = Signal()
        enable_clear = Signal()
        m.d.comb += enable_clear.eq(self.soc_en & ~enable_prev)
        m.d.sync += enable_prev.eq(self.soc_en)

        m.submodules.region_clear = region_clear = RegionClear()
        m.submodules.clear_clip = clear_clip = PlotClip()
        wiring.connect(m, region_clear.o, clear_clip.i)
        wiring.connect(m, clear_clip.o, wiring.flipped(self.clear_o))
        m.d.comb += [
            region_clear.start.eq(enable_clear | self.traces[0].sweep_wrap),
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

        m.submodules.trig = trig = dsp.Trigger(shape=PSQ)
        m.submodules.ramp = ramp = dsp.Ramp(shape=PSQ)
        timebase = Signal(shape=dsp.Ramp.TIMEBASE_SQ)

        dsp.connect_remap(m, irep2.o[0], trig.i, lambda o, i: [
            i.payload.sample.eq(o.payload),
            i.payload.threshold.eq(trigger_lvl),
        ])
        dsp.connect_remap(m, trig.o, ramp.i, lambda o, i: [
            i.payload.trigger.eq(o.payload | trigger_always),
            i.payload.td.eq(timebase),
        ])

        m.submodules.rampsplit4 = rampsplit4 = dsp.Split(
            self.n_channels, replicate=True, source=ramp.o, shape=PSQ)

        m.submodules.ch0_merge4 = ch0_merge4 = dsp.Merge(4, shape=PSQ)
        dsp.connect_peek(m, ch0_merge4.o, self.traces[0].i, always_ready=True)
        ch0_merge4.wire_valid(m, [2, 3])
        wiring.connect(m, rampsplit4.o[0], ch0_merge4.i[0])
        wiring.connect(m, irep2.o[1], ch0_merge4.i[1])

        for ch in range(1, self.n_channels):
            ch_merge4 = dsp.Merge(4, shape=PSQ)
            dsp.connect_peek(m, ch_merge4.o, self.traces[ch].i, always_ready=True)
            m.submodules += ch_merge4
            ch_merge4.wire_valid(m, [2, 3])
            wiring.connect(m, rampsplit4.o[ch], ch_merge4.i[0])
            wiring.connect(m, self.isplit4.o[ch], ch_merge4.i[1])

        with m.If(self._flags.f.trigger_always.w_stb):
            m.d.sync += trigger_always.eq(self._flags.f.trigger_always.w_data)

        with m.If(self._hue.f.hue.w_stb):
            for ch, trace in enumerate(self.traces):
                m.d.sync += trace.hue.eq(self._hue.f.hue.w_data + ch*3)

        with m.If(self._intensity.f.intensity.w_stb):
            for trace in self.traces:
                m.d.sync += trace.intensity.eq(self._intensity.f.intensity.w_data)

        with m.If(self._timebase.f.timebase.w_stb):
            m.d.sync += timebase.as_value().eq(self._timebase.f.timebase.w_data)

        with m.If(self._xscale.f.xscale.w_stb):
            for trace in self.traces:
                m.d.sync += trace.scale_x.eq(self._xscale.f.xscale.w_data)

        for i, yscale_reg in enumerate(self._yscale):
            with m.If(yscale_reg.f.yscale.w_stb):
                m.d.sync += self.traces[i].scale_y.eq(yscale_reg.f.yscale.w_data)

        with m.If(self._channel_en.f.ch0.w_stb):
            m.d.sync += self.traces[0].visible.eq(self._channel_en.f.ch0.w_data)
        with m.If(self._channel_en.f.ch1.w_stb):
            m.d.sync += self.traces[1].visible.eq(self._channel_en.f.ch1.w_data)
        with m.If(self._channel_en.f.ch2.w_stb):
            m.d.sync += self.traces[2].visible.eq(self._channel_en.f.ch2.w_data)
        with m.If(self._channel_en.f.ch3.w_stb):
            m.d.sync += self.traces[3].visible.eq(self._channel_en.f.ch3.w_data)

        with m.If(self._trigger_lvl.f.trigger_level.w_stb):
            m.d.sync += trigger_lvl.as_value().eq(
                self._trigger_lvl.f.trigger_level.w_data.as_signed() >> (PSQ_BASE_FBITS - PSQ.f_bits))

        with m.If(self._xpos.f.xpos.w_stb):
            for trace in self.traces:
                m.d.sync += trace.x_offset.eq(self._xpos.f.xpos.w_data)

        for i, ypos_reg in enumerate(self._ypos):
            with m.If(ypos_reg.f.ypos.w_stb):
                m.d.sync += self.traces[i].y_offset.eq(ypos_reg.f.ypos.w_data)

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
