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

FONT_CHARS = " #+-./:0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
FONT_INDEX = {char: index for index, char in enumerate(FONT_CHARS)}
FONT_INIT = [row for char in FONT_CHARS for row in (*FONT[char], 0)]


class TunerOverlay(wiring.Component):
    PANEL_W = 720
    PANEL_H = 720
    COLS = 45
    ROWS = 45
    CELL = 16

    def __init__(self, tile_memory):
        self.tile_memory = tile_memory
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

        # Exact circular viewport mask, shared by the real panel and the
        # centered development preview. Doubled coordinates preserve symmetry
        # about the half-pixel center at 359.5 without fractional arithmetic.
        circle_bounds = []
        for pixel_y in range(self.PANEL_H):
            dy2 = abs((pixel_y << 1) - (self.PANEL_H - 1))
            circle_bounds.append(isqrt((self.PANEL_W * self.PANEL_W) - dy2 * dy2))
        circle_mem = Memory(
            shape=unsigned(10), depth=self.PANEL_H, init=circle_bounds,
            attrs={"ram_style": "block"})
        circle_r = circle_mem.read_port(domain="dvi")
        m.submodules.circle_mem = circle_mem

        # Rasterize the same Archimedean pitch spiral used by firmware for the
        # marker. One revolution is one octave: C0 begins at radius 52 and C8
        # ends at radius 228. Each scanline is stored as narrow X intervals,
        # retaining a genuinely smooth curve without live trigonometry or a
        # framebuffer. Coordinates fit in nine bits after subtracting 128.
        spiral_pixels = [set() for _ in range(self.PANEL_H)]
        samples_per_octave = 12 * 16
        previous = None
        for step in range(8 * samples_per_octave + 1):
            turns = 1 + step / samples_per_octave
            radius = 52 + 22 * (turns - 1)
            angle = turns * 2 * pi - pi / 2
            px = round(360 + radius * cos(angle))
            py = round(360 + radius * sin(angle))
            # Join adjacent pitch samples before thickening the path. Merely
            # stamping the endpoints leaves visible gaps in the outer turns,
            # where one sixteenth of a semitone spans several display pixels.
            if previous is None:
                segment = [(px, py)]
            else:
                dx = px - previous[0]
                dy = py - previous[1]
                length = max(abs(dx), abs(dy))
                segment = [
                    (round(previous[0] + dx * n / length),
                     round(previous[1] + dy * n / length))
                    for n in range(1, length + 1)
                ] if length else [(px, py)]
            for line_x, line_y in segment:
                for oy in range(-1, 2):
                    for ox in range(-1, 2):
                        x = line_x + ox
                        y = line_y + oy
                        if 128 <= x < 640 and 0 <= y < self.PANEL_H:
                            spiral_pixels[y].add(x - 128)
            previous = (px, py)
        spiral_intervals = []
        for pixels in spiral_pixels:
            intervals = []
            for px in sorted(pixels):
                if not intervals or px > intervals[-1][1] + 1:
                    intervals.append([px, px])
                else:
                    intervals[-1][1] = px
            assert len(intervals) <= 19
            spiral_intervals.append(intervals)
        spiral_ports = []
        for slot in range(19):
            bounds = []
            for intervals in spiral_intervals:
                if slot < len(intervals):
                    lower, upper = intervals[slot]
                else:
                    lower, upper = 0x1ff, 0
                bounds.append(lower | (upper << 9))
            spiral_mem = Memory(
                shape=unsigned(18), depth=self.PANEL_H, init=bounds,
                attrs={"ram_style": "block"})
            spiral_ports.append(spiral_mem.read_port(domain="dvi"))
            m.submodules[f"spiral_mem_{slot}"] = spiral_mem

        # Rasterize twelve accurately angled radial guides at elaboration time.
        # Symmetry leaves at most three absolute-X intervals per scanline. This
        # gives exact 30-degree divisions from the center through the outer ring
        # without multipliers in the live pixel path.
        spoke_pixels = [set() for _ in range(self.PANEL_H)]
        for pitch_class in range(12):
            angle = -pi / 2 + pitch_class * (2 * pi / 12)
            for quarter_radius in range(0, 242 * 4 + 1):
                radius = quarter_radius / 4
                px = round(360 + radius * cos(angle))
                py = round(360 + radius * sin(angle))
                for oy in range(-1, 2):
                    for ox in range(-1, 2):
                        if 0 <= py + oy < self.PANEL_H:
                            spoke_pixels[py + oy].add(abs(px + ox - 360))
        spoke_intervals = []
        for pixels in spoke_pixels:
            intervals = []
            for px in sorted(pixels):
                if not intervals or px > intervals[-1][1] + 1:
                    intervals.append([px, px])
                else:
                    intervals[-1][1] = px
            assert len(intervals) <= 3
            spoke_intervals.append(intervals)
        spoke_ports = []
        for slot in range(3):
            bounds = []
            for intervals in spoke_intervals:
                if slot < len(intervals):
                    lower, upper = intervals[slot]
                else:
                    lower, upper = 0x1ff, 0
                bounds.append(lower | (upper << 9))
            spoke_mem = Memory(
                shape=unsigned(18), depth=self.PANEL_H, init=bounds,
                attrs={"ram_style": "block"})
            spoke_ports.append(spoke_mem.read_port(domain="dvi"))
            m.submodules[f"spoke_mem_{slot}"] = spoke_mem
        dx2_0 = Signal(11)
        m.d.comb += [
            circle_r.addr.eq(y0.as_unsigned()[:10]),
            circle_r.en.eq(active0),
            dx2_0.eq(Mux(x0 < 360, 719 - (x0 << 1), (x0 << 1) - 719)),
        ]
        for spiral_port in spiral_ports:
            m.d.comb += [
                spiral_port.addr.eq(y0.as_unsigned()[:10]),
                spiral_port.en.eq(active0),
            ]
        for spoke_port in spoke_ports:
            m.d.comb += [
                spoke_port.addr.eq(y0.as_unsigned()[:10]),
                spoke_port.en.eq(active0),
            ]

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
            ax1.eq(ax0), ay1.eq(ay0),
            amdx1.eq(Mux(mdx0 < 0, -mdx0, mdx0)),
            amdy1.eq(Mux(mdy0 < 0, -mdy0, mdy0)),
            lens_valid1.eq(lens_valid0),
            lens_x1.eq(mdx0 + lens_half),
            lens_y1.eq(mdy0 + lens_half),
            lens_base1.eq(marker_lens_base),
            lens_bank1.eq(marker_lens_bank),
        ]

        # Split coordinate normalization from the ROM address addition. The
        # extra register keeps the large lens memory physically off the path
        # from the live DVI pixel counters.
        lens_addr1 = Signal(14)
        m.d.comb += lens_addr1.eq(
            lens_base1 + (lens_y1 << 5) + lens_y1 + lens_x1)

        circle_inside1 = active1 & (dx2_1 <= circle_r.data)
        circle_edge1 = circle_inside1 & (dx2_1 + 4 >= circle_r.data)
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
        spoke_hits2 = Signal(len(spoke_ports))
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
            spoke_hits2.eq(Cat(*exact_spoke_hits)),
        ]
        for bounds, spiral_port in zip(spiral_bounds2, spiral_ports):
            m.d.dvi += bounds.eq(spiral_port.data)
        for lens_port in lens_ports:
            m.d.comb += [
                lens_port.addr.eq(lens_addr2),
                lens_port.en.eq(lens_valid2),
            ]

        exact_spiral_hits2 = []
        for bounds in spiral_bounds2:
            lower = bounds[:9]
            upper = bounds[9:18]
            interval_valid = lower <= upper
            exact_spiral_hits2.append(
                x_rel_valid2 & interval_valid &
                (x_rel2 >= lower) & (x_rel2 <= upper))

        text_hit2 = Signal()
        glyph_bit = Signal(3)
        m.d.comb += [
            glyph_bit.eq(Mux(glyph_col2 < 5, 4 - glyph_col2, 0)),
            text_hit2.eq(
                circle_inside2 & (glyph_col2 < 5) &
                font_r.data.bit_select(glyph_bit, 1)),
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
        m.d.dvi += [
            scan3.eq(scan2),
            circle_edge3.eq(circle_edge2),
            marker3.eq(marker2),
            marker_halo3.eq(marker_halo2),
            lens_valid3.eq(lens_valid2),
            lens_bank3.eq(lens_bank2),
            text_hit3.eq(text_hit2),
            spiral3.eq(Cat(*exact_spiral_hits2).any()),
            # Preserve the exact guide centerline through the filled lens. The
            # surrounding marker body comes from the oriented lens ROM above.
            arc3.eq(Cat(*exact_spiral_hits2).any() & marker_valid &
                    ~marker_visualizer & (marker_distance2 <= 14)),
            spoke3.eq(spoke_hits2.any()),
        ]

        guide3 = Signal()
        m.d.comb += [
            guide3.eq(spiral3),
        ]

        # 0 black, 1 pitch spiral, 2 marker core, 3 viewport edge,
        # 4 radial guide, 5 analytical arc, 6/7 visualizer halo.
        geometry4 = Signal(3)
        text_hit4 = Signal()
        analytical_lens3 = Signal()
        selected_lens_data3 = Signal()
        m.d.comb += selected_lens_data3.eq(
            Array(port.data for port in lens_ports)[lens_bank3])
        m.d.comb += analytical_lens3.eq(
            marker_valid & ~marker_visualizer & lens_valid3 &
            (lens_bank3 < len(lens_ports)) & selected_lens_data3)
        m.d.dvi += [
            scan4.eq(scan3),
            geometry4.eq(Mux(menu_active, 0,
                         Mux(marker3 | analytical_lens3, 2,
                         Mux(arc3, 5,
                         Mux(marker_halo3 == 2, 6,
                         Mux(marker_halo3 == 1, 7,
                         Mux(guide3, 1,
                         Mux(spoke3, 4, Mux(circle_edge3, 3, 0))))))))),
            text_hit4.eq(text_hit3),
        ]

        pixel = Signal(Pixel)
        m.d.comb += pixel.eq(0)
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
        with m.If(text_hit4):
            m.d.comb += [pixel.color.eq(9), pixel.intensity.eq(13)]

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
        self.overlay = TunerOverlay(self.tile_memory)

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
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        tile_w = self.tile_memory.write_port(domain="sync")
        m.d.comb += [
            tile_w.addr.eq(self._tile_write.f.address.w_data),
            tile_w.data.eq(self._tile_write.f.glyph.w_data),
            tile_w.en.eq(self._tile_write.element.w_stb),
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
