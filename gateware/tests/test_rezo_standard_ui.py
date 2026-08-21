from amaranth.sim import Simulator

from rezo_ui_support import click as _click
from rezo_ui_support import fast_click_ui
from rezo_ui_support import turn as _turn
from top.rezo.rezo_variant import RezoCore, RezoHardwareUI


FastClickRezoUI = fast_click_ui(RezoHardwareUI)


def test_ui_shared_matrix_and_output_edit_paths():
    """Dynamic edit decoders update only the selected matrix/send cells."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # BANK navigation is PAGE -> PRESET -> MODE.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_PRESET
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_MODE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.filter_mode) == 1
        await _click(ctx, dut)

        # FILTER navigation is PAGE -> TYPE -> MODE, while BANK remains
        # PAGE -> PRESET -> MODE. Walk the FILTER header in both directions.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_FILTER_TYPE
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_PAGE
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FILTER_TYPE
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_MODE
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_FILTER_TYPE
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_PAGE

        # Enter page edit and move FILTER -> BANDS -> INPUT -> MATRIX.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 6
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 2
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 7
        await _click(ctx, dut)

        # Select and edit the first modulation-matrix cell.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FILTER_CV_BASE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        # FILTER-CV writes are intentionally registered to keep the 15-way
        # edit decoder off the 60 MHz navigation critical path.
        await ctx.tick()
        assert ctx.get(dut.filter_cv_matrix[0]) > 0
        assert all(ctx.get(dut.filter_cv_matrix[n]) == 0 for n in range(1, 15))

    sim.add_testbench(bench)
    sim.run()
def test_ui_state_scan_round_trips_independent_mode_values():
    """The versioned scan port restores all representative state families."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    writes = (
        (dut.STATE_LEVELS_BASE + 2, 0xE420),
        (dut.STATE_DRIVES, 0x5612),
        (dut.STATE_CAP_FLAGS, 0x2B70),
        (dut.STATE_FILTER_CV_BASE + 7, 0x00F1),
        (dut.STATE_INPUT_GAIN_BASE + 3, 0xCCCC),
        (dut.STATE_CV_DEPTH_BASE + 1, 0x7FE0),
        (dut.STATE_INPUT_CONFIG, 0x9A56),
        (dut.STATE_BANK_GROUP_BASE + 1, 0x3210),
        (dut.STATE_FEEDBACK_PRESET, 0x73A5),
        # The high byte of the final output word is FILTER's independent
        # feedback amount; its low byte remains the tail of the send matrix.
        (dut.STATE_OUTPUT_BASE + 12, 0x5AAD),
    )

    async def bench(ctx):
        state = [0] * dut.STATE_WORDS_V2
        for address, value in writes:
            state[address] = value
        saved_frequencies = tuple((n << RezoCore.FREQ_FINE_WIDTH) | (n & 3)
                                  for n in range(RezoCore.N_BANDS))
        band_config = 0
        for n, frequency in enumerate(saved_frequencies):
            band_config |= (frequency >> RezoCore.FREQ_FINE_WIDTH) << (
                n * RezoCore.FREQ_COARSE_WIDTH)
        saved_enables = 0b1011010011
        band_config |= saved_enables << 50
        band_config |= RezoCore.LAYOUT_USER << 60
        band_config |= (saved_frequencies[9] & 3) << 62
        for n in range(4):
            state[dut.STATE_BAND_CONFIG_BASE + n] = \
                (band_config >> (16 * n)) & 0xffff
        state[dut.STATE_CAP_FLAGS] |= (saved_frequencies[0] & 3) << 14
        for n in range(1, 5):
            state[dut.STATE_FILTER_CV_BASE + 7] |= \
                (saved_frequencies[n] & 3) << (8 + (n - 1) * 2)
        for n in range(5, 9):
            state[dut.STATE_BANK_GROUP_BASE + 2] |= \
                (saved_frequencies[n] & 3) << (8 + (n - 5) * 2)

        # LOAD shifts a complete validated record into the circular stream.
        ctx.set(dut.state_shift_load, 1)
        ctx.set(dut.state_shift_enable, 1)
        for value in state:
            ctx.set(dut.state_write_data, value)
            await ctx.tick()
        ctx.set(dut.state_shift_enable, 0)
        ctx.set(dut.state_shift_load, 0)
        await ctx.tick()

        # SAVE presents words in order and rotates the entire state back to
        # its starting position after exactly STATE_WORDS_V2 cycles.
        captured = []
        ctx.set(dut.state_shift_enable, 1)
        for _ in state:
            captured.append(ctx.get(dut.state_read_data))
            await ctx.tick()
        ctx.set(dut.state_shift_enable, 0)
        assert captured == state

        # CAP_FLAGS selected FILTER mode, so the separately stored filter
        # drive must now be the active drive. Band 5 restores signed 0xE400.
        assert ctx.get(dut.filter_mode) == 1
        assert ctx.get(dut.drive) == 0x5600
        assert ctx.get(dut.feedback) == 0x5A00
        assert ctx.get(dut.levels[5]) == -0x1C00
        assert ctx.get(dut.input_gains[3]) == 0xCCCC
        assert ctx.get(dut.palette) == 3
        assert ctx.get(dut.frequency_layout) == RezoCore.LAYOUT_USER
        assert tuple(ctx.get(dut.band_frequencies[n]) for n in range(10)) == \
            saved_frequencies
        assert tuple(ctx.get(dut.band_enables[n]) for n in range(10)) == \
            tuple((saved_enables >> n) & 1 for n in range(10))

    sim.add_testbench(bench)
    sim.run()
