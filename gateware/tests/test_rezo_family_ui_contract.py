"""UI behavior shared by two or more REZO-family products."""

import pytest
from amaranth.sim import Simulator

from rezo_ui_support import click, fast_click_ui, turn
from top.rezo.rezo_variant import RezoCore, RezoHardwareUI
from top.rezo.strezo_variant import RezoCore as StrezoCore
from top.rezo.strezo_variant import RezoHardwareUI as StrezoHardwareUI
from top.rezo.top import RezoCore as RezomoCore
from top.rezo.top import RezoHardwareUI as RezomoHardwareUI


REZO_AND_REZOMO = (
    pytest.param(RezoCore, RezoHardwareUI, id="rezo"),
    pytest.param(RezomoCore, RezomoHardwareUI, id="rezomo"),
)
FAMILY_UI = REZO_AND_REZOMO + (
    pytest.param(StrezoCore, StrezoHardwareUI, id="strezo"),
)
REZO_AND_REZOMO_UI = (
    pytest.param(RezoHardwareUI, id="rezo"),
    pytest.param(RezomoHardwareUI, id="rezomo"),
)
FAMILY_CORES = (
    pytest.param(RezoCore, id="rezo"),
    pytest.param(RezomoCore, id="rezomo"),
    pytest.param(StrezoCore, id="strezo"),
)


@pytest.mark.parametrize("ui_type", REZO_AND_REZOMO_UI)
def test_ui_shared_feedback_toggle_path(ui_type):
    dut = fast_click_ui(ui_type)()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 0)
        endpoint = await turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 1
        await click(ctx, dut)

        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK_SEND_BASE
        await click(ctx, dut)
        assert ctx.get(dut.feedback_sends[0]) == 0
        assert all(ctx.get(dut.feedback_sends[n]) == 1 for n in range(1, 10))

        for _ in range(9):
            endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK_SEND_BASE + 9
        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK
        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_LIMIT_KNEE

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("ui_type", REZO_AND_REZOMO_UI)
def test_ui_advanced_palette_selection_wraps(ui_type):
    dut = fast_click_ui(ui_type)()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 5
        await click(ctx, dut)

        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_PALETTE
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.palette) == 1
        endpoint = await turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.palette) == 0
        endpoint = await turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.palette) == 4

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("core_type, ui_type", FAMILY_UI)
def test_ui_band_page_layout_toggle_and_transactional_user_edit(core_type,
                                                                ui_type):
    dut = fast_click_ui(ui_type)()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 6
        await click(ctx, dut)

        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_LAYOUT
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.frequency_layout) == 1
        await click(ctx, dut)
        for _ in range(core_type.N_BANDS + 1):
            await ctx.tick()
        assert ctx.get(dut.frequency_layout) == 2
        percept = [core_type.frequency_index(f)
                   for f in core_type.PERCEPT_FREQS_HZ]
        assert [ctx.get(dut.band_frequencies[n]) for n in range(10)] == percept

        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_ENABLE_BASE
        await click(ctx, dut)
        assert ctx.get(dut.band_enables[0]) == 0

        for _ in range(10):
            endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_FREQ_BASE
        old_frequency = ctx.get(dut.band_frequencies[0])
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.band_frequencies[0]) == old_frequency
        await click(ctx, dut)
        for _ in range(core_type.N_BANDS + 1):
            await ctx.tick()
        assert ctx.get(dut.frequency_layout) == 3
        assert ctx.get(dut.band_frequencies[0]) == old_frequency + 1
        assert [ctx.get(dut.band_frequencies[n])
                for n in range(1, 10)] == percept[1:]

        endpoint = await turn(ctx, dut, endpoint, 0)
        for _ in range(10):
            endpoint = await turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_LAYOUT
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 1)
        await click(ctx, dut)
        for _ in range(core_type.N_BANDS + 1):
            await ctx.tick()
        legacy = [core_type.frequency_index(f)
                  for f in core_type.LEGACY_FREQS_HZ]
        assert [ctx.get(dut.band_frequencies[n]) for n in range(10)] == legacy
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 0)
        await click(ctx, dut)
        for _ in range(core_type.N_BANDS + 1):
            await ctx.tick()
        assert ctx.get(dut.frequency_layout) == core_type.LAYOUT_USER
        assert [ctx.get(dut.band_frequencies[n]) for n in range(10)] == legacy

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("ui_type", REZO_AND_REZOMO_UI)
def test_ui_disabled_bank_controls_do_not_change_stored_values(ui_type):
    dut = fast_click_ui(ui_type)()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 1)
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 1)
        endpoint = await turn(ctx, dut, endpoint, 1)
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 1)
        await click(ctx, dut)
        assert ctx.get(dut.band_enables[0]) == 0
        assert ctx.get(dut.band_enables[1]) == 0

        endpoint = await turn(ctx, dut, endpoint, 0)
        endpoint = await turn(ctx, dut, endpoint, 0)
        endpoint = await turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_PAGE
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 0
        await click(ctx, dut)

        endpoint = await turn(ctx, dut, endpoint, 1)
        endpoint = await turn(ctx, dut, endpoint, 1)
        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_BASE
        old_level = ctx.get(dut.levels[0])
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.levels[0]) == old_level

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("core_type", FAMILY_CORES)
def test_frequency_grid_preserves_factory_centers_and_adds_fine_steps(
        core_type):
    assert len(core_type.COARSE_FREQUENCIES_HZ) == 29
    assert len(core_type.FREQUENCIES_HZ) == 116
    for coarse_index, frequency in enumerate(core_type.COARSE_FREQUENCIES_HZ):
        fine_index = coarse_index << core_type.FREQ_FINE_WIDTH
        assert core_type.FREQUENCIES_HZ[fine_index] == frequency
        assert core_type.frequency_index(frequency) == fine_index
    assert all(a <= b for a, b in zip(
        core_type.FREQUENCIES_HZ, core_type.FREQUENCIES_HZ[1:]))


@pytest.mark.parametrize("ui_type", REZO_AND_REZOMO_UI)
def test_ui_save_default_click_requests_once(ui_type):
    dut = fast_click_ui(ui_type)()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        ctx.set(dut.save_default_available, 1)
        await click(ctx, dut)
        endpoint = await turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 5
        await click(ctx, dut)

        endpoint = await turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_SAVE_DEFAULT
        saw_request = False
        ctx.set(dut.button, 1)
        for _ in range(5):
            await ctx.tick()
            saw_request |= bool(ctx.get(dut.save_default_request))
        ctx.set(dut.button, 0)
        for _ in range(5):
            await ctx.tick()
            saw_request |= bool(ctx.get(dut.save_default_request))
        assert saw_request
        assert ctx.get(dut.editing) == 0

    sim.add_testbench(bench)
    sim.run()
