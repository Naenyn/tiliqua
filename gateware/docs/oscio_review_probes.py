"""Diagnostic reproductions for OSCIO_CODE_REVIEW_2026-09-13.md.

Run from gateware with PYTHONPATH=src and the installed Python dependencies.
These report existing defects; they do not assert that broken behavior is correct.
"""

import json
from amaranth import signed
from amaranth.sim import Simulator
from tiliqua.raster.frequency_detector import NativeFrequencyDetector
from tiliqua.raster.scope_capture import ColumnCapture

def capture(spacing):
    dut = ColumnCapture()
    results = []
    async def bench(ctx):
        ctx.set(dut.active, 1)
        ctx.set(dut.plot_x_lo, -200)
        ctx.set(dut.plot_x_hi, 200)
        ctx.set(dut.scale_x, 5)
        for ch in range(4):
            ctx.set(dut.visible[ch], 1)
            ctx.set(dut.scale_y[ch], 3)
        await ctx.tick()
        for cycle in range(20 * spacing + 30):
            n = cycle // spacing
            valid = n < 20 and cycle % spacing == 0
            ctx.set(dut.sample_valid, valid)
            if valid:
                ctx.set(dut.ramp.as_value(), -1000 + n * 32)
                for ch in range(4):
                    ctx.set(dut.audio[ch].as_value(), 100 + n * 10 + ch * 100)
            await ctx.tick()
            if ctx.get(dut.flush_valid):
                word = ctx.get(dut.flush_word)
                def coord(v):
                    return v - 4096 if v & 2048 else v
                results.append([ctx.get(dut.flush_col), [coord((word >> (25*ch+1)) & 4095) for ch in range(4)]])
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
    return results

def rate(fs):
    dut = NativeFrequencyDetector(shape=signed(18), n_channels=1)
    result = {}
    async def bench(ctx):
        period = fs // 20
        for n in range(period * 5):
            ctx.set(dut.sample[0], -16000 if n % period < period // 2 else 16000)
            ctx.set(dut.tick, 1)
            await ctx.tick()
            ctx.set(dut.tick, 0)
            await ctx.tick()
        result.update(period=ctx.get(dut.period[0]), valid=ctx.get(dut.valid[0]), rapid=ctx.get(dut.rapid[0]))
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
    return result

if __name__ == "__main__":
    spaced, burst = capture(20), capture(5)
    print(json.dumps({
        "capture_spaced_first": spaced[0],
        "capture_burst_first": burst[0],
        "capture_spaced_columns": len(spaced),
        "capture_burst_columns": len(burst),
        "20Hz_at_48k": rate(48000),
        "20Hz_at_192k": rate(192000),
    }, indent=2))
