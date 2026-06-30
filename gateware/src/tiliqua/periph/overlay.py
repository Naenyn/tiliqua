# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Grid video overlay for scope bitstreams."""

from amaranth import *
from amaranth.lib import data, enum, wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out
from amaranth.utils import ceil_log2
from amaranth_soc import csr

from ..video.types import Pixel, Rotation, ScanPixel
from . import ui_overlay


class OverlayPipeline(wiring.Component):
    """Grid overlay followed by optional menu UI layer."""

    def __init__(self, *, enable_ui: bool = False, trace=None):
        self.enable_ui = enable_ui
        self.trace = trace
        self.grid = GridOverlay()
        if enable_ui:
            self.ui = ui_overlay.UiMenuOverlay()
        super().__init__({
            "i": In(ScanPixel),
            "o": Out(ScanPixel),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.grid = self.grid
        if self.trace is not None:
            m.submodules.trace = self.trace
            m.d.comb += [
                self.trace.i.eq(self.i),
                self.grid.i.eq(self.trace.o),
            ]
        else:
            m.d.comb += self.grid.i.eq(self.i)
        if self.enable_ui:
            m.submodules.ui = self.ui
            m.d.comb += [
                self.ui.i.eq(self.grid.o),
                self.o.eq(self.ui.o),
            ]
        else:
            m.d.comb += self.o.eq(self.grid.o)

        return m


class GridOverlay(wiring.Component):

    """
    Beamracing grid overlay, takes a pixel with DVI timings,
    emits another pixel with DVI timings with the grid applied
    (blended with the incoming pixels, intensity sum with saturation).

    All control inputs in 'sync' domain, video in 'dvi' domain.
    """

    class Style(enum.Enum, shape=unsigned(2)):
        OFF   = 0
        GRID  = 1 # simple grid (squares)
        CROSS = 2 # horiz. and vert. axes with ticks

    def __init__(self):
        super().__init__({
            # dvi domain
            "i": In(ScanPixel),
            "o": Out(ScanPixel),
            # sync domain (CDC'd internally)
            "style": In(GridOverlay.Style),
            "pixel": In(Pixel),    # overlay pixel color/intensity
                                   # this is blended with saturation with the incoming pixel.
            "spacing_x": In(8),    # grid/tick spacing in pixels
            "spacing_y": In(8),    # grid/tick spacing in pixels
            # start_{x,y} is exposed to the SoC so we don't need to synthesize
            # a divider for this core, which is expensive.
            "start_x": In(8),      # initial x counter (offset_x % spacing_x)
            "start_y": In(8),      # initial y counter (offset_y % spacing_y)
            "offset_x": In(12),    # grid center x (for Style.CROSS only)
            "offset_y": In(12),    # grid center y (for Style.CROSS only)
        })

    def elaborate(self, platform):
        m = Module()

        # CDC: bring sync control signals -> dvi
        style_dvi = Signal(2)
        pixel_dvi = Signal(Pixel)
        offset_x_dvi = Signal(12)
        offset_y_dvi = Signal(12)
        spacing_x_dvi = Signal(8)
        spacing_y_dvi = Signal(8)
        m.submodules.style_ff = FFSynchronizer(
            i=self.style, o=style_dvi, o_domain="dvi")
        m.submodules.pixel_i_ff = FFSynchronizer(
            i=self.pixel.intensity, o=pixel_dvi.intensity, o_domain="dvi")
        m.submodules.pixel_c_ff = FFSynchronizer(
            i=self.pixel.color, o=pixel_dvi.color, o_domain="dvi")
        m.submodules.offset_x_ff = FFSynchronizer(
            i=self.offset_x, o=offset_x_dvi, o_domain="dvi")
        m.submodules.offset_y_ff = FFSynchronizer(
            i=self.offset_y, o=offset_y_dvi, o_domain="dvi")
        start_x_dvi = Signal(8)
        start_y_dvi = Signal(8)
        m.submodules.spacing_x_ff = FFSynchronizer(
            i=self.spacing_x, o=spacing_x_dvi, o_domain="dvi")
        m.submodules.spacing_y_ff = FFSynchronizer(
            i=self.spacing_y, o=spacing_y_dvi, o_domain="dvi")
        m.submodules.start_x_ff = FFSynchronizer(
            i=self.start_x, o=start_x_dvi, o_domain="dvi")
        m.submodules.start_y_ff = FFSynchronizer(
            i=self.start_y, o=start_y_dvi, o_domain="dvi")

        # pass through pixels by default (WARN: assumes 1-cycle pipeline)
        m.d.dvi += self.o.eq(self.i)

        # Detect start of active line (de rising edge)
        prev_de = Signal()
        m.d.dvi += prev_de.eq(self.i.de)
        line_start = Signal()
        m.d.comb += line_start.eq(self.i.de & ~prev_de)

        # Detect start of frame (vsync rising edge)
        prev_vsync = Signal()
        m.d.dvi += prev_vsync.eq(self.i.vsync)
        vsync_rise = Signal()
        m.d.comb += vsync_rise.eq(self.i.vsync & ~prev_vsync)

        # Grid position counters (count down, 0 is on-grid)
        cnt_x = Signal(8)
        cnt_y = Signal(8)
        on_grid_x = Signal()
        on_grid_y = Signal()

        # X: reload on line start, count down during active
        m.d.comb += on_grid_x.eq(cnt_x == 0)
        with m.If(line_start):
            m.d.dvi += cnt_x.eq(start_x_dvi)
        with m.Elif(self.i.de):
            with m.If(cnt_x == 0):
                m.d.dvi += cnt_x.eq(spacing_x_dvi - 1)
            with m.Else():
                m.d.dvi += cnt_x.eq(cnt_x - 1)

        # Y: reload on frame start, count down at each line start
        m.d.comb += on_grid_y.eq(cnt_y == 0)
        with m.If(vsync_rise):
            m.d.dvi += cnt_y.eq(start_y_dvi)
        with m.Elif(line_start):
            with m.If(cnt_y == 0):
                m.d.dvi += cnt_y.eq(spacing_y_dvi - 1)
            with m.Else():
                m.d.dvi += cnt_y.eq(cnt_y - 1)

        # Center/near-center for Style.CROSS
        TICK_HALF = 5
        on_center_x = Signal()
        on_center_y = Signal()
        near_center_x = Signal()
        near_center_y = Signal()
        dx = Signal(signed(12))
        dy = Signal(signed(12))
        m.d.comb += [
            dx.eq(self.i.x - offset_x_dvi),
            dy.eq(self.i.y - offset_y_dvi),
            on_center_x.eq(dx == 0),
            on_center_y.eq(dy == 0),
            near_center_x.eq((dx >= -TICK_HALF) & (dx <= TICK_HALF)),
            near_center_y.eq((dy >= -TICK_HALF) & (dy <= TICK_HALF)),
        ]

        # Is this an overlay pixel?
        hit = Signal()
        with m.Switch(style_dvi):
            with m.Case(GridOverlay.Style.GRID):
                m.d.comb += hit.eq(on_grid_x | on_grid_y)
            with m.Case(GridOverlay.Style.CROSS):
                m.d.comb += hit.eq(
                    on_center_x | on_center_y |
                    (on_grid_x & near_center_y) |
                    (on_grid_y & near_center_x))

        # If yes, blend intensity with saturation.
        new_intensity = Signal.like(self.i.pixel.intensity)
        with m.If(self.i.pixel.intensity + pixel_dvi.intensity >= Pixel.intensity_max()):
            m.d.comb += new_intensity.eq(Pixel.intensity_max())
        with m.Else():
            m.d.comb += new_intensity.eq(self.i.pixel.intensity + pixel_dvi.intensity)
        with m.If(self.i.de & hit):
            m.d.dvi += [
                self.o.pixel.intensity.eq(new_intensity),
                self.o.pixel.color.eq(pixel_dvi.color),
            ]

        return m


class Peripheral(wiring.Component):
    """SoC controls for the grid overlay and optional UI layers."""

    class Flags(csr.Register, access="w"):
        grid_style: csr.Field(csr.action.W, unsigned(2))
        grid_pixel: csr.Field(csr.action.W, Pixel)

    class GridSpacing(csr.Register, access="w"):
        spacing_x: csr.Field(csr.action.W, unsigned(8))
        spacing_y: csr.Field(csr.action.W, unsigned(8))

    class GridStart(csr.Register, access="w"):
        start_x: csr.Field(csr.action.W, unsigned(8))
        start_y: csr.Field(csr.action.W, unsigned(8))

    class GridOffset(csr.Register, access="w"):
        offset_x: csr.Field(csr.action.W, unsigned(12))
        offset_y: csr.Field(csr.action.W, unsigned(12))

    class UiControl(csr.Register, access="w"):
        menu_enable: csr.Field(csr.action.W, unsigned(1))
        menu_transparent: csr.Field(csr.action.W, unsigned(1))
        rotation: csr.Field(csr.action.W, Rotation)

    class UiMenuPixel(csr.Register, access="w"):
        pixel: csr.Field(csr.action.W, Pixel)

    class UiMenuOrigin(csr.Register, access="w"):
        origin_x: csr.Field(csr.action.W, signed(12))
        origin_y: csr.Field(csr.action.W, signed(12))

    class UiTimings(csr.Register, access="w"):
        h_active: csr.Field(csr.action.W, unsigned(12))
        v_active: csr.Field(csr.action.W, unsigned(12))

    class UiMemAddr(csr.Register, access="w"):
        addr: csr.Field(csr.action.W, unsigned(ceil_log2(ui_overlay.UI_MEM_WORDS)))

    class UiMemData(csr.Register, access="w"):
        data: csr.Field(csr.action.W, unsigned(32))

    def __init__(self, *, enable_ui: bool = False, trace=None):
        self.enable_ui = enable_ui
        self.overlay = OverlayPipeline(enable_ui=enable_ui, trace=trace)

        regs = csr.Builder(addr_width=6 if enable_ui else 5, data_width=8)
        self._flags        = regs.add("flags",        self.Flags(),       offset=0x0)
        self._grid_spacing = regs.add("grid_spacing", self.GridSpacing(), offset=0x4)
        self._grid_start   = regs.add("grid_start",   self.GridStart(),   offset=0x8)
        self._grid_offset  = regs.add("grid_offset",  self.GridOffset(),  offset=0xC)
        if enable_ui:
            self._ui_control    = regs.add("ui_control",    self.UiControl(),    offset=0x10)
            self._ui_menu_pixel  = regs.add("ui_menu_pixel",  self.UiMenuPixel(),  offset=0x14)
            self._ui_menu_origin = regs.add("ui_menu_origin", self.UiMenuOrigin(), offset=0x18)
            self._ui_timings    = regs.add("ui_timings",    self.UiTimings(),    offset=0x1C)
            self._ui_mem_addr   = regs.add("ui_mem_addr",   self.UiMemAddr(),    offset=0x20)
            self._ui_mem_data   = regs.add("ui_mem_data",   self.UiMemData(),    offset=0x24)
            self.ui_mem = ui_overlay.UiMemory()

        self._bridge = csr.Bridge(regs.as_memory_map())

        ports = {
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
        }
        super().__init__(ports)
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()

        m.submodules.bridge = self._bridge
        m.submodules.overlay = self.overlay
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        with m.If(self._flags.f.grid_style.w_stb):
            m.d.sync += self.overlay.grid.style.eq(self._flags.f.grid_style.w_data)

        with m.If(self._flags.f.grid_pixel.w_stb):
            m.d.sync += self.overlay.grid.pixel.eq(self._flags.f.grid_pixel.w_data)

        with m.If(self._grid_spacing.element.w_stb):
            m.d.sync += self.overlay.grid.spacing_x.eq(self._grid_spacing.f.spacing_x.w_data)
            m.d.sync += self.overlay.grid.spacing_y.eq(self._grid_spacing.f.spacing_y.w_data)

        with m.If(self._grid_start.element.w_stb):
            m.d.sync += self.overlay.grid.start_x.eq(self._grid_start.f.start_x.w_data)
            m.d.sync += self.overlay.grid.start_y.eq(self._grid_start.f.start_y.w_data)

        with m.If(self._grid_offset.element.w_stb):
            m.d.sync += self.overlay.grid.offset_x.eq(self._grid_offset.f.offset_x.w_data)
            m.d.sync += self.overlay.grid.offset_y.eq(self._grid_offset.f.offset_y.w_data)

        if self.enable_ui:
            m.submodules.ui_mem = self.ui_mem
            ui = self.overlay.ui

            menu_enable_r = Signal(reset=0)
            menu_transparent_r = Signal(reset=0)
            rotation_r = Signal(Rotation, reset=Rotation.NORMAL)
            menu_pixel_r = Signal(Pixel)
            menu_origin_x_r = Signal(signed(12), reset=0)
            menu_origin_y_r = Signal(signed(12), reset=0)
            h_active_r = Signal(12, reset=0)
            v_active_r = Signal(12, reset=0)

            m.d.comb += [
                ui.menu_enable.eq(menu_enable_r),
                ui.menu_transparent.eq(menu_transparent_r),
                ui.rotation.eq(rotation_r),
                ui.menu_pixel.eq(menu_pixel_r),
                ui.menu_origin_x.eq(menu_origin_x_r),
                ui.menu_origin_y.eq(menu_origin_y_r),
                ui.h_active.eq(h_active_r),
                ui.v_active.eq(v_active_r),
                ui.menu_rdata.eq(self.ui_mem.menu_rdata),
                self.ui_mem.menu_raddr.eq(ui.menu_raddr),
            ]

            with m.If(self._ui_control.element.w_stb):
                m.d.sync += [
                    menu_enable_r.eq(self._ui_control.f.menu_enable.w_data),
                    menu_transparent_r.eq(self._ui_control.f.menu_transparent.w_data),
                    rotation_r.eq(self._ui_control.f.rotation.w_data),
                ]

            with m.If(self._ui_menu_pixel.element.w_stb):
                m.d.sync += menu_pixel_r.eq(self._ui_menu_pixel.f.pixel.w_data)

            with m.If(self._ui_menu_origin.element.w_stb):
                m.d.sync += [
                    menu_origin_x_r.eq(self._ui_menu_origin.f.origin_x.w_data),
                    menu_origin_y_r.eq(self._ui_menu_origin.f.origin_y.w_data),
                ]

            with m.If(self._ui_timings.element.w_stb):
                m.d.sync += [
                    h_active_r.eq(self._ui_timings.f.h_active.w_data),
                    v_active_r.eq(self._ui_timings.f.v_active.w_data),
                ]

            ui_mem_addr_r = Signal(ceil_log2(ui_overlay.UI_MEM_WORDS), reset=0)
            with m.If(self._ui_mem_addr.element.w_stb):
                m.d.sync += ui_mem_addr_r.eq(self._ui_mem_addr.f.addr.w_data)

            m.d.comb += [
                self.ui_mem.host_waddr.eq(ui_mem_addr_r),
                self.ui_mem.host_wdata.eq(self._ui_mem_data.f.data.w_data),
                self.ui_mem.host_wen.eq(self._ui_mem_data.element.w_stb),
            ]
            with m.If(self._ui_mem_data.element.w_stb):
                m.d.sync += ui_mem_addr_r.eq(ui_mem_addr_r + 1)

        return m
