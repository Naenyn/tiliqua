"""Cross-variant contract tests for REZO-family encoder acceleration."""

import pytest
from amaranth.sim import Simulator

from top.rezo.rezo_variant import RezoHardwareUI as RezoUI
from top.rezo.strezo_variant import RezoHardwareUI as StrezoUI
from top.rezo.top import RezoHardwareUI as RezomoUI


def _fast_click_ui(ui_class):
    return type(
        f"FastClick{ui_class.__module__.split('.')[-1]}UI",
        (ui_class,),
        {"CLICK_LOCKOUT_CYCLES": 1},
    )


async def _hold(ctx, signal, value, cycles=4):
    ctx.set(signal, value)
    for _ in range(cycles):
        await ctx.tick()


async def _click(ctx, dut):
    await _hold(ctx, dut.button, 1, 5)
    await _hold(ctx, dut.button, 0, 5)


async def _turn(ctx, dut, endpoint, direction):
    if direction == 1:
        states = (0b10, 0b11) if endpoint == 0b00 else (0b01, 0b00)
    else:
        states = (0b01, 0b11) if endpoint == 0b00 else (0b10, 0b00)
    for state in states:
        ctx.set(dut.enc_i, state & 1)
        ctx.set(dut.enc_q, (state >> 1) & 1)
        for _ in range(4):
            await ctx.tick()
    for _ in range(8):
        await ctx.tick()
    return states[-1]


@pytest.mark.parametrize("ui_class", (RezoUI, RezomoUI, StrezoUI))
def test_continuous_faders_share_progressive_acceleration(ui_class):
    """Every variant applies 1x, 2x, 3x, 4x and resets on reversal."""
    dut = _fast_click_ui(ui_class)()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # BANK -> INPUT is two PAGE detents in every family variant.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 2
        await _click(ctx, dut)

        # PAGE -> IN0 MODE -> IN0 VALUE.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_INPUT_BASE + 1
        await _click(ctx, dut)

        start = ctx.get(dut.input_gains[0])
        expected_deltas = (256, 768, 1536, 2560)
        for expected in expected_deltas:
            endpoint = await _turn(ctx, dut, endpoint, 1)
            assert ctx.get(dut.input_gains[0]) == start + expected

        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.input_gains[0]) == start + 2304

    sim.add_testbench(bench)
    sim.run()
