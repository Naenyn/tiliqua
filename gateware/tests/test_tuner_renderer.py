"""Raster-stream regressions for the reusable instrument compositor.

The instrument scenes contain synthetic values, not detector/calibrator output.
They exercise the same renderer, including colored, mixed-case profile text.
"""

from collections import deque

import pytest
from amaranth import Module, Signal, unsigned
from amaranth.lib.memory import Memory
from amaranth.sim import Simulator

from top.intono.font_9x15 import MENU_FONT_BOLD, MENU_FONT_NORMAL
from top.intono.renderer import Panel, TextCompositor, TextPlane, divide_coordinate


def atlas():
    result = [0] * 4096
    for bold, face in enumerate((MENU_FONT_NORMAL, MENU_FONT_BOLD)):
        for glyph in range(95):
            result[(bold << 11) + glyph * 16:(bold << 11) + glyph * 16 + 15] = \
                face[glyph * 15:glyph * 15 + 15]
    return result


def text_cells(plane, entries):
    cells = [0] * (plane.columns * plane.rows)
    for column, row, label, color, bold in entries:
        assert column >= 0 and row >= 0
        assert column + len(label) <= plane.columns and row < plane.rows
        for offset, char in enumerate(label):
            assert 32 <= ord(char) <= 126
            cells[row * plane.columns + column + offset] = \
                (ord(char) - 32) | (int(bold) << 7) | (color << 8)
    return cells


def reference_pixel(x, y, background, enabled, planes, panels, contents, font):
    # Independent integer geometry and glyph lookup. Later character boxes
    # own the text sample; panel backgrounds also suppress earlier text.
    pixel = background
    pending = None
    for index, (plane, panel, cells) in enumerate(zip(planes, panels, contents)):
        if not enabled & (1 << index):
            continue
        if panel is not None:
            if not (panel.x <= x < panel.x + panel.width and
                    panel.y <= y < panel.y + panel.height):
                continue
            pixel = panel.fill
            pending = None
            if (x < panel.x + panel.border_width or x >= panel.x + panel.width - panel.border_width or
                    y < panel.y + panel.border_width or y >= panel.y + panel.height - panel.border_width):
                pixel = panel.border
            elif x == panel.x + panel.rule_x and panel.y + panel.rule_y <= y < panel.y + panel.rule_y + panel.rule_height:
                pixel = panel.rule_color
        rx, ry = x - plane.x, y - plane.y
        if not (0 <= rx < plane.columns * plane.pitch_x and 0 <= ry < plane.rows * plane.pitch_y):
            continue
        column, gx = divmod(rx, plane.pitch_x)
        row, gy = divmod(ry, plane.pitch_y)
        gx //= plane.scale
        gy //= plane.scale
        if gx >= plane.glyph_width or gy >= plane.glyph_height:
            continue
        entry = cells[row * plane.columns + column]
        glyph = entry & ((1 << plane.glyph_bits) - 1)
        bold = ((entry >> plane.bold_bit) & 1) if plane.bold_bit is not None else 0
        address = plane.font_base | (bold << (plane.glyph_bits + plane.row_bits)) | (glyph << plane.row_bits) | gy
        color = entry >> 8 if plane.cell_color else (plane.bold_color if bold else plane.color)
        pending = color if font[address] & (1 << (plane.glyph_width - 1 - gx)) else None
    return pending if pending is not None else pixel


def test_pitch_dividers_are_exact_for_all_local_coordinates():
    m = Module()
    coordinate = Signal(10)
    quotients = [Signal(10) for _ in range(3)]
    for quotient, divisor in zip(quotients, (9, 18, 16)):
        m.d.comb += quotient.eq(divide_coordinate(coordinate, divisor))
    sim = Simulator(m)

    async def bench(ctx):
        for x in range(1024):
            ctx.set(coordinate, x)
            for quotient, divisor in zip(quotients, (9, 18, 16)):
                assert ctx.get(quotient) == x // divisor

    sim.add_testbench(bench)
    sim.run()


