# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""CPU-controlled, framebuffer-independent tuner scanline renderer.

Firmware writes a small character plane and the current pitch-marker position.
The renderer regenerates the complete image on every DVI scan; no pixel history,
framebuffer clearing, or raster-engine completion is involved.
"""

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.memory import Memory
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr
from math import cos, isqrt, pi, sin

from tiliqua.video.types import Pixel, ScanPixel

try:
    from .font_9x15 import MENU_FONT_BOLD, MENU_FONT_NORMAL
except ImportError:
    from font_9x15 import MENU_FONT_BOLD, MENU_FONT_NORMAL


# A deliberately small 5x7 font. Unsupported characters render as spaces.
# Rows are encoded most-significant pixel first.
FONT = {
    " ": [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
    "#": [0x0a, 0x1f, 0x0a, 0x0a, 0x1f, 0x0a, 0x00],
    "+": [0x00, 0x04, 0x04, 0x1f, 0x04, 0x04, 0x00],
    "-": [0x00, 0x00, 0x00, 0x1f, 0x00, 0x00, 0x00],
    ".": [0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x06],
    "/": [0x01, 0x02, 0x04, 0x08, 0x10, 0x00, 0x00],
    ":": [0x00, 0x06, 0x06, 0x00, 0x06, 0x06, 0x00],
    "<": [0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02],
    "^": [0x04, 0x0a, 0x11, 0x00, 0x00, 0x00, 0x00],
    "0": [0x0e, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0e],
    "1": [0x04, 0x0c, 0x14, 0x04, 0x04, 0x04, 0x1f],
    "2": [0x0e, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1f],
    "3": [0x1e, 0x01, 0x01, 0x0e, 0x01, 0x01, 0x1e],
    "4": [0x02, 0x06, 0x0a, 0x12, 0x1f, 0x02, 0x02],
    "5": [0x1f, 0x10, 0x10, 0x1e, 0x01, 0x01, 0x1e],
    "6": [0x0e, 0x10, 0x10, 0x1e, 0x11, 0x11, 0x0e],
    "7": [0x1f, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
    "8": [0x0e, 0x11, 0x11, 0x0e, 0x11, 0x11, 0x0e],
    "9": [0x0e, 0x11, 0x11, 0x0f, 0x01, 0x01, 0x0e],
    "A": [0x0e, 0x11, 0x11, 0x1f, 0x11, 0x11, 0x11],
    "B": [0x1e, 0x11, 0x11, 0x1e, 0x11, 0x11, 0x1e],
    "C": [0x0e, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0e],
    "D": [0x1e, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1e],
    "E": [0x1f, 0x10, 0x10, 0x1e, 0x10, 0x10, 0x1f],
    "F": [0x1f, 0x10, 0x10, 0x1e, 0x10, 0x10, 0x10],
    "G": [0x0e, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0f],
    "H": [0x11, 0x11, 0x11, 0x1f, 0x11, 0x11, 0x11],
    "I": [0x0e, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0e],
    "J": [0x07, 0x02, 0x02, 0x02, 0x12, 0x12, 0x0c],
    "K": [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11],
    "L": [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1f],
    "M": [0x11, 0x1b, 0x15, 0x15, 0x11, 0x11, 0x11],
    "N": [0x11, 0x19, 0x19, 0x15, 0x13, 0x13, 0x11],
    "O": [0x0e, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0e],
    "P": [0x1e, 0x11, 0x11, 0x1e, 0x10, 0x10, 0x10],
    "Q": [0x0e, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0d],
    "R": [0x1e, 0x11, 0x11, 0x1e, 0x14, 0x12, 0x11],
    "S": [0x0f, 0x10, 0x10, 0x0e, 0x01, 0x01, 0x1e],
    "T": [0x1f, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
    "U": [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0e],
    "V": [0x11, 0x11, 0x11, 0x11, 0x11, 0x0a, 0x04],
    "W": [0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0a],
    "X": [0x11, 0x11, 0x0a, 0x04, 0x0a, 0x11, 0x11],
    "Y": [0x11, 0x11, 0x0a, 0x04, 0x04, 0x04, 0x04],
    "Z": [0x1f, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1f],
}

FONT_CHARS = " #+-./:0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<^"
FONT_INDEX = {char: index for index, char in enumerate(FONT_CHARS)}
FONT_INIT = [row for char in FONT_CHARS for row in (*FONT[char], 0)]


class TunerOverlay(wiring.Component):
    PANEL_W = 720
    PANEL_H = 720
    COLS = 45
    ROWS = 45
    CELL = 16

    # Exact OSCIO/SONORO overlay geometry on the logical 720x720 canvas.
    MENU_X = 454
    MENU_Y = 342
    MENU_W = 250
    MENU_H = 160
    MENU_TEXT_X = 455
    MENU_TEXT_Y = 349
    MENU_COLS = 28
    MENU_ROWS = 9
    MENU_ROW_PITCH = 18

    def __init__(self, tile_memory, menu_memory):
        self.tile_memory = tile_memory
        self.menu_memory = menu_memory
        super().__init__({
            "i": In(ScanPixel),
            "o": Out(ScanPixel),
            "marker_x": In(12),
            "marker_y": In(12),
            "marker_hue": In(4),
            "marker_lens_base": In(14),
            "marker_lens_bank": In(2),
            "marker_valid": In(1),
            "marker_visualizer": In(1),
            "menu_active": In(1),
            "x_offset": In(12),
            "rotate_left": In(1),
        })

    def elaborate(self, platform):
        m = Module()

        # Synchronize the compact CPU-owned state. It is sampled into a stable
        # frame snapshot only during vertical sync, preventing mid-frame motion.
        marker_x_cdc = Signal(12)
        marker_y_cdc = Signal(12)
        marker_hue_cdc = Signal(4)
        marker_lens_base_cdc = Signal(14)
        marker_lens_bank_cdc = Signal(2)
        marker_valid_cdc = Signal()
        marker_visualizer_cdc = Signal()
        menu_active_cdc = Signal()
        x_offset_cdc = Signal(12)
        rotate_left_cdc = Signal()
        for name, source, target in (
            ("marker_x", self.marker_x, marker_x_cdc),
            ("marker_y", self.marker_y, marker_y_cdc),
            ("marker_hue", self.marker_hue, marker_hue_cdc),
            ("marker_lens_base", self.marker_lens_base, marker_lens_base_cdc),
            ("marker_lens_bank", self.marker_lens_bank, marker_lens_bank_cdc),
            ("marker_valid", self.marker_valid, marker_valid_cdc),
            ("marker_visualizer", self.marker_visualizer, marker_visualizer_cdc),
            ("menu_active", self.menu_active, menu_active_cdc),
            ("x_offset", self.x_offset, x_offset_cdc),
            ("rotate_left", self.rotate_left, rotate_left_cdc),
        ):
            m.submodules[name + "_ff"] = FFSynchronizer(
                source, target, o_domain="dvi")

        marker_x = Signal(12)
        marker_y = Signal(12)
        marker_hue = Signal(4)
        marker_lens_base = Signal(14)
        marker_lens_bank = Signal(2)
        marker_valid = Signal()
        marker_visualizer = Signal()
        menu_active = Signal()
        x_offset = Signal(12)
        rotate_left = Signal()
        with m.If(self.i.vsync):
            m.d.dvi += [
                marker_x.eq(marker_x_cdc),
                marker_y.eq(marker_y_cdc),
                marker_hue.eq(marker_hue_cdc),
                marker_lens_base.eq(marker_lens_base_cdc),
                marker_lens_bank.eq(marker_lens_bank_cdc),
                marker_valid.eq(marker_valid_cdc),
                marker_visualizer.eq(marker_visualizer_cdc),
                menu_active.eq(menu_active_cdc),
                x_offset.eq(x_offset_cdc),
                rotate_left.eq(rotate_left_cdc),
            ]

        # Character plane: one byte per 16x16 cell. A synchronous tile lookup
        # followed by a synchronous glyph-row lookup forms a short fixed pixel
        # pipeline; timing/control and procedural geometry follow the same path.
        tile_r = self.tile_memory.read_port(domain="dvi")
        font_mem = Memory(shape=unsigned(5), depth=len(FONT_INIT), init=FONT_INIT)
        font_r = font_mem.read_port(domain="dvi")
        m.submodules.font_mem = font_mem

        # Menus in XBEAM, OSCIO, and SONORO use embedded-graphics' exact 9x15
        # normal/bold fonts. Keep a dedicated compact plane so the tuner can
        # retain its larger display lettering without approximating the menu.
        menu_r = self.menu_memory.read_port(domain="dvi")
        # Lay glyph rows out on power-of-two address boundaries so the live
        # address is only Cat(row, glyph, bold), not glyph*15 plus a bank add.
        menu_font_init = [0] * 4096
        for bold, font in enumerate((MENU_FONT_NORMAL, MENU_FONT_BOLD)):
            for glyph in range(95):
                for row in range(15):
                    menu_font_init[row | (glyph << 4) | (bold << 11)] = \
                        font[glyph * 15 + row]
        menu_font_mem = Memory(
            shape=unsigned(9), depth=len(menu_font_init), init=menu_font_init,
            attrs={"ram_style": "block"})
        menu_font_r = menu_font_mem.read_port(domain="dvi")
        m.submodules.menu_font_mem = menu_font_mem

        # The Snail-style analytical marker is a compact filled lens, not a
        # widened copy of a scanline interval. Thirty-two unoriented axes cover
        # 180 degrees at 5.625-degree resolution (an ellipse at angle + 180
        # degrees is identical), giving an isotropic, rounded silhouette while
        # keeping the live pixel path free of multipliers. Its major axis is
        # tangent to the local spiral and its 15-pixel thickness stays well
        # inside the 22-pixel octave spacing.
        lens_half = 16
        lens_size = lens_half * 2 + 1
        orientations_per_bank = 11
        lens_bank_init = [[], [], []]
        for orientation in range(32):
            angle = orientation * pi / 32
            tangent_x = cos(angle)
            tangent_y = sin(angle)
            for lens_y in range(-lens_half, lens_half + 1):
                for lens_x in range(-lens_half, lens_half + 1):
                    tangent = lens_x * tangent_x + lens_y * tangent_y
                    normal = -lens_x * tangent_y + lens_y * tangent_x
                    lens_bank_init[orientation // orientations_per_bank].append(int(
                        (tangent * tangent * 49 + normal * normal * 256)
                        <= (16 * 16 * 49)))
        # Keep the three blocks explicit. Inferring one 35Kx1 memory causes
        # nextpnr to cascade EBRs with a combinational bank selector whose
        # address is one pixel newer than their synchronous data, fragmenting
        # the marker during a real raster scan.
        lens_ports = []
        for bank, init in enumerate(lens_bank_init):
            lens_mem = Memory(
                shape=unsigned(1), depth=len(init), init=init,
                attrs={"ram_style": "block"})
            lens_ports.append(lens_mem.read_port(domain="dvi"))
            m.submodules[f"lens_mem_{bank}"] = lens_mem

        # One upright 720x720 UI canvas serves both targets. Standard HDMI
        # centers it horizontally; the official circular panel uses REZO's
        # inverse mount rotation so the authored UI remains upright.
        sx0 = self.i.x
        sy0 = self.i.y
        x0 = Signal(signed(12))
        y0 = Signal(signed(12))
        with m.If(rotate_left):
            m.d.comb += [x0.eq(sy0), y0.eq((self.PANEL_H - 1) - sx0)]
        with m.Else():
            m.d.comb += [x0.eq(sx0 - x_offset), y0.eq(sy0)]
        active0 = self.i.de & (x0 >= 0) & (x0 < self.PANEL_W) & \
            (y0 >= 0) & (y0 < self.PANEL_H)
        cell_x0 = Signal(6)
        cell_y0 = Signal(6)
        m.d.comb += [
            cell_x0.eq(x0.as_unsigned()[4:10]),
            cell_y0.eq(y0.as_unsigned()[4:10]),
            tile_r.addr.eq(
                (cell_y0 << 5) + (cell_y0 << 3) +
                (cell_y0 << 2) + cell_y0 + cell_x0),
            tile_r.en.eq(active0 & (cell_x0 < self.COLS) & (cell_y0 < self.ROWS)),
        ]

        # Predecode the non-power-of-two 9x15 font grid into two tiny ROMs.
        # This reproduces embedded-graphics placement without putting division
        # or modulo operators on the DVI pixel path.
        menu_xmap = []
        menu_ymap = []
        for pixel_x in range(self.PANEL_W):
            relative = pixel_x - self.MENU_TEXT_X
            valid = 0 <= relative < self.MENU_COLS * 9
            column = relative // 9 if valid else 0
            glyph_column = relative % 9 if valid else 0
            menu_xmap.append(column | (glyph_column << 5) | (int(valid) << 9))
        for pixel_y in range(self.PANEL_H):
            relative = pixel_y - self.MENU_TEXT_Y
            row = relative // self.MENU_ROW_PITCH if relative >= 0 else 0
            glyph_row = relative % self.MENU_ROW_PITCH if relative >= 0 else 0
            valid = (0 <= row < self.MENU_ROWS) and glyph_row < 15
            menu_ymap.append(
                (row * self.MENU_COLS) | (glyph_row << 8) | (int(valid) << 12))
        menu_xmap_mem = Memory(
            shape=unsigned(10), depth=self.PANEL_W, init=menu_xmap,
            attrs={"ram_style": "block"})
        menu_ymap_mem = Memory(
            shape=unsigned(13), depth=self.PANEL_H, init=menu_ymap,
            attrs={"ram_style": "block"})
        menu_xmap_r = menu_xmap_mem.read_port(domain="dvi")
        menu_ymap_r = menu_ymap_mem.read_port(domain="dvi")
        m.submodules.menu_xmap_mem = menu_xmap_mem
        m.submodules.menu_ymap_mem = menu_ymap_mem
        m.d.comb += [
            menu_xmap_r.addr.eq(x0.as_unsigned()[:10]),
            menu_xmap_r.en.eq(active0),
            menu_ymap_r.addr.eq(y0.as_unsigned()[:10]),
            menu_ymap_r.en.eq(active0),
        ]

        # Static viewport, chromatic divisions, and spiral now live in the
        # PSRAM framebuffer. This overlay only composites live state, text, and
        # the modal menu; no duplicate guide geometry is stored in FPGA EBR.
        spiral_ports = []
        spoke_ports = []
        dx2_0 = Signal(11)
        m.d.comb += dx2_0.eq(0)

        scan1 = Signal(ScanPixel)
        scan2 = Signal(ScanPixel)
        scan3 = Signal(ScanPixel)
        scan4 = Signal(ScanPixel)
        glyph_col1 = Signal(3)
        glyph_row1 = Signal(3)
        active1 = Signal()
        dx2_1 = Signal.like(dx2_0)
        x_rel1 = Signal(9)
        x_rel_valid1 = Signal()
        menu_inside1 = Signal()
        menu_border1 = Signal()
        menu_rule1 = Signal()

        # Use the established right-side 250x160 menu placement verbatim.
        menu_inside0 = active0 & (x0 >= self.MENU_X) & \
            (x0 < self.MENU_X + self.MENU_W) & (y0 >= self.MENU_Y) & \
            (y0 < self.MENU_Y + self.MENU_H)
        menu_border0 = menu_inside0 & (
            (x0 < self.MENU_X + 2) | (x0 >= self.MENU_X + self.MENU_W - 2) |
            (y0 < self.MENU_Y + 2) | (y0 >= self.MENU_Y + self.MENU_H - 2))
        # Match OSCIO/SONORO's page gutter: page name on the left, option
        # names and values on the right, separated by one quiet vertical rule.
        menu_rule0 = menu_inside0 & (x0 >= self.MENU_X + 79) & \
            (x0 < self.MENU_X + 80) & (y0 >= self.MENU_Y + 8) & \
            (y0 < self.MENU_Y + 62)

        # Cheap polar approximation. It is deliberately generated every scan,
        # so guide pixels never need to be stored, erased, or repaired. The
        # coordinate normalization is registered before radial classification.
        dx0 = Signal(signed(13))
        dy0 = Signal(signed(13))
        ax0 = Signal(13)
        ay0 = Signal(13)
        mdx0 = Signal(signed(13))
        mdy0 = Signal(signed(13))
        m.d.comb += [
            dx0.eq(x0 - 360),
            dy0.eq(y0 - 360),
            ax0.eq(Mux(dx0 < 0, -dx0, dx0)),
            ay0.eq(Mux(dy0 < 0, -dy0, dy0)),
            mdx0.eq(x0 - marker_x),
            mdy0.eq(y0 - marker_y),
        ]
        lens_valid0 = Signal()
        m.d.comb += [
            lens_valid0.eq(
                active0 & marker_valid & ~marker_visualizer &
                (mdx0 >= -lens_half) & (mdx0 <= lens_half) &
                (mdy0 >= -lens_half) & (mdy0 <= lens_half)),
        ]
        ax1 = Signal.like(ax0)
        ay1 = Signal.like(ay0)
        amdx1 = Signal(13)
        amdy1 = Signal(13)
        lens_valid1 = Signal()
        lens_x1 = Signal(6)
        lens_y1 = Signal(6)
        lens_base1 = Signal(14)
        lens_bank1 = Signal(2)
        m.d.dvi += [
            scan1.eq(self.i),
            glyph_col1.eq(x0.as_unsigned()[1:4]),
            glyph_row1.eq(y0.as_unsigned()[1:4]),
            active1.eq(active0),
            dx2_1.eq(dx2_0),
            x_rel1.eq(x0 - 128),
            x_rel_valid1.eq((x0 >= 128) & (x0 < 640)),
            menu_inside1.eq(menu_inside0),
            menu_border1.eq(menu_border0),
            menu_rule1.eq(menu_rule0),
            ax1.eq(ax0), ay1.eq(ay0),
            amdx1.eq(Mux(mdx0 < 0, -mdx0, mdx0)),
            amdy1.eq(Mux(mdy0 < 0, -mdy0, mdy0)),
            lens_valid1.eq(lens_valid0),
            lens_x1.eq(mdx0 + lens_half),
            lens_y1.eq(mdy0 + lens_half),
            lens_base1.eq(marker_lens_base),
            lens_bank1.eq(marker_lens_bank),
        ]

        menu_valid1 = Signal()
        menu_glyph_col1 = Signal(4)
        menu_glyph_row1 = Signal(4)
        menu_cell_addr1 = Signal(range(self.MENU_COLS * self.MENU_ROWS))
        m.d.comb += [
            menu_valid1.eq(menu_xmap_r.data[9] & menu_ymap_r.data[12]),
            menu_glyph_col1.eq(menu_xmap_r.data[5:9]),
            menu_glyph_row1.eq(menu_ymap_r.data[8:12]),
            menu_cell_addr1.eq(menu_ymap_r.data[:8] + menu_xmap_r.data[:5]),
            menu_r.addr.eq(menu_cell_addr1),
            menu_r.en.eq(menu_active & menu_valid1),
        ]

        # Split coordinate normalization from the ROM address addition. The
        # extra register keeps the large lens memory physically off the path
        # from the live DVI pixel counters.
        lens_addr1 = Signal(14)
        m.d.comb += lens_addr1.eq(
            lens_base1 + (lens_y1 << 5) + lens_y1 + lens_x1)

        circle_inside1 = active1
        circle_edge1 = Const(0)
        marker_min1 = Signal(13)
        marker_max1 = Signal(13)
        marker_distance1 = Signal(14)
        m.d.comb += [
            marker_min1.eq(Mux(amdx1 < amdy1, amdx1, amdy1)),
            marker_max1.eq(Mux(amdx1 > amdy1, amdx1, amdy1)),
            # max + min/2 is a rounded, multiplier-free Euclidean distance.
            marker_distance1.eq(marker_max1 + (marker_min1 >> 1)),
        ]

        exact_spoke_hits = []
        for spoke_port in spoke_ports:
            lower = spoke_port.data[:9]
            upper = spoke_port.data[9:18]
            exact_spoke_hits.append((ax1 >= lower) & (ax1 <= upper))

        # Stored character bytes are direct FONT_CHARS indices, keeping the
        # pixel path free of an ASCII decoder.
        font_addr = Signal(range(len(FONT_INIT)))
        m.d.comb += [
            font_addr.eq((tile_r.data << 3) + glyph_row1),
            font_r.addr.eq(font_addr),
        ]
        glyph_col2 = Signal.like(glyph_col1)
        circle_inside2 = Signal()
        circle_edge2 = Signal()
        marker2 = Signal()
        marker_halo2 = Signal(2)
        marker_distance2 = Signal.like(marker_distance1)
        lens_addr2 = Signal.like(lens_addr1)
        lens_valid2 = Signal()
        lens_bank2 = Signal(2)
        spiral_bounds2 = [Signal(18, name=f"spiral_bounds2_{index}")
                          for index in range(len(spiral_ports))]
        x_rel2 = Signal.like(x_rel1)
        x_rel_valid2 = Signal()
        spoke_hits2 = Signal(1)
        menu_inside2 = Signal()
        menu_border2 = Signal()
        menu_rule2 = Signal()
        menu_valid2 = Signal()
        menu_glyph_col2 = Signal(4)
        menu_glyph_row2 = Signal(4)
        m.d.dvi += [
            scan2.eq(scan1),
            glyph_col2.eq(glyph_col1),
            circle_inside2.eq(circle_inside1),
            circle_edge2.eq(circle_edge1),
            marker2.eq(marker_valid & marker_visualizer &
                       (marker_distance1 <= 5)),
            marker_distance2.eq(marker_distance1),
            lens_addr2.eq(lens_addr1),
            lens_valid2.eq(lens_valid1),
            lens_bank2.eq(lens_bank1),
            x_rel2.eq(x_rel1),
            x_rel_valid2.eq(x_rel_valid1),
            marker_halo2.eq(Mux(
                marker_valid & marker_visualizer &
                (marker_distance1 <= 12), 2,
                Mux(marker_valid & marker_visualizer &
                    (marker_distance1 <= 22), 1, 0))),
            spoke_hits2.eq(0),
            menu_inside2.eq(menu_inside1),
            menu_border2.eq(menu_border1),
            menu_rule2.eq(menu_rule1),
            menu_valid2.eq(menu_valid1),
            menu_glyph_col2.eq(menu_glyph_col1),
            menu_glyph_row2.eq(menu_glyph_row1),
        ]
        for bounds, spiral_port in zip(spiral_bounds2, spiral_ports):
            m.d.dvi += bounds.eq(spiral_port.data)
        for lens_port in lens_ports:
            m.d.comb += [
                lens_port.addr.eq(lens_addr2),
                lens_port.en.eq(lens_valid2),
            ]

        text_hit2 = Signal()
        glyph_bit = Signal(3)
        m.d.comb += [
            glyph_bit.eq(Mux(glyph_col2 < 5, 4 - glyph_col2, 0)),
            text_hit2.eq(
                circle_inside2 & (glyph_col2 < 5) &
                font_r.data.bit_select(glyph_bit, 1)),
        ]


        menu_font_addr2 = Signal(12)
        m.d.comb += [
            menu_font_addr2.eq(Cat(
                menu_glyph_row2, menu_r.data[:7], menu_r.data[7])),
            menu_font_r.addr.eq(menu_font_addr2),
            menu_font_r.en.eq(menu_active & menu_valid2),
        ]

        # Keep normalization, radial classification, and final color selection
        # in separate pixel-clock stages. This is deliberately a few pixels of
        # latency: the scan stream is delayed alongside it, and the shorter
        # paths leave comfortable margin at the 74.25 MHz preview clock.
        circle_edge3 = Signal()
        marker3 = Signal()
        marker_halo3 = Signal(2)
        lens_valid3 = Signal()
        lens_bank3 = Signal(2)
        text_hit3 = Signal()
        spiral3 = Signal()
        arc3 = Signal()
        spoke3 = Signal()
        menu_inside3 = Signal()
        menu_border3 = Signal()
        menu_rule3 = Signal()
        menu_valid3 = Signal()
        menu_glyph_col3 = Signal(4)
        menu_bold3 = Signal()
        m.d.dvi += [
            scan3.eq(scan2),
            circle_edge3.eq(circle_edge2),
            marker3.eq(marker2),
            marker_halo3.eq(marker_halo2),
            lens_valid3.eq(lens_valid2),
            lens_bank3.eq(lens_bank2),
            text_hit3.eq(text_hit2),
            spiral3.eq(0),
            arc3.eq(0),
            spoke3.eq(0),
            menu_inside3.eq(menu_inside2),
            menu_border3.eq(menu_border2),
            menu_rule3.eq(menu_rule2),
            menu_valid3.eq(menu_valid2),
            menu_glyph_col3.eq(menu_glyph_col2),
            menu_bold3.eq(menu_r.data[7]),
        ]

        menu_text_hit3 = Signal()
        menu_font_bit3 = Signal(4)
        m.d.comb += [
            menu_font_bit3.eq(8 - menu_glyph_col3),
            menu_text_hit3.eq(
                menu_active & menu_valid3 &
                menu_font_r.data.bit_select(menu_font_bit3, 1)),
        ]

        guide3 = Signal()
        m.d.comb += [
            guide3.eq(spiral3),
        ]

        # 0 black, 1 pitch spiral, 2 marker core, 3 viewport edge,
        # 4 radial guide, 5 analytical arc, 6/7 visualizer halo.
        geometry4 = Signal(3)
        text_hit4 = Signal()
        menu_inside4 = Signal()
        menu_border4 = Signal()
        menu_rule4 = Signal()
        menu_text_hit4 = Signal()
        menu_bold4 = Signal()
        analytical_lens3 = Signal()
        selected_lens_data3 = Signal()
        m.d.comb += selected_lens_data3.eq(
            Array(port.data for port in lens_ports)[lens_bank3])
        m.d.comb += analytical_lens3.eq(
            marker_valid & ~marker_visualizer & lens_valid3 &
            (lens_bank3 < len(lens_ports)) & selected_lens_data3)
        m.d.dvi += [
            scan4.eq(scan3),
            geometry4.eq(Mux(marker3 | analytical_lens3, 2,
                         Mux(arc3, 5,
                         Mux(marker_halo3 == 2, 6,
                         Mux(marker_halo3 == 1, 7,
                         Mux(guide3, 1,
                         Mux(spoke3, 4, Mux(circle_edge3, 3, 0)))))))),
            text_hit4.eq(text_hit3),
            menu_inside4.eq(menu_inside3),
            menu_border4.eq(menu_border3),
            menu_rule4.eq(menu_rule3),
            menu_text_hit4.eq(menu_text_hit3),
            menu_bold4.eq(menu_bold3),
        ]

        pixel = Signal(Pixel)
        m.d.comb += pixel.eq(scan4.pixel)
        with m.If(geometry4 == 1):
            m.d.comb += [pixel.color.eq(9), pixel.intensity.eq(5)]
        with m.If(geometry4 == 2):
            m.d.comb += [pixel.color.eq(marker_hue), pixel.intensity.eq(15)]
        with m.If(geometry4 == 3):
            m.d.comb += [pixel.color.eq(9), pixel.intensity.eq(2)]
        with m.If(geometry4 == 4):
            m.d.comb += [pixel.color.eq(9), pixel.intensity.eq(2)]
        with m.If(geometry4 == 5):
            m.d.comb += [pixel.color.eq(marker_hue), pixel.intensity.eq(15)]
        with m.If(geometry4 == 6):
            m.d.comb += [pixel.color.eq(marker_hue), pixel.intensity.eq(8)]
        with m.If(geometry4 == 7):
            m.d.comb += [pixel.color.eq(marker_hue), pixel.intensity.eq(3)]
        # The menu is an opaque modal panel over the continuously rendered
        # tuner, rather than a separate full-screen page. Its procedural fill
        # guarantees that old pixels cannot show through between text updates.
        with m.If(menu_active & menu_inside4):
            m.d.comb += pixel.eq(0)
            with m.If(menu_border4):
                m.d.comb += [pixel.color.eq(9), pixel.intensity.eq(10)]
            with m.Elif(menu_rule4):
                m.d.comb += [pixel.color.eq(9), pixel.intensity.eq(3)]
        with m.If(text_hit4 & ~(menu_active & menu_inside4)):
            m.d.comb += [pixel.color.eq(9), pixel.intensity.eq(13)]
        with m.If(menu_text_hit4):
            m.d.comb += [
                pixel.color.eq(9),
                pixel.intensity.eq(Mux(menu_bold4, 15, 10)),
            ]

        m.d.comb += [
            self.o.eq(scan4),
            self.o.pixel.eq(Mux(scan4.de, pixel, 0)),
        ]
        return m


class Peripheral(wiring.Component):
    """CSR state and tile writer for :class:`TunerOverlay`."""

    class Marker(csr.Register, access="w"):
        x: csr.Field(csr.action.W, unsigned(12))
        y: csr.Field(csr.action.W, unsigned(12))
        hue: csr.Field(csr.action.W, unsigned(4))
        valid: csr.Field(csr.action.W, unsigned(1))
        visualizer: csr.Field(csr.action.W, unsigned(1))
        menu_active: csr.Field(csr.action.W, unsigned(1))

    class TileWrite(csr.Register, access="w"):
        address: csr.Field(csr.action.W, unsigned(12))
        glyph: csr.Field(csr.action.W, unsigned(6))

    class MarkerShape(csr.Register, access="w"):
        # Firmware selects one explicit EBR and supplies its local sprite base,
        # keeping both the multiply and deep-memory bank cascade out of DVI.
        base: csr.Field(csr.action.W, unsigned(14))
        bank: csr.Field(csr.action.W, unsigned(2))

    class Layout(csr.Register, access="w"):
        x_offset: csr.Field(csr.action.W, unsigned(12))
        rotate_left: csr.Field(csr.action.W, unsigned(1))

    def __init__(self):
        self.tile_memory = Memory(
            shape=unsigned(6), depth=TunerOverlay.COLS * TunerOverlay.ROWS,
            init=[0] * (TunerOverlay.COLS * TunerOverlay.ROWS))
        # Bits 0..6 select printable ASCII; bit 7 selects the bold face used
        # by draw_options for the active page or option.
        self.menu_memory = Memory(
            shape=unsigned(8), depth=TunerOverlay.MENU_COLS * TunerOverlay.MENU_ROWS,
            init=[0] * (TunerOverlay.MENU_COLS * TunerOverlay.MENU_ROWS))
        self.overlay = TunerOverlay(self.tile_memory, self.menu_memory)

        regs = csr.Builder(addr_width=4, data_width=8)
        self._marker = regs.add("marker", self.Marker(), offset=0x0)
        self._tile_write = regs.add("tile_write", self.TileWrite(), offset=0x4)
        self._layout = regs.add("layout", self.Layout(), offset=0x8)
        self._marker_shape = regs.add(
            "marker_shape", self.MarkerShape(), offset=0xc)
        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__({
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        m.submodules.overlay = self.overlay
        m.submodules.tile_memory = self.tile_memory
        m.submodules.menu_memory = self.menu_memory
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        tile_w = self.tile_memory.write_port(domain="sync")
        menu_w = self.menu_memory.write_port(domain="sync")
        m.d.comb += [
            tile_w.addr.eq(self._tile_write.f.address.w_data),
            tile_w.data.eq(self._tile_write.f.glyph.w_data),
            tile_w.en.eq(
                self._tile_write.element.w_stb &
                ~self._tile_write.f.address.w_data[11]),
            menu_w.addr.eq(self._tile_write.f.address.w_data[:8]),
            menu_w.data.eq(Cat(
                self._tile_write.f.glyph.w_data,
                self._tile_write.f.address.w_data[9],
                self._tile_write.f.address.w_data[10])),
            menu_w.en.eq(
                self._tile_write.element.w_stb &
                self._tile_write.f.address.w_data[11]),
        ]
        with m.If(self._marker.element.w_stb):
            m.d.sync += [
                self.overlay.marker_x.eq(self._marker.f.x.w_data),
                self.overlay.marker_y.eq(self._marker.f.y.w_data),
                self.overlay.marker_hue.eq(self._marker.f.hue.w_data),
                self.overlay.marker_valid.eq(self._marker.f.valid.w_data),
                self.overlay.marker_visualizer.eq(self._marker.f.visualizer.w_data),
                self.overlay.menu_active.eq(self._marker.f.menu_active.w_data),
            ]
        with m.If(self._layout.element.w_stb):
            m.d.sync += [
                self.overlay.x_offset.eq(self._layout.f.x_offset.w_data),
                self.overlay.rotate_left.eq(self._layout.f.rotate_left.w_data),
            ]
        with m.If(self._marker_shape.element.w_stb):
            m.d.sync += [
                self.overlay.marker_lens_base.eq(
                    self._marker_shape.f.base.w_data),
                self.overlay.marker_lens_bank.eq(
                    self._marker_shape.f.bank.w_data),
            ]
        return m
