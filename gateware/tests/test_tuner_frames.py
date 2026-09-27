"""Adversarial frame ownership tests using unrelated CPU/pixel clocks."""

import pytest
from amaranth.sim import Simulator

from top.intono.display import FONT_INDEX, Peripheral, IntonoOverlay
from top.intono.font_9x15 import MENU_FONT_BOLD, MENU_FONT_NORMAL
from top.intono.renderer import FrameExchange


@pytest.mark.parametrize("cpu_period,pixel_period", [(1e-6, 1.7e-6), (1.7e-6, 1e-6), (1e-6, 1.01e-6)])
def test_frame_exchange_holds_payload_until_ack(cpu_period, pixel_period):
    dut = FrameExchange(32)
    sim = Simulator(dut)
    sim.add_clock(cpu_period, domain="sync")
    sim.add_clock(pixel_period, domain="dvi")

    async def bench(ctx):
        assert ctx.get(dut.back_bank) == 1
        assert ctx.get(dut.front_bank) == 0
        for number, payload in enumerate((0xABCDEF01, 0x12345678, 0x5555AAAA)):
            ctx.set(dut.payload, payload)
            ctx.set(dut.submit, 1)
            await ctx.tick("sync")
            assert ctx.get(dut.busy)
            # Illegal extra requests and changes to the staging input cannot
            # replace the transaction while the display owns it.
            ctx.set(dut.payload, ~payload & 0xFFFFFFFF)
            await ctx.tick("sync").repeat(9)
            ctx.set(dut.submit, 0)
            await ctx.tick("dvi").repeat(9)
            assert ctx.get(dut.busy)
            assert ctx.get(dut.front_bank) == number % 2
            ctx.set(dut.boundary, 1)
            await ctx.tick("dvi")
            ctx.set(dut.boundary, 0)
            assert ctx.get(dut.published) == payload
            assert ctx.get(dut.front_bank) == (number + 1) % 2
            # The CPU may not reclaim the old front before ack crosses back.
            await ctx.tick("sync").repeat(4)
            assert not ctx.get(dut.busy)
            assert ctx.get(dut.back_bank) == number % 2
            await ctx.tick("dvi").repeat(5)
            assert ctx.get(dut.published) == payload

    sim.add_testbench(bench)
    sim.run()


