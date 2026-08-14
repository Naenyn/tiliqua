from amaranth.sim import Simulator

from top.rezo.top import RezoCore, RezoHardwareUI


class FastClickRezoUI(RezoHardwareUI):
    """Keep production debounce semantics without millions of test cycles."""

    CLICK_LOCKOUT_CYCLES = 1


async def _hold(ctx, signal, value, cycles=4):
    ctx.set(signal, value)
    for _ in range(cycles):
        await ctx.tick()


async def _click(ctx, dut):
    await _hold(ctx, dut.button, 1, 5)
    await _hold(ctx, dut.button, 0, 5)


async def _turn(ctx, dut, endpoint, direction):
    """Emit one complete detent and return its new 00/11 endpoint."""
    if direction == 1:
        states = (0b10, 0b11) if endpoint == 0b00 else (0b01, 0b00)
    else:
        states = (0b01, 0b11) if endpoint == 0b00 else (0b10, 0b00)
    for state in states:
        ctx.set(dut.enc_i, state & 1)
        ctx.set(dut.enc_q, (state >> 1) & 1)
        for _ in range(4):
            await ctx.tick()
    return states[-1]


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

        # Return to PAGE, enter page edit, and move FILTER -> MATRIX.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_PAGE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 2
        await _click(ctx, dut)

        # Select and edit the first modulation-matrix cell.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FILTER_CV_BASE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.filter_cv_matrix[0]) > 0
        assert all(ctx.get(dut.filter_cv_matrix[n]) == 0 for n in range(1, 15))

    sim.add_testbench(bench)
    sim.run()

def test_ui_shared_feedback_toggle_path():
    """FEEDBACK navigates top-to-bottom and toggles only the selected band."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> ADVANCED -> FEEDBACK.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 1
        await _click(ctx, dut)

        # Forward entry reaches the band row before the lower safety faders.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK_SEND_BASE
        await _click(ctx, dut)
        assert ctx.get(dut.feedback_sends[0]) == 0
        assert all(ctx.get(dut.feedback_sends[n]) == 1 for n in range(1, 10))

        for _ in range(9):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK_SEND_BASE + 9
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_LIMIT_KNEE

    sim.add_testbench(bench)
    sim.run()


def test_ui_advanced_palette_selection_wraps():
    """OPTIONS exposes a palette control with five wrapping themes."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> OPTIONS.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 5
        await _click(ctx, dut)

        # Select PALETTE, edit it, and exercise both ends of the wrap.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_PALETTE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.palette) == 1
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.palette) == 0
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.palette) == 4

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
        (dut.STATE_OUTPUT_BASE + 12, 0x00AD),
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


def test_ui_band_page_layout_toggle_and_transactional_user_edit():
    """BANDS applies layouts, toggles masks, and commits edits into USER."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> BANDS.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 6
        await _click(ctx, dut)

        # Select LAYOUT, preview PERCEPT, then commit it.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_LAYOUT
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.frequency_layout) == 1  # preview is not live
        await _click(ctx, dut)
        for _ in range(RezoCore.N_BANDS + 1):
            await ctx.tick()
        assert ctx.get(dut.frequency_layout) == 2
        percept = [RezoCore.frequency_index(f) for f in RezoCore.PERCEPT_FREQS_HZ]
        assert [ctx.get(dut.band_frequencies[n]) for n in range(10)] == percept

        # First enable target toggles immediately and retains its band value.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_ENABLE_BASE
        await _click(ctx, dut)
        assert ctx.get(dut.band_enables[0]) == 0

        # Walk across the enable row to frequency 0. Editing previews without
        # touching DSP state; commit snapshots PERCEPT into USER and changes
        # only the selected center.
        for _ in range(10):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_FREQ_BASE
        old_frequency = ctx.get(dut.band_frequencies[0])
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.band_frequencies[0]) == old_frequency
        await _click(ctx, dut)
        for _ in range(RezoCore.N_BANDS + 1):
            await ctx.tick()
        assert ctx.get(dut.frequency_layout) == 3
        assert ctx.get(dut.band_frequencies[0]) == old_frequency + 1
        assert [ctx.get(dut.band_frequencies[n]) for n in range(1, 10)] == percept[1:]

        # USER is a working state, not a second recalled preset. Select a
        # factory layout, then select USER again: it snapshots that factory
        # vector rather than recalling the previous manual edit.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        for _ in range(10):
            endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_LAYOUT
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)  # USER wraps to LEGACY
        await _click(ctx, dut)
        for _ in range(RezoCore.N_BANDS + 1):
            await ctx.tick()
        legacy = [RezoCore.frequency_index(f) for f in RezoCore.LEGACY_FREQS_HZ]
        assert [ctx.get(dut.band_frequencies[n]) for n in range(10)] == legacy
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)  # LEGACY wraps to USER
        await _click(ctx, dut)
        for _ in range(RezoCore.N_BANDS + 1):
            await ctx.tick()
        assert ctx.get(dut.frequency_layout) == RezoCore.LAYOUT_USER
        assert [ctx.get(dut.band_frequencies[n]) for n in range(10)] == legacy

    sim.add_testbench(bench)
    sim.run()


def test_ui_disabled_bank_controls_do_not_change_stored_values():
    """Muted bands remain configurable on BANDS but are inert on BANK."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # Enter BANDS and disable the first two bands.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)  # layout
        endpoint = await _turn(ctx, dut, endpoint, 1)  # enable 0
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)  # enable 1
        await _click(ctx, dut)
        assert ctx.get(dut.band_enables[0]) == 0
        assert ctx.get(dut.band_enables[1]) == 0

        # Navigate back through BANDS controls to PAGE, then return to BANK.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_PAGE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 0
        await _click(ctx, dut)

        # PRESET -> MODE -> band 0. It may be traversed while navigating, but
        # entering EDIT and turning cannot alter its hidden stored level.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_BASE
        old_level = ctx.get(dut.levels[0])
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.levels[0]) == old_level

    sim.add_testbench(bench)
    sim.run()


def test_frequency_grid_preserves_factory_centers_and_adds_fine_steps():
    """Every old five-bit index maps to its exact center at fine position zero."""
    assert len(RezoCore.COARSE_FREQUENCIES_HZ) == 29
    assert len(RezoCore.FREQUENCIES_HZ) == 116
    for coarse_index, frequency in enumerate(RezoCore.COARSE_FREQUENCIES_HZ):
        fine_index = coarse_index << RezoCore.FREQ_FINE_WIDTH
        assert RezoCore.FREQUENCIES_HZ[fine_index] == frequency
        assert RezoCore.frequency_index(frequency) == fine_index
    assert all(a <= b for a, b in zip(
        RezoCore.FREQUENCIES_HZ, RezoCore.FREQUENCIES_HZ[1:]))


def test_ui_save_default_click_requests_once():
    """SAVE DEFAULT emits one request from one explicit encoder click."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        ctx.set(dut.save_default_available, 1)

        # PAGE edit: BANK -> OPTIONS.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 5
        await _click(ctx, dut)

        # Counter-clockwise enters ADVANCED at SAVE DEFAULT directly.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_SAVE_DEFAULT
        # Observe the click's one-cycle request pulse.
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
