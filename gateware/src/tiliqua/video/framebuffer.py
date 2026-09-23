# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Implementation of PSRAM-backed framebuffer with a DVI PHY."""

from amaranth import *
from amaranth.build import *
from amaranth.lib import data, wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.fifo import AsyncFIFOBuffered
from amaranth.lib.wiring import In, Out
from amaranth.utils import exact_log2
from amaranth_soc import csr, wishbone

from ..build import sim
from . import dvi
from .types import DVIPixel, Pixel, Rotation, ScanPixel


class DMAFramebuffer(wiring.Component):

    """
    Interpret a PSRAM region as a framebuffer, effectively DMAing it to the display.
    - 'sync' domain: Pixels are DMA'd from PSRAM as a wishbone master in bursts,
       whenever 'burst_threshold_words' space is available in the FIFO.
    - 'dvi' domain: FIFO is drained to the display as required by DVI timings.
    Framebuffer storage: currently fixed at 1byte/pix: 4-bit intensity, 4-bit color.
    """

    class Properties(wiring.Signature):
        """
        Dynamic information required by other cores in order to be able to plot to the framebuffer.
        Current base address, video mode, rotation and so on.
        """
        def __init__(self):
            super().__init__({
                # Base address of framebuffer in PSRAM
                "base": Out(22),
                # Independent target for raster engines. Existing users set
                # this to `base`; double-buffered users draw elsewhere.
                "draw_base": Out(22),
                # Must be updated on timing changes
                "timings": Out(dvi.DVITimingGen.TimingProperties()),
                # Not directly used by this core but shared between every core that uses DMAFramebuffer.
                "enable": Out(1), # Framebuffer is being sent to screen
                "rotation": Out(Rotation),
            })

    class SimulationInterface(wiring.Signature):
        """
        Enough information for simulation to plot the output of this core to bitmaps.
        """
        def __init__(self):
            super().__init__({
                "de": Out(1),
                "vsync": Out(1),
                "hsync": Out(1),
                "r": Out(8),
                "g": Out(8),
                "b": Out(8),
            })

    def __init__(self, *, palette, addr_width=22, fifo_depth=512,
                 burst_threshold_words=128, fixed_modeline=None, overlay=None,
                 pipeline_palette_output=False, frame_exchange=None):

        self.fifo_depth = fifo_depth
        assert (Pixel.as_shape().size % 8) == 0
        self.bytes_per_pixel = Pixel.as_shape().size // 8
        self.burst_threshold_words = burst_threshold_words
        self.fixed_modeline = fixed_modeline
        self.palette = palette
        self._overlay = overlay
        self.pipeline_palette_output = pipeline_palette_output
        # Opt-in reader-owned background acquisition. Existing bitstreams keep
        # their original path until coordinated scene publication is integrated.
        self.frame_exchange = frame_exchange
        if frame_exchange is not None:
            assert 0 < burst_threshold_words < fifo_depth

        super().__init__({
            # Backing store
            "bus":  Out(wishbone.Signature(addr_width=addr_width, data_width=32, granularity=8,
                                           features={"cti", "bte"})),
            # Assert while scanout is consuming its reserve and the PSRAM DMA
            # should take precedence over non-real-time framebuffer writers.
            "scanout_urgent": Out(1),
            # Dynamic timing / modeline information shared with other cores.
            "fbp": In(self.Properties()),
            # Enough information to plot the output of this core to images
            "simif": Out(self.SimulationInterface())
        })

    def elaborate(self, platform) -> Module:
        m = Module()

        if self.fixed_modeline is not None:
            for member in self.fbp.timings.signature.members:
                m.d.comb += getattr(self.fbp.timings, member).eq(getattr(self.fixed_modeline, member))

        m.submodules.fifo = fifo = AsyncFIFOBuffered(
                width=32, depth=self.fifo_depth, r_domain='dvi', w_domain='sync')
        m.d.comb += self.scanout_urgent.eq(
            fifo.w_level < self.fifo_depth - self.burst_threshold_words)

        m.submodules.dvi_tgen = dvi_tgen = dvi.DVITimingGen()

        # TODO: FFSync needed? (sync -> dvi crossing, but should always be in reset when changed).
        wiring.connect(m, wiring.flipped(self.fbp.timings), dvi_tgen.timings)

        # Register VSync before it controls the scanout FIFO. The timing
        # generator derives VSync combinationally from the current X/Y
        # counters; using that expression directly for the byte counter made
        # one DVI-clock path continue through FIFO readiness, its Gray-code
        # read-pointer increment, and finally the block-RAM address. VSync is
        # asserted for many pixel clocks, so this one-cycle internal delay
        # does not change frame alignment while giving the FIFO path a clean
        # register boundary.
        phy_vsync_dvi = Signal()
        m.d.dvi += phy_vsync_dvi.eq(dvi_tgen.ctrl.vsync)

        # Create a VSync signal in the 'sync' domain. Decoupled from display VSync inversion!
        phy_vsync_sync = Signal()
        m.submodules.vsync_ff = FFSynchronizer(
                i=phy_vsync_dvi, o=phy_vsync_sync, o_domain="sync")

        # DMA master bus
        bus = self.bus

        # Current offset into the framebuffer
        dma_addr = Signal(32)
        scan_base = Signal.like(self.fbp.base)
        burst_cnt = Signal(16, init=0)

        if self.frame_exchange is not None:
            m.submodules.frame_exchange = self.frame_exchange
            previous_vsync = Signal()
            m.d.sync += previous_vsync.eq(phy_vsync_sync)
            frame_start = phy_vsync_sync & ~previous_vsync

        # DMA bus master -> FIFO state machine
        # Burst until FIFO is full, then wait until half empty.

        fb_size_words = (self.fbp.timings.active_pixels * self.bytes_per_pixel) // 4

        # Read to FIFO in sync domain
        with m.FSM() as fsm:
            with m.State('WAIT-VSYNC'):
                with m.If(phy_vsync_sync if self.frame_exchange is None else frame_start):
                    m.d.sync += dma_addr.eq(0)
                    if self.frame_exchange is None:
                        # Latch the base for the entire scan to avoid tearing.
                        m.d.sync += scan_base.eq(self.fbp.base)
                    else:
                        m.d.comb += self.frame_exchange.acquire.eq(1)
                        m.d.sync += scan_base.eq(self.frame_exchange.next_base)
                    m.next = 'WAIT'
            with m.State('BURST'):
                m.d.comb += [
                    bus.stb.eq(1),
                    bus.cyc.eq(1),
                    bus.we.eq(0),
                    bus.sel.eq(2**(bus.data_width//8)-1),
                    bus.adr.eq(scan_base + dma_addr),
                    fifo.w_en.eq(bus.ack),
                    fifo.w_data.eq(bus.dat_r),
                    bus.cti.eq(
                        wishbone.CycleType.INCR_BURST),
                ]

                with m.If(bus.ack):
                    m.d.sync += [
                        burst_cnt.eq(burst_cnt + 1),
                        dma_addr.eq(dma_addr+1),
                    ]

                if self.frame_exchange is None:
                    with m.If((fifo.w_level == (self.fifo_depth-1)) |
                              (burst_cnt == self.burst_threshold_words)):
                        m.d.comb += bus.cti.eq(wishbone.CycleType.END_OF_BURST)
                        m.next = 'WAIT'
                    with m.If(dma_addr == (fb_size_words-1)):
                        m.d.comb += bus.cti.eq(wishbone.CycleType.END_OF_BURST)
                        m.next = 'WAIT-VSYNC'
                else:
                    # WAIT reserves a whole burst's FIFO capacity. Termination
                    # depends on counters, not a changing FIFO level, so CTI and
                    # address stay stable during arbitrarily delayed bus ACKs.
                    last_word = dma_addr == (fb_size_words - 1)
                    end_burst = burst_cnt == (self.burst_threshold_words - 1)
                    with m.If(last_word | end_burst):
                        m.d.comb += bus.cti.eq(wishbone.CycleType.END_OF_BURST)
                        with m.If(bus.ack):
                            with m.If(last_word):
                                m.next = 'WAIT-VSYNC'
                            with m.Else():
                                m.next = 'WAIT'

            with m.State('WAIT'):
                with m.If(fifo.w_level < self.fifo_depth-self.burst_threshold_words):
                    m.d.sync += burst_cnt.eq(0)
                    m.next = 'BURST'

        # -- DVI domain pixel stream to PHY --

        # Stage 1: FIFO read -> ScanPixel
        # (1 FIFO word is N pixels, extracted byte-by-byte)
        bytecounter = Signal(exact_log2(4//self.bytes_per_pixel))
        last_word   = Signal(32)
        with m.If(phy_vsync_dvi):
            m.d.dvi += bytecounter.eq(0)
        word_available = fifo.r_rdy if self.frame_exchange is None else (fifo.r_rdy | (bytecounter != 0))
        with m.Elif(dvi_tgen.ctrl.de & word_available):
            m.d.comb += fifo.r_en.eq(bytecounter == 0),
            m.d.dvi += bytecounter.eq(bytecounter+1)
            with m.If(bytecounter == 0):
                m.d.dvi += last_word.eq(fifo.r_data)
            with m.Else():
                m.d.dvi += last_word.eq(last_word >> 8)

        # 1-cycle delayed x/y to align with last_word
        pixel_x = Signal(signed(12))
        pixel_y = Signal(signed(12))
        m.d.dvi += pixel_x.eq(dvi_tgen.x)
        m.d.dvi += pixel_y.eq(dvi_tgen.y)

        # Stage 1.5: Optional beamracing overlay (ScanPixel -> ScanPixel)
        if self._overlay is not None:
            first_input = self._overlay.i
            m.d.comb += self.palette.i.eq(self._overlay.o)
        else:
            first_input = self.palette.i

        m.d.comb += [
            first_input.pixel.eq(last_word[:Pixel.as_shape().size]),
            first_input.x.eq(pixel_x),
            first_input.y.eq(pixel_y),
            first_input.de.eq(dvi_tgen.ctrl_phy.de),
            first_input.hsync.eq(dvi_tgen.ctrl_phy.hsync),
            first_input.vsync.eq(dvi_tgen.ctrl_phy.vsync),
        ]
        if self.frame_exchange is not None:
            # Align active/sync flags with the registered pixel and coordinates.
            de, hs, vs = Signal(), Signal(), Signal()
            m.d.dvi += [de.eq(dvi_tgen.ctrl_phy.de), hs.eq(dvi_tgen.ctrl_phy.hsync),
                        vs.eq(dvi_tgen.ctrl_phy.vsync)]
            m.d.comb += [first_input.de.eq(de), first_input.hsync.eq(hs),
                        first_input.vsync.eq(vs)]

        # Stage 2/3: Palette and DVI PHY / simulation output
        if sim.is_hw(platform):
            m.submodules.dvi_gen = dvi_gen = dvi.DVIPHY(
                circular_shift=getattr(self, "serializer_circular_shift", False))
            if self.pipeline_palette_output:
                # Opt-in timing stage for dense designs: keep RGB and control
                # aligned while breaking the palette RAM -> TMDS critical path.
                phy_pixel = Signal(DVIPixel)
                m.d.dvi += phy_pixel.eq(self.palette.o)
                m.d.comb += dvi_gen.i.eq(phy_pixel)
            else:
                m.d.comb += dvi_gen.i.eq(self.palette.o)
        else:
            m.d.comb += [
                self.simif.de.eq(self.palette.o.de),
                self.simif.vsync.eq(self.palette.o.vsync),
                self.simif.hsync.eq(self.palette.o.hsync),
                self.simif.r.eq(self.palette.o.r),
                self.simif.g.eq(self.palette.o.g),
                self.simif.b.eq(self.palette.o.b),
            ]

        return m


class Peripheral(wiring.Component):

    """
    CSR peripheral for tweaking framebuffer timing/palette parameters from an SoC.
    Timing values follow the same format as DVIModeline in modeline.py.
    """

    class HTimingReg(csr.Register, access="w"):
        h_active:     csr.Field(csr.action.W, unsigned(16))
        h_sync_start: csr.Field(csr.action.W, unsigned(16))

    class HTimingReg2(csr.Register, access="w"):
        h_sync_end:   csr.Field(csr.action.W, unsigned(16))
        h_total:      csr.Field(csr.action.W, unsigned(16))

    class VTimingReg(csr.Register, access="w"):
        v_active:     csr.Field(csr.action.W, unsigned(16))
        v_sync_start: csr.Field(csr.action.W, unsigned(16))

    class VTimingReg2(csr.Register, access="w"):
        v_sync_end:   csr.Field(csr.action.W, unsigned(16))
        v_total:      csr.Field(csr.action.W, unsigned(16))

    class HVTimingReg(csr.Register, access="w"):
        h_sync_invert: csr.Field(csr.action.W, unsigned(1))
        v_sync_invert: csr.Field(csr.action.W, unsigned(1))
        active_pixels: csr.Field(csr.action.W, unsigned(30))

    class FlagsReg(csr.Register, access="w"):
        enable:        csr.Field(csr.action.W, unsigned(1))
        rotation:      csr.Field(csr.action.W, Rotation)

    class FBBaseReg(csr.Register, access="w"):
        fb_base: csr.Field(csr.action.W, unsigned(32))

    class DrawBaseReg(csr.Register, access="w"):
        draw_base: csr.Field(csr.action.W, unsigned(32))

    class HpdReg(csr.Register, access="r"):
        # DVI hot plug detect
        hpd: csr.Field(csr.action.R, unsigned(1))

    def __init__(self):
        regs = csr.Builder(addr_width=6, data_width=8)

        self._h_timing     = regs.add("h_timing",     self.HTimingReg(),     offset=0x00)
        self._h_timing2    = regs.add("h_timing2",    self.HTimingReg2(),    offset=0x04)
        self._v_timing     = regs.add("v_timing",     self.VTimingReg(),     offset=0x08)
        self._v_timing2    = regs.add("v_timing2",    self.VTimingReg2(),    offset=0x0C)
        self._hv_timing    = regs.add("hv_timing",    self.HVTimingReg(),    offset=0x10)
        self._flags        = regs.add("flags",        self.FlagsReg(),       offset=0x14)
        self._fb_base      = regs.add("fb_base",      self.FBBaseReg(),      offset=0x18)
        self._hpd          = regs.add("hpd",          self.HpdReg(),         offset=0x1C)
        self._draw_base    = regs.add("draw_base",    self.DrawBaseReg(),    offset=0x20)

        self._bridge = csr.Bridge(regs.as_memory_map())

        super().__init__({
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
            "fbp": Out(DMAFramebuffer.Properties()),
        })

        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform) -> Module:
        m = Module()

        m.submodules.bridge = self._bridge
        draw_base_explicit = Signal()

        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        with m.If(self._h_timing.element.w_stb):
            m.d.sync += self.fbp.timings.h_active.eq(self._h_timing.f.h_active.w_data)
            m.d.sync += self.fbp.timings.h_sync_start.eq(self._h_timing.f.h_sync_start.w_data)
        with m.If(self._h_timing2.element.w_stb):
            m.d.sync += self.fbp.timings.h_sync_end.eq(self._h_timing2.f.h_sync_end.w_data)
            m.d.sync += self.fbp.timings.h_total.eq(self._h_timing2.f.h_total.w_data)
        with m.If(self._v_timing.element.w_stb):
            m.d.sync += self.fbp.timings.v_active.eq(self._v_timing.f.v_active.w_data)
            m.d.sync += self.fbp.timings.v_sync_start.eq(self._v_timing.f.v_sync_start.w_data)
        with m.If(self._v_timing2.element.w_stb):
            m.d.sync += self.fbp.timings.v_sync_end.eq(self._v_timing2.f.v_sync_end.w_data)
            m.d.sync += self.fbp.timings.v_total.eq(self._v_timing2.f.v_total.w_data)
        with m.If(self._hv_timing.element.w_stb):
            m.d.sync += self.fbp.timings.h_sync_invert.eq(self._hv_timing.f.h_sync_invert.w_data)
            m.d.sync += self.fbp.timings.v_sync_invert.eq(self._hv_timing.f.v_sync_invert.w_data)
            m.d.sync += self.fbp.timings.active_pixels.eq(self._hv_timing.f.active_pixels.w_data)
        with m.If(self._flags.f.enable.w_stb):
            m.d.sync += self.fbp.enable.eq(self._flags.f.enable.w_data)
        with m.If(self._flags.f.rotation.w_stb):
            m.d.sync += self.fbp.rotation.eq(self._flags.f.rotation.w_data)
        with m.If(self._fb_base.f.fb_base.w_stb):
            m.d.sync += self.fbp.base.eq(self._fb_base.f.fb_base.w_data)
            with m.If(~draw_base_explicit):
                m.d.sync += self.fbp.draw_base.eq(self._fb_base.f.fb_base.w_data)
        with m.If(self._draw_base.f.draw_base.w_stb):
            m.d.sync += [
                self.fbp.draw_base.eq(self._draw_base.f.draw_base.w_data),
                draw_base_explicit.eq(1),
            ]

        if sim.is_hw(platform):
            m.d.comb += self._hpd.f.hpd.r_data.eq(platform.request("dvi_hpd").i)
        else:
            # Fake connected screen in simulation
            m.d.comb += self._hpd.f.hpd.r_data.eq(1)

        return m
