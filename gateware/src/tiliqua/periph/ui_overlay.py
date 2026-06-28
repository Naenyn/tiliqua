# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Hardware UI overlay composited at DVI read time."""

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.memory import Memory
from amaranth.lib.wiring import In, Out
from amaranth.utils import ceil_log2, exact_log2
from amaranth_soc import wishbone
from amaranth_soc.memory import MemoryMap

from ..video.types import Pixel, Rotation, ScanPixel

# Right-side options panel (local coordinates 0..width-1, 0..height-1).
MENU_W = 250
# Tall enough for CH 1-2 (9 rows) with one blank line between channel groups.
MENU_H = 160

MENU_BITS = MENU_W * MENU_H
MENU_WORDS = (MENU_BITS + 31) // 32
UI_MEM_WORDS = MENU_WORDS
UI_MEM_BYTES = UI_MEM_WORDS * 4


class UiMenuOverlay(wiring.Component):
    """
    Composites a 1bpp menu bitmap over the incoming video stream.

    One registered pixel stage matches the BRAM read latency so bitmap bits
    align with the scan coordinates (same pattern as :class:`GridOverlay`).
    When ``menu_enable`` is low the pixel stream passes through unchanged.
    """

    def __init__(self):
        super().__init__({
            "i": In(ScanPixel),
            "o": Out(ScanPixel),
            "menu_enable": In(1),
            "menu_transparent": In(1),
            "menu_pixel": In(Pixel),
            "menu_origin_x": In(signed(12)),
            "menu_origin_y": In(signed(12)),
            "rotation": In(Rotation),
            "h_active": In(12),
            "v_active": In(12),
            "menu_rdata": In(32),
            "menu_raddr": Out(ceil_log2(MENU_WORDS)),
        })

    def _logical_xy(self, m, px, py, rotation, h_active, v_active, log_x, log_y):
        with m.Switch(rotation):
            with m.Case(Rotation.NORMAL):
                m.d.comb += [log_x.eq(px), log_y.eq(py)]
            with m.Case(Rotation.LEFT):
                m.d.comb += [
                    log_x.eq(py),
                    log_y.eq(h_active - 1 - px),
                ]
            with m.Case(Rotation.INVERTED):
                m.d.comb += [
                    log_x.eq(h_active - 1 - px),
                    log_y.eq(v_active - 1 - py),
                ]
            with m.Case(Rotation.RIGHT):
                m.d.comb += [
                    log_x.eq(v_active - 1 - py),
                    log_y.eq(px),
                ]

    def elaborate(self, platform):
        m = Module()

        menu_en_dvi = Signal()
        menu_transparent_dvi = Signal()
        menu_px_dvi = Signal(Pixel)
        menu_ox_dvi = Signal(signed(12))
        menu_oy_dvi = Signal(signed(12))
        rotation_dvi = Signal(Rotation)
        h_active_dvi = Signal(12)
        v_active_dvi = Signal(12)

        m.submodules.menu_en_ff = FFSynchronizer(
            i=self.menu_enable, o=menu_en_dvi, o_domain="dvi")
        m.submodules.menu_transparent_ff = FFSynchronizer(
            i=self.menu_transparent, o=menu_transparent_dvi, o_domain="dvi")
        m.submodules.menu_ox_ff = FFSynchronizer(
            i=self.menu_origin_x, o=menu_ox_dvi, o_domain="dvi")
        m.submodules.menu_oy_ff = FFSynchronizer(
            i=self.menu_origin_y, o=menu_oy_dvi, o_domain="dvi")
        m.submodules.rotation_ff = FFSynchronizer(
            i=self.rotation, o=rotation_dvi, o_domain="dvi")
        m.submodules.h_active_ff = FFSynchronizer(
            i=self.h_active, o=h_active_dvi, o_domain="dvi")
        m.submodules.v_active_ff = FFSynchronizer(
            i=self.v_active, o=v_active_dvi, o_domain="dvi")
        m.submodules.menu_px_c_ff = FFSynchronizer(
            i=self.menu_pixel.color, o=menu_px_dvi.color, o_domain="dvi")
        m.submodules.menu_px_i_ff = FFSynchronizer(
            i=self.menu_pixel.intensity, o=menu_px_dvi.intensity, o_domain="dvi")

        # Registered pass-through (one pipeline stage, like GridOverlay).
        m.d.dvi += self.o.eq(self.i)

        log_x = Signal(signed(12))
        log_y = Signal(signed(12))
        menu_lx = Signal(signed(12))
        menu_ly = Signal(signed(12))
        menu_row_base = Signal(signed(17))
        menu_bit_addr = Signal(signed(17))
        menu_hit = Signal()
        menu_bit = Signal()
        menu_bit_idx = Signal(5)
        menu_hit_r = Signal()
        menu_en_r = Signal()
        menu_transparent_r = Signal()
        black_px = Signal(Pixel)
        overlay_pixel = Signal(Pixel)

        m.d.comb += [
            black_px.color.eq(0),
            black_px.intensity.eq(0),
            self.menu_raddr.eq(0),
        ]

        with m.If(menu_en_dvi):
            self._logical_xy(
                m, self.i.x, self.i.y, rotation_dvi, h_active_dvi, v_active_dvi,
                log_x, log_y)

            m.d.comb += [
                menu_lx.eq(log_x - menu_ox_dvi),
                menu_ly.eq(log_y - menu_oy_dvi),
                menu_row_base.eq(menu_ly * Const(MENU_W)),
                menu_bit_addr.eq(menu_row_base + menu_lx),
                menu_hit.eq(
                    (menu_lx >= 0) & (menu_lx < MENU_W) &
                    (menu_ly >= 0) & (menu_ly < MENU_H)),
                self.menu_raddr.eq(menu_bit_addr >> 5),
            ]

            # BRAM read is registered; align bit index and hit with ``self.o``.
            m.d.dvi += [
                menu_bit_idx.eq(menu_bit_addr[0:5]),
                menu_hit_r.eq(menu_hit),
                menu_en_r.eq(1),
                menu_transparent_r.eq(menu_transparent_dvi),
            ]
        with m.Else():
            m.d.dvi += [
                menu_bit_idx.eq(0),
                menu_hit_r.eq(0),
                menu_en_r.eq(0),
                menu_transparent_r.eq(0),
            ]

        m.d.comb += menu_bit.eq(self.menu_rdata.bit_select(menu_bit_idx, 1))

        with m.If(self.o.de & menu_en_r & menu_hit_r):
            with m.If(menu_transparent_r):
                with m.If(menu_bit != 0):
                    m.d.dvi += self.o.pixel.eq(menu_px_dvi)
            with m.Else():
                with m.If(menu_bit != 0):
                    m.d.comb += overlay_pixel.eq(menu_px_dvi)
                with m.Else():
                    m.d.comb += overlay_pixel.eq(black_px)
                m.d.dvi += self.o.pixel.eq(overlay_pixel)

        return m


