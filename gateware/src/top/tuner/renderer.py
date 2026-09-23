# Copyright (c) 2026
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Reusable, fixed-latency text compositor for CPU-authored instrument UIs.

This module knows nothing about pitch, scales, menus, or display modelines.
Its inputs are logical canvas coordinates, a background pixel stream, character
memories and layer enables. Later layers have priority, including opaque panel
backgrounds. All layers share ONE synchronous glyph ROM read port.
"""

from dataclasses import dataclass

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.memory import Memory
from amaranth.lib.wiring import In, Out

from tiliqua.video.types import ScanPixel


class FrameExchange(wiring.Component):
    """One outstanding sync->dvi frame transaction with acknowledged ownership.

    Submit freezes the payload until the DVI reader adopts it at a blanking
    boundary. The request/acknowledgement toggles cross through synchronizers;
    the bundled payload is held from before request arrival until after ack.
    The writer must gate ALL back-buffer writes with busy, and cannot reuse the
    former front bank until the acknowledgement has returned to sync.
    """
    def __init__(self, payload_width):
        super().__init__({
            "submit": In(1), "payload": In(payload_width), "busy": Out(1),
            "back_bank": Out(1), "boundary": In(1),
            "front_bank": Out(1), "published": Out(payload_width),
        })

    def elaborate(self, platform):
        m = Module()
        request = Signal()
        request_dvi = Signal()
        acknowledged = Signal()
        acknowledged_sync = Signal()
        held = Signal.like(self.payload)
        m.submodules.request_ff = FFSynchronizer(request, request_dvi, o_domain="dvi")
        m.submodules.ack_ff = FFSynchronizer(acknowledged, acknowledged_sync, o_domain="sync")
        m.d.comb += [self.busy.eq(request != acknowledged_sync),
                     self.back_bank.eq(~acknowledged_sync)]
        with m.If(self.submit & ~self.busy):
            m.d.sync += [held.eq(self.payload), request.eq(~request)]
        with m.If(self.boundary & (request_dvi != acknowledged)):
            m.d.dvi += [self.published.eq(held), self.front_bank.eq(request_dvi),
                        acknowledged.eq(request_dvi)]
        return m


@dataclass(frozen=True)
class TextPlane:
    x: int
    y: int
    columns: int
    rows: int
    pitch_x: int = 16
    pitch_y: int = 16
    glyph_width: int = 9
    glyph_height: int = 15
    scale: int = 1
    row_bits: int = 4
    glyph_bits: int = 7
    font_base: int = 0
    bold_bit: int | None = 7
    color: int = 0xD9  # Pixel: low nibble hue, high nibble intensity.
    bold_color: int = 0xF9
    cell_color: bool = False  # Optional bits 8..15 of a character entry.

    def __post_init__(self):
        assert self.scale in (1, 2)
        assert 1 <= self.glyph_width <= 9 and self.glyph_height > 0
        assert self.row_bits in (3, 4) and 1 <= self.glyph_bits <= 7
        assert self.bold_bit is None or self.bold_bit >= self.glyph_bits
        assert 0 < self.columns and 0 < self.rows
        assert self.columns * self.pitch_x <= 1024
        assert self.rows * self.pitch_y <= 1024
        assert self.glyph_width * self.scale <= self.pitch_x
        assert self.glyph_height * self.scale <= self.pitch_y
        assert self.glyph_height <= 1 << self.row_bits
        assert self.font_base % (1 << (self.glyph_bits + self.row_bits)) == 0


@dataclass(frozen=True)
class Panel:
    """Opaque layer backdrop. Borders/rules use the same pixel pipeline."""
    x: int
    y: int
    width: int
    height: int
    fill: int = 0
    border: int = 0xA9
    border_width: int = 2
    rule_x: int = 0
    rule_y: int = 0
    rule_height: int = 0
    rule_color: int = 0x39


def constant_product(value, factor):
    """Signed-digit shift/add network; never infer scarce audio DSP blocks."""
    assert factor > 0
    positive, negative = [], []
    shift = 0
    while factor:
        if factor & 1:
            digit = 2 - (factor & 3)
            (positive if digit == 1 else negative).append(value << shift)
            factor -= digit
        factor >>= 1
        shift += 1

    def balanced_sum(terms):
        if not terms:
            return Const(0)
        while len(terms) > 1:
            terms = [terms[n] + terms[n + 1] if n + 1 < len(terms) else terms[n]
                     for n in range(0, len(terms), 2)]
        return terms[0]

    return balanced_sum(positive) - balanced_sum(negative)


def divide_coordinate(value, divisor):
    """Exact unsigned division for the bounded 10-bit local coordinates.

    No coordinate lookup EBRs or general divider. Power-of-two pitches are
    wires; other pitches use a constant reciprocal, with enough fractional
    bits to be exact for EVERY value 0..1023 (checked at elaboration).
    """
    assert divisor > 0
    if divisor & (divisor - 1) == 0:
        return value >> (divisor.bit_length() - 1)
    shift = 13
    while True:
        reciprocal = ((1 << shift) + divisor - 1) // divisor
        if all((x * reciprocal) >> shift == x // divisor for x in range(1024)):
            return constant_product(value, reciprocal) >> shift
        shift += 1


class TextCompositor(wiring.Component):
    """Five pixel clocks, including blanking and all timing sidebands.

    Character memories are owned/written by the caller. A plane may contain
    8-bit glyph/bold entries or 16-bit glyph/bold/color entries. Panel and text
    coordinates are logical canvas coordinates, not physical display pixels.
    Frame publication/CDC is the caller's responsibility; enables must remain
    stable through active video. No framebuffer or extra scanout is created.
    """
    LATENCY = 5

    def __init__(self, memories, planes, font_rows, *, panels=None, double_buffered=False):
        self.memories = tuple(memories)
        self.planes = tuple(planes)
        self.font_rows = tuple(font_rows)
        self.panels = tuple(panels or [None] * len(planes))
        self.double_buffered = double_buffered
        assert len(memories) == len(planes) == len(self.panels) > 0
        for memory, plane in zip(memories, planes):
            assert memory.depth >= plane.columns * plane.rows
            if double_buffered:
                assert memory.depth >= 2 << (plane.columns * plane.rows - 1).bit_length()
            required_width = 16 if plane.cell_color else max(
                plane.glyph_bits, 0 if plane.bold_bit is None else plane.bold_bit + 1)
            assert Shape.cast(memory.shape).width >= required_width
            address_bits = plane.glyph_bits + plane.row_bits + (plane.bold_bit is not None)
            assert 0 <= plane.font_base and plane.font_base + (1 << address_bits) <= len(font_rows)
        assert all(0 <= row < 512 for row in font_rows)
        super().__init__({
            "i": In(ScanPixel), "o": Out(ScanPixel),
            "x": In(signed(12)), "y": In(signed(12)),
            "enable": In(len(planes)),
            "bank": In(1),
        })

    def elaborate(self, platform):
        m = Module()
        scans = [self.i] + [Signal(ScanPixel, name=f"scan{n}") for n in range(1, 6)]
        for previous, following in zip(scans, scans[1:]):
            m.d.dvi += following.eq(previous)

        font = Memory(shape=unsigned(9), depth=len(self.font_rows),
                      init=self.font_rows, attrs={"ram_style": "block"})
        font_r = font.read_port(domain="dvi")
        m.submodules.font = font
        candidates = []
        # Stage 1: bounded local coordinates and opaque panel geometry.
        for index, (memory, plane, panel) in enumerate(zip(
                self.memories, self.planes, self.panels)):
            rx = Signal(10, name=f"rx{index}_1")
            ry = Signal(10, name=f"ry{index}_1")
            valid1 = Signal()
            covered1 = Signal()
            backdrop1 = Signal(8)
            enabled = self.enable[index] & self.i.de
            inside = Const(0)
            backdrop = Const(0, 8)
            if panel is not None:
                inside = enabled & (self.x >= panel.x) & (self.x < panel.x + panel.width) & \
                    (self.y >= panel.y) & (self.y < panel.y + panel.height)
                border = (self.x < panel.x + panel.border_width) | \
                    (self.x >= panel.x + panel.width - panel.border_width) | \
                    (self.y < panel.y + panel.border_width) | \
                    (self.y >= panel.y + panel.height - panel.border_width)
                rule = (self.x == panel.x + panel.rule_x) & \
                    (self.y >= panel.y + panel.rule_y) & \
                    (self.y < panel.y + panel.rule_y + panel.rule_height)
                backdrop = Mux(border, panel.border, Mux(rule, panel.rule_color, panel.fill))
            text_area = enabled & (self.x >= plane.x) & \
                (self.x < plane.x + plane.columns * plane.pitch_x) & \
                (self.y >= plane.y) & (self.y < plane.y + plane.rows * plane.pitch_y)
            if panel is not None:
                text_area = text_area & inside
            m.d.dvi += [rx.eq(self.x - plane.x), ry.eq(self.y - plane.y),
                        valid1.eq(text_area), covered1.eq(inside), backdrop1.eq(backdrop)]

            # Stage 2: constant-pitch division, isolated from address generation.
            cx2 = Signal(10)
            cy2 = Signal(10)
            rx2 = Signal.like(rx)
            ry2 = Signal.like(ry)
            valid2 = Signal()
            covered2 = Signal()
            backdrop2 = Signal(8)
            m.d.dvi += [cx2.eq(divide_coordinate(rx, plane.pitch_x)),
                        cy2.eq(divide_coordinate(ry, plane.pitch_y)),
                        rx2.eq(rx), ry2.eq(ry), valid2.eq(valid1),
                        covered2.eq(covered1), backdrop2.eq(backdrop1)]

            # Stage 3: one character fetch per plane, glyph-local coordinates.
            cell = memory.read_port(domain="dvi")
            address = constant_product(cy2, plane.columns) + cx2
            if self.double_buffered:
                bank_bit = (plane.columns * plane.rows - 1).bit_length()
                address = Cat(address[:bank_bit], self.bank)
            m.d.comb += [cell.addr.eq(address), cell.en.eq(valid2)]
            gx3 = Signal(10)
            gy3 = Signal(10)
            valid3 = Signal()
            covered3 = Signal()
            backdrop3 = Signal(8)
            m.d.dvi += [gx3.eq((rx2 - constant_product(cx2, plane.pitch_x)) >> (plane.scale - 1)),
                        gy3.eq((ry2 - constant_product(cy2, plane.pitch_y)) >> (plane.scale - 1)),
                        valid3.eq(valid2), covered3.eq(covered2), backdrop3.eq(backdrop2)]
            glyph = cell.data[:plane.glyph_bits]
            bold = cell.data[plane.bold_bit] if plane.bold_bit is not None else Const(0)
            address = plane.font_base | Cat(gy3[:plane.row_bits], glyph, bold)
            color = cell.data[8:16] if plane.cell_color else Mux(bold, plane.bold_color, plane.color)
            candidates.append((valid3 & (gx3 < plane.glyph_width) & (gy3 < plane.glyph_height),
                               covered3, backdrop3, address, plane.glyph_width - 1 - gx3, color))

        # Stage 4: choose the frontmost layer BEFORE the shared font lookup.
        address3 = Signal(range(len(self.font_rows)))
        bit3 = Signal(4)
        color3 = Signal(8)
        hit3 = Signal()
        cover3 = Signal()
        background3 = Signal(8)
        m.d.comb += [address3.eq(0), bit3.eq(0), color3.eq(0), hit3.eq(0),
                     cover3.eq(0), background3.eq(0)]
        for valid, covered, backdrop, address, bit, color in candidates:
            with m.If(covered):
                m.d.comb += [cover3.eq(1), background3.eq(backdrop), hit3.eq(0)]
            with m.If(valid):
                m.d.comb += [address3.eq(address), bit3.eq(bit), color3.eq(color), hit3.eq(1)]
        m.d.comb += [font_r.addr.eq(address3), font_r.en.eq(hit3)]
        bit4 = Signal(4)
        color4 = Signal(8)
        hit4 = Signal()
        cover4 = Signal()
        background4 = Signal(8)
        m.d.dvi += [bit4.eq(bit3), color4.eq(color3), hit4.eq(hit3),
                    cover4.eq(cover3), background4.eq(background3)]

        # Stage 5: the only glyph bit selector, then pixel composition.
        foreground5 = Signal()
        color5 = Signal(8)
        cover5 = Signal()
        background5 = Signal(8)
        m.d.dvi += [foreground5.eq(hit4 & font_r.data.bit_select(bit4, 1)),
                    color5.eq(color4), cover5.eq(cover4), background5.eq(background4)]
        m.d.comb += self.o.eq(scans[5])
        with m.If(cover5):
            m.d.comb += self.o.pixel.eq(background5)
        with m.If(foreground5):
            m.d.comb += self.o.pixel.eq(color5)
        with m.If(~scans[5].de):
            m.d.comb += self.o.pixel.eq(0)
        return m
