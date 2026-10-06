# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""INTONO display adapter around the shared instrument text compositor.

CPU-authored static pixels arrive from the retained PSRAM framebuffer. Live
markers and text are composited on scanout, without phosphor/persistence engines.
"""

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.memory import Memory
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr
from math import cos, pi, sin

from tiliqua.video.types import Pixel, ScanPixel

try:
    from .font_9x15 import MENU_FONT_BOLD, MENU_FONT_NORMAL
    from .font_7x10 import UX_FONT_BOLD, UX_FONT_NORMAL
    from .renderer import FrameExchange, Panel, TextCompositor, TextPlane
    from .sprites import ScanlineSprites
    from .ui_shapes import RoundedBorders
    from .background import SceneExchange
except ImportError:
    from font_9x15 import MENU_FONT_BOLD, MENU_FONT_NORMAL
    from font_7x10 import UX_FONT_BOLD, UX_FONT_NORMAL
    from renderer import FrameExchange, Panel, TextCompositor, TextPlane
    from sprites import ScanlineSprites
    from ui_shapes import RoundedBorders
    from background import SceneExchange


def arc_pitch_text_coordinates(x, y, enabled):
    """Magnify the primary Arc note 2x using its existing character cells.

    Only text lookup coordinates change: background, markers and scan timing
    retain their original positions. The 30-pixel glyph fits between PITCH
    and cents, and four 24-pixel cells accommodate sharps and octave numbers.
    """
    inside = enabled & (x >= 492) & (x < 588) & (y >= 216) & (y < 246)
    return (Mux(inside, 492 + ((x - 492) >> 1), x),
            Mux(inside, 224 + ((y - 216) >> 1), y))


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


class IntonoOverlay(wiring.Component):
    FRAME_FIELDS = ("marker_x", "marker_y", "marker_hue", "marker_lens_base",
                    "marker_lens_bank", "marker_valid", "marker_visualizer", "menu_active",
                    "marker1", "marker2", "marker3", "blank_background", "keyboard_mask", "keyboard_mask_b", "keyboard_enable", "keyboard_second", "ui_surface", "ui_focus", "ui_ready", "ui_mode", "keyboard_focus")
    LATENCY = 4 + 6  # Maximum; instances without pixel-offset text use nine clocks.
    PANEL_W = 720
    PANEL_H = 720
    COLS = 45
    ROWS = 45
    CELL = 16
    MAIN_TEXT_X = 90
    MAIN_TEXT_PITCH = 12
    UX_TEXT_X = 120
    UX_COLUMNS = 43
    UX_ROWS = 22
    UX_PITCH_X = 12
    UX_PITCH_Y = 32

    # OSCIO/SONORO text placement, with enough left padding for SETTINGS.
    # Grow leftward only: text, divider and the right edge stay in place.
    MENU_X = 448
    MENU_Y = 332
    MENU_W = 256
    MENU_H = 178
    MENU_TEXT_X = 455
    MENU_TEXT_Y = 339
    MENU_COLS = 28
    MENU_ROWS = 9
    MENU_ROW_PITCH = 18

    def __init__(self, tile_memory, menu_memory, *, h_active=720,
                 rotate_left=False, double_buffered=False, ascii_text=False, large_text=False):
        self.tile_memory = tile_memory
        self.menu_memory = menu_memory
        self.x_offset = 0 if rotate_left else max(0, (h_active - self.PANEL_W) // 2)
        self.rotate_left = rotate_left
        self.double_buffered = double_buffered
        self.ascii_text = ascii_text
        self.large_text = large_text
        self.LATENCY = 4 + (6 if large_text else TextCompositor.LATENCY)
        super().__init__({
            "i": In(ScanPixel),
            "o": Out(ScanPixel),
            "background_errors": Out(8),
            "marker_x": In(12),
            "marker_y": In(12),
            "marker_hue": In(4),
            "marker_lens_base": In(14),
            "marker_lens_bank": In(2),
            "marker_valid": In(1),
            "marker_visualizer": In(1),
            "menu_active": In(1),
            "front_bank": In(1),
            "blank_background": In(1),
            "keyboard_mask": In(12), "keyboard_mask_b": In(12), "keyboard_enable": In(1), "keyboard_second": In(1),
            "ui_surface": In(4), "ui_focus": In(5), "ui_ready": In(1, init=1), "ui_mode": In(2, init=1), "keyboard_focus": In(5, init=31),
            # Additional arcs: x10/y10/orientation5/hue4/valid1. Slot zero
            # retains the legacy ABI and its optional visualizer halo.
            "marker1": In(30), "marker2": In(30), "marker3": In(30),
        })

    def elaborate(self, platform):
        m = Module()

        # Production inputs are one acknowledged frame snapshot, already in
        # dvi. The unbuffered mode is retained for standalone raster tests only.
        state = {}
        for name in self.FRAME_FIELDS:
            source = getattr(self, name)
            if self.double_buffered:
                state[name] = source
                continue
            crossed = Signal.like(source)
            state[name] = Signal.like(source)
            m.submodules[name + "_ff"] = FFSynchronizer(source, crossed, o_domain="dvi")
            with m.If(self.i.vsync):
                m.d.dvi += state[name].eq(crossed)

        # Transform once, and delay logical coordinates alongside physical scan
        # timing. Neither the sprite nor text compositor knows a modeline.
        x = Signal(signed(12))
        y = Signal(signed(12))
        if self.rotate_left:
            m.d.comb += [x.eq(self.i.y), y.eq(719 - self.i.x)]
        else:
            m.d.comb += [x.eq(self.i.x - self.x_offset), y.eq(self.i.y)]
        active = self.i.de & (x >= 0) & (x < 720) & (y >= 0) & (y < 720)
        if self.large_text and self.double_buffered:
            # Diagnostic only: retained canvases use cyan guides, white loading
            # dots, cream traces, red/yellow tracking, or E/F keyboard tags.
            # No retained canvas draws outside the logical 720-pixel panel.
            raw = self.i.pixel.as_value()
            known = ((raw == 0) | (self.i.pixel.color == 9) |
                     (raw == 0xFF) | (raw == 0xDB) | (raw == 0xD2) |
                     (raw == 0xD0) | (raw == 0xD1) | (raw == 0xD4) |
                     ((self.i.pixel.intensity >= 14) & (self.i.pixel.color < 12)))
            bad = self.i.de & ((~known) | ((~active) & (raw != 0)))
            # Sticky evidence is enough to distinguish an incoming bad sample
            # from a later output fault; avoid another multi-bit counter/CDC.
            seen, crossed = Signal(), Signal()
            with m.If(bad):
                m.d.dvi += seen.eq(1)
            m.submodules.background_error_ff = FFSynchronizer(seen, crossed, o_domain="sync")
            m.d.comb += self.background_errors[0].eq(crossed)

        text_x, text_y = (arc_pitch_text_coordinates(x, y,
                            state["ui_ready"] & (state["ui_surface"] == 0))
                          if self.large_text else (x, y))
        xs = [text_x] + [Signal.like(x) for _ in range(4)]
        ys = [text_y] + [Signal.like(y) for _ in range(4)]
        for n in range(4):
            m.d.dvi += [xs[n+1].eq(xs[n]), ys[n+1].eq(ys[n])]

        # Cached key interiors use E0..EB for A and F0..FB for B (C..B). Decode
        # membership rather than re-testing twelve rectangles per pixel.
        # The published enable prevents tags affecting any other page.
        if self.large_text:
            note = self.i.pixel.color
            tagged = ((self.i.pixel.intensity == 14) | (self.i.pixel.intensity == 15)) & (note < 12)
            black = (note == 1) | (note == 3) | (note == 6) | (note == 8) | (note == 10)
            mask = Mux(self.i.pixel.intensity == 15, state["keyboard_mask_b"], state["keyboard_mask"])
            selected = mask.bit_select(note,1)
            fill = active & state["keyboard_enable"] & tagged
            # Excluded keys are white/black; included intervals use the theme highlight.
            lefts=Array(Const(n,10) for n in (165,203,221,259,277,333,371,389,427,445,483,501))
            key_top=248+Mux(self.i.pixel.intensity==15,140,0)+Mux(state["keyboard_second"],0,32)
            rx=Signal(signed(12));ry=Signal(signed(12))
            m.d.comb += [rx.eq(x-lefts[note]),ry.eq(y-key_top)]
            cursor=(state["keyboard_focus"]==Cat(note,self.i.pixel.intensity==15))
            # Resolve the key-relative coordinates in the first existing overlay
            # stage, then calculate its ring. Total pixel latency stays four.
            rx1=Signal(signed(12));ry1=Signal(signed(12))
            black1=Signal();cursor1=Signal();selected1=Signal();fill1=Signal();second1=Signal()
            m.d.dvi += [rx1.eq(rx),ry1.eq(ry),black1.eq(black),
                        cursor1.eq(cursor),selected1.eq(selected),fill1.eq(fill),second1.eq(state["keyboard_second"])]
            rx,ry,black,cursor,selected,fill=rx1,ry1,black1,cursor1,selected1,fill1
            # A two-pixel white ring with a dark halo on both sides stays
            # visible on white, black, and highlighted keys without changing membership.
            right=Mux(black,34,54);bottom=Mux(black,Mux(second1,53,77),Mux(second1,99,143))
            edge=(rx<=4)|(rx>=right-4)|(ry<=4)|(ry>=bottom-4)
            # Key radius is four pixels. Insetting the ring by two leaves
            # radius two: scanline insets 4,3,2 match the retained key curve.
            row2=(ry==2)|(ry==bottom-2)
            row3=(ry==3)|(ry==bottom-3)
            inset=Mux(row2,4,Mux(row3,3,2))
            outer=(ry>=2)&(ry<=bottom-2)&(rx>=inset)&(rx<=right-inset)
            inner=(rx>=4)&(rx<=right-4)&(ry>=4)&(ry<=bottom-4)
            yellow=outer & ~inner
            fill_color=Mux(cursor&edge,Mux(yellow,0xF9,0x09),
                           Mux(selected,0xF2,Mux(black,0x09,0xF9)))
        else:
            fill, fill_color = Const(0), Const(0,8)
        fill_stages = 3 if self.large_text else 4
        fills = [fill] + [Signal() for _ in range(fill_stages)]
        fill_colors = [fill_color] + [Signal(8) for _ in range(fill_stages)]
        for n in range(fill_stages):
            m.d.dvi += [fills[n+1].eq(fills[n]), fill_colors[n+1].eq(fill_colors[n])]

        if self.large_text:
            m.submodules.borders = borders = RoundedBorders()
            m.d.comb += [borders.x.eq(x),borders.y.eq(y),borders.active.eq(active & state["ui_ready"]),
                        borders.surface.eq(state["ui_surface"]),borders.focus.eq(state["ui_focus"]),borders.mode.eq(state["ui_mode"]),borders.keyboard_second.eq(state["keyboard_second"])]

        # One row-wide atlas, fetched in blanking rather than once per pixel.
        # Rotate bitmap samples as well as marker positions for the round panel.
        bitmaps = []
        for orientation in range(32):
            angle = orientation * pi / 32
            rows = []
            for py in range(-16, 17):
                row = 0
                for px in range(-16, 17):
                    lx, ly = (py, -px) if self.rotate_left else (px, py)
                    tangent = lx * cos(angle) + ly * sin(angle)
                    normal = -lx * sin(angle) + ly * cos(angle)
                    row |= int(tangent * tangent * 49 + normal * normal * 256
                               <= 16 * 16 * 49) << (px + 16)
                rows.append(row)
            bitmaps.append(rows)
        m.submodules.sprites = sprites = ScanlineSprites(
            bitmaps, slots=4 if self.ascii_text else 1)
        orientation = Signal(5)
        shape_valid = Signal()
        # Compatibility with the current firmware ABI, without a divider.
        for n in range(32):
            with m.If((state["marker_lens_bank"] == n // 11) &
                      (state["marker_lens_base"] == (n % 11) * 1089)):
                m.d.comb += [orientation.eq(n), shape_valid.eq(1)]
        m.d.comb += [sprites.i.eq(self.i), sprites.row.eq(self.i.y),
                    sprites.prepare.eq((self.i.x == -16) & ~self.i.de),
                    sprites.shape0.eq(orientation),
                    sprites.color0.eq(Cat(state["marker_hue"], Const(12 if self.ascii_text else 15, 4))),
                    sprites.enable0.eq(state["marker_valid"] & shape_valid &
                                       ~state["marker_visualizer"])]
        # Generic text/overlay-only view, published with the same atomic frame
        # snapshot as its text. Keep the cached framebuffer untouched underneath.
        with m.If(state["blank_background"]):
            m.d.comb += sprites.i.pixel.eq(0)
        if self.rotate_left:
            m.d.comb += [sprites.x0.eq(719 - state["marker_y"] - 16),
                        sprites.y0.eq(state["marker_x"] - 16)]
        else:
            m.d.comb += [sprites.x0.eq(state["marker_x"] + self.x_offset - 16),
                        sprites.y0.eq(state["marker_y"] - 16)]
        for slot in range(1, sprites.slots):
            descriptor = state[f"marker{slot}"]
            mx, my = descriptor[:10], descriptor[10:20]
            m.d.comb += [
                getattr(sprites, f"shape{slot}").eq(descriptor[20:25]),
                getattr(sprites, f"color{slot}").eq(Cat(descriptor[25:29], Const(12, 4))),
                getattr(sprites, f"enable{slot}").eq(descriptor[29] & (mx < 720) & (my < 720)),
                getattr(sprites, f"x{slot}").eq(
                    719 - my - 16 if self.rotate_left else mx + self.x_offset - 16),
                getattr(sprites, f"y{slot}").eq(mx - 16 if self.rotate_left else my - 16),
            ]
        sprite3, sprite4 = Signal(ScanPixel), Signal(ScanPixel)
        m.d.dvi += [sprite3.eq(sprites.o), sprite4.eq(sprite3)]

        dx = Signal(signed(13))
        dy = Signal(signed(13))
        m.d.comb += [dx.eq(x - state["marker_x"]), dy.eq(y - state["marker_y"])]
        ax1, ay1 = Signal(13), Signal(13)
        valid1 = Signal()
        hue1 = Signal(4)
        visual1 = Signal()
        m.d.dvi += [
            ax1.eq(Mux(dx < 0, -dx, dx)), ay1.eq(Mux(dy < 0, -dy, dy)),
            valid1.eq(active & state["marker_valid"]),
            hue1.eq(state["marker_hue"]), visual1.eq(state["marker_visualizer"]),
        ]
        halo2 = Signal(4)
        hue2 = Signal(4)
        distance = Mux(ax1 > ay1, ax1 + (ay1 >> 1), ay1 + (ax1 >> 1))
        m.d.dvi += [
            hue2.eq(hue1),
            halo2.eq(Mux(valid1 & visual1,
                         Mux(distance <= 5, 15, Mux(distance <= 12, 8,
                             Mux(distance <= 22, 3, 0))), 0)),
        ]
        halo3 = Signal(4)
        hue3 = Signal(4)
        m.d.dvi += [halo3.eq(halo2), hue3.eq(hue2)]
        intensity4 = Signal(4)
        hue4 = Signal(4)
        m.d.dvi += [
            intensity4.eq(halo3),
            hue4.eq(hue3),
        ]
        marked = Signal(ScanPixel)
        m.d.comb += marked.eq(sprite4)
        with m.If(intensity4 != 0):
            m.d.comb += [marked.pixel.color.eq(hue4), marked.pixel.intensity.eq(intensity4)]

        with m.If(fills[-1]):
            m.d.comb += marked.pixel.eq(fill_colors[-1])

        if self.large_text:
            with m.If(borders.hit):
                m.d.comb += marked.pixel.eq(borders.color)

        # One atlas and one glyph fetch for BOTH text layers. Legacy tuner
        # lettering fits in unused normal-font addresses; the menu keeps the
        # exact normal/bold 9x15 assets from OSCIO/SONORO.
        atlas = [0] * 4096
        for bold, font in enumerate((MENU_FONT_NORMAL, MENU_FONT_BOLD)):
            for glyph in range(95):
                for row in range(15):
                    atlas[row | (glyph << 4) | (bold << 11)] = font[glyph * 15 + row]
        atlas[1536:1536 + len(FONT_INIT)] = FONT_INIT
        planes = [
            (TextPlane(self.UX_TEXT_X, 0, self.UX_COLUMNS, self.UX_ROWS,
                       pitch_x=self.UX_PITCH_X, pitch_y=self.UX_PITCH_Y,
                       scale=1, cell_color=True, pixel_offsets=True, row_stride=self.COLS, bank_stride=2048)
             if self.large_text else
             TextPlane(self.MAIN_TEXT_X, 0, self.COLS, self.ROWS,
                       pitch_x=self.MAIN_TEXT_PITCH, cell_color=True) if self.ascii_text else
             TextPlane(0, 0, self.COLS, self.ROWS, glyph_width=5, glyph_height=7,
                       scale=2, row_bits=3, glyph_bits=6, font_base=1536, bold_bit=None)),
            TextPlane(self.MENU_TEXT_X, self.MENU_TEXT_Y, self.MENU_COLS, self.MENU_ROWS,
                      pitch_x=9, pitch_y=self.MENU_ROW_PITCH, color=0xA9),
        ]
        panels = [None, Panel(self.MENU_X, self.MENU_Y, self.MENU_W, self.MENU_H,
                              rule_x=85, rule_y=8, rule_height=54)]
        # Visible UX controls replace the old popup. Omit its decoder and
        # character fetch entirely in production; retain the legacy adapter.
        memories = [self.tile_memory, self.menu_memory]
        if self.large_text:
            planes, panels, memories = planes[:1], panels[:1], memories[:1]
        m.submodules.text = text = TextCompositor(
            memories, planes, atlas, panels=panels,
            double_buffered=self.double_buffered)
        text_y = ys[4]
        if self.large_text:
            # Native text rows are 32 pixels apart. Move only the second
            # octave caption down 12 pixels, leaving the side pager untouched.
            caption = state["keyboard_second"] & ((state["ui_surface"] == 4) | (state["ui_surface"] == 5)) & (xs[4] < 560) & (ys[4] >= 352) & (ys[4] < 384)
            text_y = Mux(caption, ys[4] - 12, ys[4])
        m.d.comb += [
            text.i.eq(marked), text.x.eq(xs[4]), text.y.eq(text_y),
            text.enable.eq(Const(1) if self.large_text else Cat(Const(1), state["menu_active"])),
            text.bank.eq(self.front_bank),
            self.o.eq(text.o),
        ]
        if self.large_text and self.double_buffered:
            # Independently watch the completed overlay. Reuse the input
            # panel predicate, delayed by the complete overlay latency, rather
            # than duplicating wide output-coordinate comparisons.
            panel_valid = [active] + [Signal() for _ in range(self.LATENCY)]
            for previous, following in zip(panel_valid, panel_valid[1:]):
                m.d.dvi += following.eq(previous)
            output_seen, output_crossed = Signal(), Signal()
            with m.If(text.o.de & ~panel_valid[-1] & (text.o.pixel.as_value() != 0)):
                m.d.dvi += output_seen.eq(1)
            m.submodules.output_error_ff = FFSynchronizer(
                output_seen, output_crossed, o_domain="sync")
            m.d.comb += self.background_errors[1].eq(output_crossed)
        return m

class Peripheral(wiring.Component):
    """CSR state and tile writer for :class:`IntonoOverlay`."""

    class Marker(csr.Register, access="w"):
        x: csr.Field(csr.action.W, unsigned(12))
        y: csr.Field(csr.action.W, unsigned(12))
        hue: csr.Field(csr.action.W, unsigned(4))
        valid: csr.Field(csr.action.W, unsigned(1))
        visualizer: csr.Field(csr.action.W, unsigned(1))
        menu_active: csr.Field(csr.action.W, unsigned(1))

    class TileWrite(csr.Register, access="w"):
        address: csr.Field(csr.action.W, unsigned(12))
        glyph: csr.Field(csr.action.W, unsigned(7))
        bold: csr.Field(csr.action.W, unsigned(1))
        color: csr.Field(csr.action.W, unsigned(8))
        text_offset: csr.Field(csr.action.W, unsigned(2))

    class MarkerShape(csr.Register, access="w"):
        # Firmware selects one explicit EBR and supplies its local sprite base,
        # keeping both the multiply and deep-memory bank cascade out of DVI.
        base: csr.Field(csr.action.W, unsigned(14))
        bank: csr.Field(csr.action.W, unsigned(2))

    class Frame(csr.Register, access="rw"):
        commit: csr.Field(csr.action.W, unsigned(1))
        busy: csr.Field(csr.action.R, unsigned(1))
        back_bank: csr.Field(csr.action.R, unsigned(1))
        swap_background: csr.Field(csr.action.W, unsigned(1))
        background_back: csr.Field(csr.action.R, unsigned(1))
        # 0: mutable CAL banks, 1: ARC, 2: LINEAR, 3: two keyboards, 4: circle, 5: centered keyboard.
        background_source: csr.Field(csr.action.W, unsigned(3))

    class ExtraMarker(csr.Register, access="w"):
        x: csr.Field(csr.action.W, unsigned(10))
        y: csr.Field(csr.action.W, unsigned(10))
        orientation: csr.Field(csr.action.W, unsigned(5))
        hue: csr.Field(csr.action.W, unsigned(4))
        valid: csr.Field(csr.action.W, unsigned(1))

    class Backdrop(csr.Register, access="w"):
        blank: csr.Field(csr.action.W, unsigned(1))
        keyboard_mask: csr.Field(csr.action.W, unsigned(12))
        keyboard_enable: csr.Field(csr.action.W, unsigned(1))
        ui_surface: csr.Field(csr.action.W, unsigned(4))
        ui_focus: csr.Field(csr.action.W, unsigned(5))
        ui_ready: csr.Field(csr.action.W, unsigned(1))
        keyboard_second: csr.Field(csr.action.W, unsigned(1))
        ui_mode: csr.Field(csr.action.W, unsigned(2))
        keyboard_focus: csr.Field(csr.action.W, unsigned(5))

    class KeyboardB(csr.Register, access="w"):
        mask: csr.Field(csr.action.W, unsigned(12))

    class VideoHealth(csr.Register, access="r"):
        gaps: csr.Field(csr.action.R, unsigned(8))
        background_errors: csr.Field(csr.action.R, unsigned(8))

    def __init__(self, *, h_active=1280, rotate_left=False, scene_layout=None, large_text=False):
        self.scene_layout = scene_layout
        self.tile_memory = Memory(
            shape=unsigned(18), depth=4096, init=[])
        # Bits 0..6 select printable ASCII; bit 7 selects the bold face used
        # by draw_options for the active page or option.
        self.menu_memory = Memory(
            shape=unsigned(8), depth=512, init=[])
        self.overlay = IntonoOverlay(
            self.tile_memory, self.menu_memory,
            h_active=h_active, rotate_left=rotate_left, double_buffered=True,
            ascii_text=True, large_text=large_text)
        self.staging = {name: Signal.like(getattr(self.overlay, name))
                        for name in IntonoOverlay.FRAME_FIELDS}
        payload_width = sum(len(field) for field in self.staging.values())
        self.exchange = (FrameExchange(payload_width) if scene_layout is None else
                         SceneExchange(scene_layout, payload_width))

        regs = csr.Builder(addr_width=6, data_width=8)
        self._marker = regs.add("marker", self.Marker(), offset=0x0)
        self._tile_write = regs.add("tile_write", self.TileWrite(), offset=0x4)
        self._frame = regs.add("frame", self.Frame(), offset=0x8)
        self._marker_shape = regs.add(
            "marker_shape", self.MarkerShape(), offset=0xc)
        self._extra_markers = [regs.add(f"marker{slot}", self.ExtraMarker(),
                                       offset=0x10 + (slot - 1) * 4)
                               for slot in range(1, 4)]
        self._backdrop = regs.add("backdrop", self.Backdrop(), offset=0x1c)
        self._keyboard_b = regs.add("keyboard_b", self.KeyboardB(), offset=0x20)
        self._video_health = regs.add("video_health", self.VideoHealth(), offset=0x24)
        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__({
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
            "scanout_gaps": In(16),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.d.comb += [self._video_health.f.gaps.r_data.eq(self.scanout_gaps[:8]),
                     self._video_health.f.background_errors.r_data.eq(self.overlay.background_errors)]
        m.submodules.bridge = self._bridge
        m.submodules.overlay = self.overlay
        m.submodules.tile_memory = self.tile_memory
        m.submodules.menu_memory = self.menu_memory
        exchange = self.exchange
        if self.scene_layout is None:
            m.submodules.exchange = exchange
        else:
            # SceneExchange is owned by the DMA, which supplies its acquire
            # event. This peripheral supplies CPU staging and visible boundary.
            m.d.comb += [exchange.static_source.eq(self._frame.f.background_source.w_data),
                        exchange.swap_background.eq(self._frame.f.swap_background.w_data),
                        self._frame.f.background_back.r_data.eq(exchange.draw_base != 0)]
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)
        with m.If(self._backdrop.element.w_stb & ~exchange.busy):
            m.d.sync += [self.staging["blank_background"].eq(self._backdrop.f.blank.w_data),
                         self.staging["keyboard_mask"].eq(self._backdrop.f.keyboard_mask.w_data),
                         self.staging["keyboard_enable"].eq(self._backdrop.f.keyboard_enable.w_data),
                         self.staging["keyboard_second"].eq(self._backdrop.f.keyboard_second.w_data),
                         self.staging["ui_surface"].eq(self._backdrop.f.ui_surface.w_data),
                         self.staging["ui_focus"].eq(self._backdrop.f.ui_focus.w_data),
                         self.staging["ui_ready"].eq(self._backdrop.f.ui_ready.w_data),
                         self.staging["ui_mode"].eq(self._backdrop.f.ui_mode.w_data),
                         self.staging["keyboard_focus"].eq(self._backdrop.f.keyboard_focus.w_data)]

        with m.If(self._keyboard_b.element.w_stb & ~exchange.busy):
            m.d.sync += self.staging["keyboard_mask_b"].eq(self._keyboard_b.f.mask.w_data)

        m.d.comb += [
            exchange.payload.eq(Cat(*self.staging.values())),
            exchange.submit.eq(self._frame.element.w_stb & self._frame.f.commit.w_data),
            self._frame.f.busy.r_data.eq(exchange.busy),
            self._frame.f.back_bank.r_data.eq(exchange.back_bank),
            # Last blank line, independent of modeline sync polarity. There
            # is a full scanline for publication to settle before visible y=0.
            exchange.boundary.eq((self.overlay.i.y == -1) &
                                 (self.overlay.i.x == 0) & ~self.overlay.i.de),
            self.overlay.front_bank.eq(exchange.front_bank),
            Cat(*(getattr(self.overlay, name) for name in IntonoOverlay.FRAME_FIELDS)).eq(exchange.published),
        ]

        tile_w = self.tile_memory.write_port(domain="sync")
        menu_w = self.menu_memory.write_port(domain="sync")
        m.d.comb += [
            tile_w.addr.eq(Cat(self._tile_write.f.address.w_data[:11], exchange.back_bank)),
            tile_w.data.eq(Cat(self._tile_write.f.glyph.w_data,
                               self._tile_write.f.bold.w_data,
                               self._tile_write.f.color.w_data,
                               self._tile_write.f.text_offset.w_data)),
            tile_w.en.eq(
                self._tile_write.element.w_stb &
                ~exchange.busy & (self._tile_write.f.address.w_data[:11] < 2025) &
                ~self._tile_write.f.address.w_data[11]),
            menu_w.addr.eq(Cat(self._tile_write.f.address.w_data[:8], exchange.back_bank)),
            menu_w.data.eq(Cat(
                self._tile_write.f.glyph.w_data[:6],
                self._tile_write.f.address.w_data[9],
                self._tile_write.f.address.w_data[10])),
            menu_w.en.eq(
                self._tile_write.element.w_stb &
                ~exchange.busy & (self._tile_write.f.address.w_data[:8] < 252) &
                self._tile_write.f.address.w_data[11]),
        ]
        with m.If(self._marker.element.w_stb & ~exchange.busy):
            m.d.sync += [
                self.staging["marker_x"].eq(self._marker.f.x.w_data),
                self.staging["marker_y"].eq(self._marker.f.y.w_data),
                self.staging["marker_hue"].eq(self._marker.f.hue.w_data),
                self.staging["marker_valid"].eq(self._marker.f.valid.w_data),
                self.staging["marker_visualizer"].eq(self._marker.f.visualizer.w_data),
                self.staging["menu_active"].eq(self._marker.f.menu_active.w_data),
            ]
        with m.If(self._marker_shape.element.w_stb & ~exchange.busy):
            m.d.sync += [
                self.staging["marker_lens_base"].eq(
                    self._marker_shape.f.base.w_data),
                self.staging["marker_lens_bank"].eq(
                    self._marker_shape.f.bank.w_data),
            ]
        for slot, register in enumerate(self._extra_markers, 1):
            with m.If(register.element.w_stb & ~exchange.busy):
                m.d.sync += self.staging[f"marker{slot}"].eq(Cat(
                    register.f.x.w_data, register.f.y.w_data,
                    register.f.orientation.w_data, register.f.hue.w_data,
                    register.f.valid.w_data))
        return m
