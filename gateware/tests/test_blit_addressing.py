"""Sprite-address regression for the OSCIO row-base optimization."""
import pytest
from amaranth import Module
from amaranth.sim import Simulator
from amaranth_soc import csr
from amaranth_soc.csr import wishbone as csr_wishbone
from tiliqua.raster import blit
from tiliqua.test import csr as csr_util, wishbone


@pytest.mark.parametrize("sheet_width", [32, 40, 144])
@pytest.mark.parametrize("stall", [False, True])
def test_sprite_subrectangles_match_bitmap_under_backpressure(sheet_width, stall):
    dut = blit.Peripheral()
    m = Module()
    decoder = csr.Decoder(addr_width=28, data_width=8)
    decoder.add(dut.csr_bus, addr=0, name="dut")
    bridge = csr_wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
    m.submodules += [dut, decoder, bridge]
    sim = Simulator(m)
    sim.add_clock(1e-6)
    pixels = [[(x * 7 + y * 11) % 13 < 6 for x in range(sheet_width)]
              for y in range(20)]
    packed = bytearray()
    for row in pixels:
        for x in range(0, sheet_width, 8):
            packed.append(sum(int(row[x + bit]) << (7 - bit) for bit in range(8)))
    packed.extend(bytes((-len(packed)) % 4))
    actual = []
    expected = []

    async def monitor(ctx):
        cycle = 0
        while True:
            ready = not stall or cycle % 7 in (0, 1, 4)
            ctx.set(dut.o.ready, ready)
            if ready and ctx.get(dut.o.valid):
                actual.append((ctx.get(dut.o.payload.x),
                               ctx.get(dut.o.payload.y),
                               ctx.get(dut.o.payload.pixel.as_value())))
            await ctx.tick()
            cycle += 1

    async def bench(ctx):
        async def write(register, fields):
            await csr_util.wb_csr_w_dict(
                ctx, dut.csr_bus, bridge.wb_bus, register, fields)

        for offset in range(0, len(packed), 4):
            await wishbone.classic_wr(
                ctx, dut.sprite_mem_bus, adr=offset // 4,
                dat_w=int.from_bytes(packed[offset:offset + 4], "little"))
        await write("sheet_width", {"width": sheet_width})
        for sx, sy, width, height, dx, dy, color in (
                (3, 2, 23, 9, 15, 21, 0xAB),
                (9, 7, 13, 6, 50, 40, 0xC5)):
            await write("src", {"src_x": sx, "src_y": sy,
                                "width": width, "height": height})
            await write("blit", {"dst_x": dx, "dst_y": dy, "pixel": color})
            expected.extend((dx + x, dy + y, color)
                            for y in range(height) for x in range(width)
                            if pixels[sy + y][sx + x])
            for _ in range(5000):
                await ctx.tick()
        assert actual == expected

    sim.add_testbench(monitor, background=True)
    sim.add_testbench(bench)
    sim.run()

