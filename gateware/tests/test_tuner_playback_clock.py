"""Playback diagnostics must work on the compact CPU without mcycle."""
from pathlib import Path

from amaranth.sim import Simulator
from luna_soc.gateware.core import timer


def test_playback_uses_supported_bus_timer_not_cpu_performance_csrs():
    root = Path(__file__).resolve().parents[1]
    main = (root / "src/top/tuner/fw/src/main.rs").read_text()
    top = (root / "src/top/tuner/top.py").read_text()
    assert "riscv::register::mcycle" not in main
    assert "riscv::register::cycle" not in main
    assert "PLAYBACK_TIMER.counter().read()" in main
    assert "PLAYBACK_TIMER.reload().write" in main
    assert 'name="playback_timer"' in top


def test_free_running_timer_inverted_count_wraps_without_discontinuity():
    # Short width exercises the same periodic reload as the 32-bit hardware.
    dut = timer.Peripheral(width=4)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        async def write(register, value):
            address = next(r.start for r in dut.bus.memory_map.all_resources()
                           if r.resource is register)
            ctx.set(dut.bus.addr, address)
            ctx.set(dut.bus.w_data, value)
            ctx.set(dut.bus.w_stb, 1)
            await ctx.tick()
            ctx.set(dut.bus.w_stb, 0)
            await ctx.tick().repeat(2)

        await write(dut._reload, 15)
        await write(dut._mode, 1)
        await write(dut._enable, 1)
        previous = (~ctx.get(dut._counter.f.value.r_data)) & 15
        for _ in range(40):
            await ctx.tick()
            current = (~ctx.get(dut._counter.f.value.r_data)) & 15
            assert (current - previous) & 15 == 1
            previous = current

    sim.add_testbench(bench)
    sim.run()
