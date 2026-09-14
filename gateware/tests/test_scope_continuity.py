"""Fast-sweep continuity and burst backpressure regressions."""

from amaranth.sim import Simulator
from tiliqua.raster.scope_capture import ColumnCapture


def capture_columns(spacing, step=80):
    dut = ColumnCapture()
    rows = []
    accepted = []

    async def bench(ctx):
        ctx.set(dut.active, 1)
        ctx.set(dut.plot_x_lo, -200)
        ctx.set(dut.plot_x_hi, 200)
        ctx.set(dut.scale_x, 5)
        for ch in range(4):
            ctx.set(dut.visible[ch], 1)
            ctx.set(dut.scale_y[ch], 3)
        await ctx.tick()
        n = 0
        next_cycle = 0
        for cycle in range(1500):
            valid = n < 30 and cycle >= next_cycle
            ctx.set(dut.sample_valid, valid)
            if valid:
                ctx.set(dut.ramp.as_value(), -1000 + n * 8)
                for ch in range(4):
                    # Opposite slopes and DC offsets catch mixed bundles.
                    value = n * step * (1 if ch % 2 else -1) + ch * 100
                    ctx.set(dut.audio[ch].as_value(), value)
            if valid and ctx.get(dut.sample_ready):
                accepted.append(cycle)
                n += 1
                next_cycle = cycle + spacing
            await ctx.tick()
            if ctx.get(dut.flush_valid):
                word = ctx.get(dut.flush_word)
                def signed12(v):
                    return v - 4096 if v & 2048 else v
                rows.append((ctx.get(dut.flush_col), [
                    (signed12((word >> (25 * ch + 1)) & 4095),
                     signed12((word >> (25 * ch + 13)) & 4095))
                    for ch in range(4)]))
        assert n == 30

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
    return rows, accepted


def test_bursts_preserve_every_column_and_channel():
    spaced, _ = capture_columns(20)
    for spacing in (1, 2, 5, 8):
        burst, accepted = capture_columns(spacing)
        assert burst == spaced
        assert len(burst) == 29
        assert [col for col, _ in burst] == list(range(75, 104))
        # Eight clocks/bundle is ~4.9x the required average throughput.
        assert max(b - a for a, b in zip(accepted, accepted[1:])) <= 8


def test_small_and_large_slopes_have_connected_envelopes():
    for step in (16, 32, 80, 160, 320):
        rows, _ = capture_columns(1, step)
        for (_, before), (_, after) in zip(rows, rows[1:]):
            for (lo0, hi0), (lo1, hi1) in zip(before, after):
                assert max(lo0, lo1) <= min(hi0, hi1)
        # Five-pixel slopes should be connected without duplicating the whole
        # neighboring span in both columns (the older broad-bridge artifact).
        if step == 80:
            assert all(hi - lo <= 6 for _, channels in rows for lo, hi in channels)