def test_cpu_registers_publish_characters_marker_and_menu_atomically():
    dut = Peripheral()
    sim = Simulator(dut)
    sim.add_clock(1.3e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")

    async def write(ctx, address, value):
        # Exercise the actual byte-wide CSR bridge, not private field strobes.
        for byte in range(4):
            ctx.set(dut.bus.addr, address + byte)
            ctx.set(dut.bus.w_data, (value >> (byte * 8)) & 255)
            ctx.set(dut.bus.w_stb, 1)
            await ctx.tick("sync")
        ctx.set(dut.bus.w_stb, 0)
        await ctx.tick("sync")

    async def read_status(ctx):
        ctx.set(dut.bus.addr, 8)
        ctx.set(dut.bus.r_stb, 1)
        await ctx.tick("sync")
        value = ctx.get(dut.bus.r_data)
        ctx.set(dut.bus.r_stb, 0)
        return value

    async def boundary(ctx):
        ctx.set(dut.overlay.i.de, 0)
        ctx.set(dut.overlay.i.y, -1)
        ctx.set(dut.overlay.i.x, 0)
        await ctx.tick("dvi")
        ctx.set(dut.overlay.i.x, 1)
        await ctx.tick("sync").repeat(4)

    async def bench(ctx):
        ctx.set(dut.overlay.i.x, 100)
        ctx.set(dut.overlay.i.y, 100)
        ctx.set(dut.overlay.i.de, 1)
        assert await read_status(ctx) == 4  # idle, back bank 1
        for iteration, glyph in enumerate(("a", "B", "~", "d")):
            front_before = iteration % 2
            back = 1 - front_before
            x, y, hue = 350 + iteration, 300 + iteration, 5 + iteration
            active = iteration & 1
            color = (0xF1, 0xF5, 0xFA, 0xFE)[iteration]
            cell = (ord(glyph) - 32) | (active << 7) | (color << 8)
            await write(ctx, 4, cell << 12)
            # Distinct bold menu glyphs in successive back banks.
            menu_glyph = 1 + iteration
            await write(ctx, 4, 0xC00 | (menu_glyph << 12))
            await write(ctx, 0, x | (y << 12) | (hue << 24) | (1 << 28) | (active << 30))
            await write(ctx, 12, 1089 | (1 << 14))
            extras = [((400 + slot) | (320 << 10) | (slot << 20) |
                       ((slot + 2) << 25) | ((iteration != 3) << 29))
                      for slot in range(1, 4)]
            for slot, descriptor in enumerate(extras, 1):
                await write(ctx, 12 + slot * 4, descriptor)
            await write(ctx, 28, active)
            assert ctx.get(dut.exchange.front_bank) == front_before
            await write(ctx, 8, 1)
            assert (await read_status(ctx)) & 2
            # Try to corrupt both banks and the held geometry while pending.
            await write(ctx, 4, FONT_INDEX["Z"] << 12)
            await write(ctx, 4, 0x800 | (2 << 12))
            await write(ctx, 0, 0)
            await write(ctx, 12, 0)
            await write(ctx, 28, 1-active)
            for slot in range(1, 4):
                await write(ctx, 12 + slot * 4, 0)
            await write(ctx, 8, 1)
            assert ctx.get(dut.exchange.front_bank) == front_before
            await boundary(ctx)
            assert not (await read_status(ctx)) & 2
            assert ctx.get(dut.exchange.front_bank) == back
            assert ctx.get(dut.overlay.marker_x) == x
            assert ctx.get(dut.overlay.marker_y) == y
            assert ctx.get(dut.overlay.marker_hue) == hue
            assert ctx.get(dut.overlay.marker_valid) == 1
            assert ctx.get(dut.overlay.menu_active) == active
            assert ctx.get(dut.overlay.blank_background) == active
            assert ctx.get(dut.overlay.marker_lens_base) == 1089
            assert ctx.get(dut.overlay.marker_lens_bank) == 1
            for slot, descriptor in enumerate(extras, 1):
                assert ctx.get(getattr(dut.overlay, f"marker{slot}")) == descriptor
            assert ctx.get(dut.tile_memory.data[(back << 11)]) == cell
            assert ctx.get(dut.menu_memory.data[(back << 8)]) == 128 + menu_glyph
            # Sample a glyph pixel through the production banked renderer.
            ctx.set(dut.overlay.i.de, 1)
            font = MENU_FONT_BOLD if active else MENU_FONT_NORMAL
            gx, gy = next((gx, gy) for gy in range(15) for gx in range(9)
                          if font[(ord(glyph) - 32) * 15 + gy] & (1 << (8 - gx)))
            ctx.set(dut.overlay.i.x, 280 + IntonoOverlay.MAIN_TEXT_X + gx)
            ctx.set(dut.overlay.i.y, gy)
            await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
            assert ctx.get(dut.overlay.o.pixel.intensity) == 15
            assert ctx.get(dut.overlay.o.pixel.color) == (color & 15)
            gx, gy = next((gx, gy) for gy in range(15) for gx in range(9)
                          if MENU_FONT_BOLD[menu_glyph * 15 + gy] & (1 << (8 - gx)))
            ctx.set(dut.overlay.i.x, 280 + IntonoOverlay.MENU_TEXT_X + gx)
            ctx.set(dut.overlay.i.y, IntonoOverlay.MENU_TEXT_Y + gy)
            await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
            assert ctx.get(dut.overlay.o.pixel.intensity) == (15 if active else 0)
        # Blank boundaries without a pending transaction must not swap banks.
        front = ctx.get(dut.exchange.front_bank)
        await boundary(ctx)
        assert ctx.get(dut.exchange.front_bank) == front

    sim.add_testbench(bench)
    sim.run()
