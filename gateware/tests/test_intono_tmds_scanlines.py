"""Exercise the wire symbols behind Intono's sparse, high-contrast rows."""

import random

from amaranth.sim import Simulator

from tiliqua.video.tmds import TMDSEncoder


def test_scanline_symbols_decode_without_colour_trails():
    # Decode symbols independently of the encoder's disparity decisions. A
    # coloured run after text must not be hidden by merely comparing two PHYs.
    def decode(symbol):
        qm = symbol & 255
        if symbol & 512:
            qm ^= 255
        value = qm & 1
        for bit in range(1, 8):
            decoded = ((qm >> bit) ^ (qm >> (bit - 1))) & 1
            if not symbol & 256:
                decoded ^= 1
            value |= decoded << bit
        return value

    controls = (0b1101010100, 0b0010101011,
                0b0101010100, 0b1010101011)
    rng = random.Random(239)
    rows = [
        [0] * 780 + [255] * 18 + [0] * 482,
        [0] * 400 + [85, 191, 232, 255, 144, 0] * 70 + [0] * 460,
        list(range(256)) * 5,
        [rng.randrange(256) for _ in range(1280)],
    ]
    # Both white/black transitions and each constant byte over a full scanline
    # exercise long repeated symbols and the reset of disparity in blanking.
    rows += [[level] * 1280 for level in range(256)]
    dut = TMDSEncoder()
    sim = Simulator(dut)
    sim.add_clock(1 / 74_250_000, domain="dvi")

    async def bench(ctx):
        previous = None
        disparity = 0

        async def sample(data, de, control=0):
            nonlocal previous, disparity
            ctx.set(dut.data_in, data)
            ctx.set(dut.de, de)
            ctx.set(dut.ctrl_in, control)
            await ctx.tick("dvi")
            symbol = ctx.get(dut.tmds)
            if previous is not None:
                old_data, old_de, old_control = previous
                if old_de:
                    assert decode(symbol) == old_data
                    disparity += 2 * symbol.bit_count() - 10
                    assert abs(disparity) <= 8
                else:
                    assert symbol == controls[old_control]
                    disparity = 0
            previous = data, de, control

        for row_number, row in enumerate(rows):
            for control in range(4):
                await sample(0, 0, control)
            for value in row:
                await sample(value, 1)
            await sample(0, 0, row_number % 4)
        await sample(0, 0)

    sim.add_testbench(bench)
    sim.run()
