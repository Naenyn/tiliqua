# Copyright (c) 2026
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Bounded scanline sprite compositor, independent of instrument semantics."""

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.memory import Memory
from amaranth.lib.wiring import In, Out

from tiliqua.video.types import ScanPixel
try:
    from .renderer import constant_product
except ImportError:
    from renderer import constant_product


class ScanlineSprites(wiring.Component):
    """Share one bitmap ROM port across up to four monochrome colored sprites.

    Pulse prepare in horizontal blanking with the NEXT physical scanline in
    row. All descriptors are captured together. ready arrives 2*slots clocks
    later; no pixels are emitted before that, or on a different row. A prepare
    while busy is ignored. Keep prepare low during active video.

    Coordinates and bitmap orientation are physical, after display rotation.
    The caller supplies frame-stable descriptors and must schedule preparation
    after frame publication. This module neither crosses clocks nor owns UI
    state. Later slots win only on opaque bitmap pixels (transparent holes
    reveal earlier sprites). Bitmap bit zero is the leftmost pixel.
    """
    LATENCY = 2

    def __init__(self, bitmaps, *, width=33, height=33, slots=4):
        if not 1 <= slots <= 4 or not 1 <= width <= 64 or not 1 <= height <= 64:
            raise ValueError("sprite dimensions or slot count out of bounds")
        if not bitmaps or any(len(bitmap) != height for bitmap in bitmaps):
            raise ValueError("each bitmap must contain exactly height rows")
        if any(not 0 <= row < (1 << width) for bitmap in bitmaps for row in bitmap):
            raise ValueError("bitmap row exceeds width")
        self.bitmaps = bitmaps
        self.width, self.height, self.slots = width, height, slots
        self.preparation_cycles = 2 * slots
        ports = {"i": In(ScanPixel), "o": Out(ScanPixel),
                 "prepare": In(1), "row": In(signed(12)),
                 "busy": Out(1), "ready": Out(1)}
        for slot in range(slots):
            ports.update({f"x{slot}": In(signed(12)), f"y{slot}": In(signed(12)),
                          f"shape{slot}": In(max(1, (len(bitmaps)-1).bit_length())),
                          f"color{slot}": In(8), f"enable{slot}": In(1)})
        super().__init__(ports)

    def elaborate(self, platform):
        m = Module()
        memory = Memory(shape=unsigned(self.width),
                        depth=len(self.bitmaps) * self.height,
                        init=[row for bitmap in self.bitmaps for row in bitmap],
                        attrs={"ram_style": "block"})
        m.submodules.atlas = memory
        port = memory.read_port(domain="dvi")
        xs = Array(Signal(signed(12), name=f"sprite_x{n}") for n in range(self.slots))
        colors = Array(Signal(8, name=f"sprite_color{n}") for n in range(self.slots))
        addresses = Array(Signal(range(memory.depth), name=f"sprite_addr{n}")
                          for n in range(self.slots))
        enabled = Array(Signal(name=f"sprite_enabled{n}") for n in range(self.slots))
        masks = Array(Signal(self.width, name=f"sprite_row{n}") for n in range(self.slots))
        prepared_row = Signal(signed(12))
        slot = Signal(range(self.slots))
        capture = Signal()
        m.d.comb += [port.addr.eq(addresses[slot]), port.en.eq(self.busy & ~capture)]
        with m.If(self.prepare & ~self.busy):
            m.d.dvi += [self.busy.eq(1), self.ready.eq(0), slot.eq(0),
                        capture.eq(0), prepared_row.eq(self.row)]
            for n in range(self.slots):
                dy = Signal(signed(13), name=f"sprite_dy{n}")
                shape = getattr(self, f"shape{n}")
                valid = Signal()
                m.d.comb += [dy.eq(self.row - getattr(self, f"y{n}")),
                            valid.eq(getattr(self, f"enable{n}") & (dy >= 0) &
                                     (dy < self.height) & (shape < len(self.bitmaps)))]
                m.d.dvi += [xs[n].eq(getattr(self, f"x{n}")),
                            colors[n].eq(getattr(self, f"color{n}")),
                            enabled[n].eq(valid),
                            addresses[n].eq(Mux(valid,
                                constant_product(shape, self.height) + dy, 0))]
        with m.Elif(self.busy):
            with m.If(~capture):
                m.d.dvi += capture.eq(1)
            with m.Else():
                m.d.dvi += [masks[slot].eq(Mux(enabled[slot], port.data, 0)), capture.eq(0)]
                with m.If(slot == self.slots - 1):
                    m.d.dvi += [self.busy.eq(0), self.ready.eq(1)]
                with m.Else():
                    m.d.dvi += slot.eq(slot + 1)

        scan = Signal(ScanPixel)
        hits = Signal(self.slots)
        sampled_colors = [Signal(8) for _ in range(self.slots)]
        m.d.dvi += scan.eq(self.i)
        for n in range(self.slots):
            dx = Signal(signed(13))
            m.d.comb += dx.eq(self.i.x - xs[n])
            m.d.dvi += [hits[n].eq(self.ready & ~self.prepare & self.i.de &
                                  (self.i.y == prepared_row) & (dx >= 0) &
                                  (dx < self.width) &
                                  masks[n].bit_select(dx.as_unsigned()[:6], 1)),
                        sampled_colors[n].eq(colors[n])]
        m.d.dvi += self.o.eq(scan)
        for n in range(self.slots):
            with m.If(hits[n]):
                m.d.dvi += self.o.pixel.eq(sampled_colors[n])
        return m
