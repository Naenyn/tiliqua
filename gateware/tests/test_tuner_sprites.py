from collections import deque
import random

import pytest
from amaranth import Value
from amaranth.sim import Simulator

from top.intono.sprites import ScanlineSprites


@pytest.mark.parametrize("slots", [1, 4])
def test_shared_sprite_rows_against_reference(slots):
    rng = random.Random(716)
    width, height = 33, 33
    bitmaps = [[rng.getrandbits(width) for _ in range(height)] for _ in range(3)]
    dut = ScanlineSprites(bitmaps, slots=slots)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        assert not ctx.get(dut.ready)
        for row in range(-2, 40):
            # Overlapping and clipped sprites, including an invalid shape.
            descriptors = [(n * 7 - 10, n * 3, (n + row) % 4,
                            0xF1 + n, (n + row) % 7 != 0) for n in range(slots)]
            ctx.set(dut.i.de, 0)
            ctx.set(dut.row, row)
            for n, (x, y, shape, color, enabled) in enumerate(descriptors):
                for field, value in zip(("x", "y", "shape", "color", "enable"),
                                        (x, y, shape, color, enabled)):
                    ctx.set(getattr(dut, f"{field}{n}"), value)
            ctx.set(dut.prepare, 1)
            await ctx.tick("dvi")
            assert ctx.get(dut.busy) and not ctx.get(dut.ready)
            # A duplicate request and changed inputs cannot mutate captured rows.
            ctx.set(dut.row, 999)
            ctx.set(dut.x0, 999)
            for cycle in range(dut.preparation_cycles):
                if cycle == 1:
                    ctx.set(dut.prepare, 0)
                await ctx.tick("dvi")
                assert ctx.get(dut.ready) == (cycle == dut.preparation_cycles - 1)
            assert not ctx.get(dut.busy)
            queue = deque()
            for x in range(-20, 85):
                # Also exercise blanking, wrong rows and transparent priority.
                y = row + (1 if x % 19 == 0 else 0)
                de = x % 17 != 0
                bg = 0x32
                expected = bg
                for sx, sy, shape, color, enabled in descriptors:
                    dx, dy = x - sx, row - sy
                    if (de and y == row and enabled and shape < len(bitmaps) and
                            0 <= dx < width and 0 <= dy < height and
                            (bitmaps[shape][dy] >> dx) & 1):
                        expected = color
                hs, vs = x % 3 == 0, x % 5 == 0
                for field, value in (("x", x), ("y", y), ("de", de),
                                     ("hsync", hs), ("vsync", vs), ("pixel", bg)):
                    ctx.set(Value.cast(getattr(dut.i, field)), value)
                queue.append((x, y, de, hs, vs, expected))
                await ctx.tick("dvi")
                if len(queue) >= dut.LATENCY:
                    assert tuple(ctx.get(Value.cast(getattr(dut.o, field))) for field in
                                 ("x", "y", "de", "hsync", "vsync", "pixel")) == queue.popleft()
            await ctx.tick("dvi")
            assert ctx.get(dut.o.pixel.as_value()) == queue.popleft()[-1]

    sim.add_testbench(bench)
    sim.run()


def test_sprite_contract_rejects_unbounded_or_malformed_atlases():
    for kwargs in ({"slots": 5}, {"width": 65}, {"height": 0}):
        with pytest.raises(ValueError):
            ScanlineSprites([[0] * 33], **kwargs)
    with pytest.raises(ValueError):
        ScanlineSprites([[1 << 33] * 33])