# Backwards-compatible alias for overlay pipeline wiring.
UiLayersOverlay = UiMenuOverlay


class UiMemory(wiring.Component):
    """1bpp menu bitmap in BRAM, CPU-writable via Wishbone."""

    def __init__(self):
        self._menu_mem = Memory(shape=unsigned(32), depth=MENU_WORDS, init=[])

        wb_addr_width = ceil_log2(UI_MEM_BYTES) - exact_log2(4)
        mem_map = MemoryMap(
            addr_width=wb_addr_width + exact_log2(4),
            data_width=8,
        )
        mem_map.add_resource(name=("ui_memory",), size=UI_MEM_BYTES, resource=self)

        super().__init__({
            "bus": In(wishbone.Signature(
                addr_width=wb_addr_width,
                data_width=32,
                granularity=8,
            )),
            "host_waddr": In(ceil_log2(UI_MEM_WORDS)),
            "host_wdata": In(32),
            "host_wen": In(1),
            "menu_rdata": Out(32),
            "menu_raddr": In(ceil_log2(MENU_WORDS)),
        })
        self.bus.memory_map = mem_map

    def elaborate(self, platform):
        m = Module()

        m.submodules.menu_mem = self._menu_mem

        menu_r = self._menu_mem.read_port(domain="dvi")
        menu_w = self._menu_mem.write_port(domain="sync")

        m.d.comb += [
            menu_r.addr.eq(self.menu_raddr),
            self.menu_rdata.eq(menu_r.data),
        ]

        bus = self.bus
        write_en = bus.cyc & bus.stb & bus.we
        word_adr = bus.adr[2:]

        menu_waddr = Signal(ceil_log2(MENU_WORDS))
        m.d.comb += [
            menu_waddr.eq(Mux(write_en, word_adr, self.host_waddr)),
            menu_w.addr.eq(menu_waddr),
            menu_w.data.eq(Mux(write_en, bus.dat_w, self.host_wdata)),
            menu_w.en.eq(write_en | self.host_wen),
            bus.ack.eq(bus.cyc & bus.stb),
            bus.dat_r.eq(0),
        ]

        return m