SCENES = {
    "tuner": [(10, 10, "FOUR INPUT TUNER", 0xD9, True)] + [
        (9, 15 + channel * 5, f"IN{channel}  A#3  +02.4c", color, False)
        for channel, color in enumerate((0xF2, 0xF5, 0xF9, 0xFC))],
    "calibrator": [
        (10, 10, "OSCILLATOR CALIBRATION", 0xD9, True),
        (9, 15, "Profile: VCO North-01", 0xD9, False),
        (9, 20, "Test: -1.250V  110.00Hz", 0xF5, False),
        (9, 25, "Error: +2.4c  Saved: Yes", 0xD9, False),
        (9, 30, "Progress: 12 / 24", 0xD9, False)],
    "quantizer": [
        (10, 10, "QUANTIZER SCALE", 0xD9, True),
        (9, 15, "Scale: Custom 19-EDO", 0xD9, False),
        (9, 20, "Octave: 3   Root: C#", 0xF9, False),
        (9, 25, "0  63 126 189 253 cents", 0xD9, False),
        (9, 30, "Gate: change  OUT: 2", 0xF2, False)],
}


@pytest.mark.parametrize("scene", SCENES)
@pytest.mark.parametrize("menu_enabled", [False, True])
def test_instrument_scenes_use_one_text_pipeline(scene, menu_enabled):
    planes = [TextPlane(0, 0, 45, 45, cell_color=True),
              TextPlane(310, 298, 28, 8, pitch_x=9, pitch_y=18)]
    panels = [None, Panel(304, 290, 272, 164, rule_x=81, rule_y=8, rule_height=72)]
    contents = [text_cells(planes[0], SCENES[scene]),
                text_cells(planes[1], [(0, 0, "OPTIONS", 0, True),
                                      (10, 1, "Page: Tuner", 0, False),
                                      (10, 2, "< Edit", 0, True)])]
    memories = [Memory(shape=unsigned(16), depth=len(cells), init=cells) for cells in contents]
    font = atlas()
    dut = TextCompositor(memories, planes, font, panels=panels)
    m = Module()
    m.submodules.dut = dut
    for index, memory in enumerate(memories):
        m.submodules[f"cells{index}"] = memory
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        enabled = 1 | (int(menu_enabled) << 1)
        ctx.set(dut.enable, enabled)
        queue = deque()
        # Consecutive horizontal pixels, adjacent rows, panel edges, the first
        # pixel after blanking, and invalid signed canvas coordinates. Never
        # hold each pixel long enough to disguise a pipeline alignment error.
        rows = sorted({-1, 0, 719, 720, *range(158, 177), *range(238, 257),
                       *range(287, 345), *range(398, 417), *range(478, 497)})
        for y in rows:
            for x in range(120, 605):
                de = 128 <= x < 600
                bg = 0x39 if (x + y) % 19 == 0 else 0
                expected = reference_pixel(x, y, bg, enabled, planes, panels, contents, font) if de else 0
                ctx.set(dut.x, x)
                ctx.set(dut.y, y)
                ctx.set(dut.i.x, x + 280)
                ctx.set(dut.i.y, y)
                ctx.set(dut.i.de, de)
                ctx.set(dut.i.hsync, x < 125)
                ctx.set(dut.i.vsync, y < 0)
                ctx.set(dut.i.pixel.as_value(), bg)
                queue.append((x + 280, y, de, x < 125, y < 0, expected))
                await ctx.tick("dvi")
                if len(queue) >= dut.LATENCY:
                    out = tuple(ctx.get(value) for value in
                                (dut.o.x, dut.o.y, dut.o.de, dut.o.hsync, dut.o.vsync, dut.o.pixel.as_value()))
                    assert out == queue.popleft(), (scene, x, y, out)
        for _ in range(dut.LATENCY - 1):
            await ctx.tick("dvi")
            out = tuple(ctx.get(value) for value in
                        (dut.o.x, dut.o.y, dut.o.de, dut.o.hsync, dut.o.vsync, dut.o.pixel.as_value()))
            assert out == queue.popleft()

    sim.add_testbench(bench)
    sim.run()
