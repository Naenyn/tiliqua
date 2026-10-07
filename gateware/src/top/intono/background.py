# Copyright (c) 2026
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Background-buffer ownership groundwork; not yet connected to scanout."""

from dataclasses import dataclass
from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out


@dataclass(frozen=True)
class BackgroundLayout:
    """Byte offsets relative to PSRAM, not CPU or Wishbone addresses."""
    width: int
    height: int
    stride: int = 0x100000
    firmware_start: int = 0x200000

    def __post_init__(self):
        if not (0 < self.width <= 1280 and 0 < self.height <= 720):
            raise ValueError("unsupported framebuffer dimensions")
        if self.frame_bytes % 4 or self.stride % 4:
            raise ValueError("DMA storage must be word aligned")
        if self.frame_bytes > self.stride or self.stride + self.frame_bytes > self.firmware_start:
            raise ValueError("background buffers overlap each other or firmware")

    @property
    def frame_bytes(self):
        return self.width * self.height

    @property
    def word_bases(self):
        return (0, self.stride // 4)


class BackgroundExchange(wiring.Component):
    """One pending background commit, entirely in the CPU/DMA sync domain.

    CPU draws only when writable, into draw_base, flushes its cache, then
    pulses submit. DMA must sample next_base on the SAME edge it pulses acquire,
    exactly once before fetching a whole frame. acquire is NOT the vsync level:
    it is a reader-owned event after all old-frame bus transactions complete.

    Both buffers must be initialized before enabling the reader. Acknowledging
    acquisition releases the old PSRAM buffer for writing; FIFO pixels already
    copied from it remain valid. This does not acknowledge on-screen visibility.
    Text/sprites still need a separately coordinated visible-frame transaction.
    """
    def __init__(self, layout):
        self.layout = layout
        super().__init__({
            "submit": In(1), "acquire": In(1),
            "busy": Out(1), "writable": Out(1), "released": Out(1),
            "front_bank": Out(1), "draw_bank": Out(1),
            "next_base": Out(22), "draw_base": Out(22),
        })

    def elaborate(self, platform):
        m = Module()
        pending = Signal()
        front = Signal()
        m.d.comb += [self.busy.eq(pending), self.writable.eq(~pending),
                    self.front_bank.eq(front), self.draw_bank.eq(~front),
                    self.next_base.eq(Mux(front ^ pending, self.layout.word_bases[1], 0)),
                    self.draw_base.eq(Mux(~front, self.layout.word_bases[1], 0))]
        m.d.sync += self.released.eq(0)
        with m.If(pending):
            with m.If(self.acquire):
                m.d.sync += [front.eq(~front), pending.eq(0), self.released.eq(1)]
        with m.Elif(self.submit):
            # If acquisition and submission coincide, the reader takes the old
            # front this time. The just-submitted image waits for next acquire.
            m.d.sync += pending.eq(1)
        return m


class SceneExchange(wiring.Component):
    """Acquire background in sync, then publish held foreground in dvi blanking.

    One outstanding scene includes the text-bank selection, marker payload and
    optional background swap. The CPU keeps ALL back buffers frozen until busy
    clears, deliberately later than the DMA-only ownership acknowledgement.
    `boundary` must be after DMA acquisition has crossed into dvi and before the
    first visible pixel; supported display timing must guarantee that interval.
    No independent reset of either clock domain is supported during a commit.
    """
    def __init__(self, layout, payload_width):
        self.layout = layout
        super().__init__({
            "submit": In(1), "payload": In(payload_width),
            "swap_background": In(1), "static_source": In(3),
            "acquire": In(1), "boundary": In(1),
            "busy": Out(1), "next_base": Out(22), "draw_base": Out(22),
            "back_bank": Out(1), "front_bank": Out(1),
            "visible_background": Out(1), "published": Out(payload_width),
        })

    def elaborate(self, platform):
        m = Module()
        request, acquired, acknowledged = Signal(), Signal(), Signal()
        acquired_dvi, acknowledged_sync = Signal(), Signal()
        held = Signal.like(self.payload)
        held_background, dma_background = Signal(), Signal()
        held_source, dma_source = Signal(3), Signal(3)
        m.submodules.acquired_ff = FFSynchronizer(acquired, acquired_dvi, o_domain="dvi")
        m.submodules.ack_ff = FFSynchronizer(acknowledged, acknowledged_sync, o_domain="sync")
        selected = Mux(request != acquired, held_background, dma_background)
        source = Mux(request != acquired, held_source, dma_source)
        # Immutable images never become CPU draw buffers. Keep CAL bank
        # ownership independent while tuner or scale guides are scanned directly.
        base = Mux(source == 1, 0x800000 // 4,
                   Mux(source == 2, 0x900000 // 4,
                       Mux(source == 3, 0xB00000 // 4,
                           Mux(source == 4, 0xA00000 // 4,
                               Mux(source == 5, 0xC00000 // 4,
                                   Mux(source == 6, 0xD00000 // 4,
                                       Mux(selected, self.layout.word_bases[1], 0)))))))
        m.d.comb += [self.busy.eq(request != acknowledged_sync),
                    self.back_bank.eq(~acknowledged_sync),
                    self.next_base.eq(base),
                    self.draw_base.eq(Mux(~dma_background, self.layout.word_bases[1], 0))]
        with m.If(self.submit & ~self.busy):
            m.d.sync += [held.eq(self.payload), request.eq(~request),
                        held_background.eq(dma_background ^ self.swap_background),
                        held_source.eq(self.static_source)]
        with m.If(self.acquire & (request != acquired)):
            m.d.sync += [dma_background.eq(held_background), dma_source.eq(held_source), acquired.eq(request)]
        with m.If(self.boundary & (acquired_dvi != acknowledged)):
            m.d.dvi += [self.published.eq(held), self.front_bank.eq(acquired_dvi),
                        self.visible_background.eq(held_background),
                        acknowledged.eq(acquired_dvi)]
        return m
