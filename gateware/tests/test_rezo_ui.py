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
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK
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


def test_ui_state_scan_preserves_v3_bank_and_clock_words():
    """BANK and CLOCK configuration round-trip through the V3 scan stream."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    writes = (
        (dut.STATE_LEVELS_BASE + 2, 0xE420),
        (dut.STATE_DRIVES, 0x5612),
        (dut.STATE_CAP_FLAGS, 0x2B70),
        (dut.STATE_LEGACY_CV_BASE + 7, 0x00F1),
        (dut.STATE_INPUT_GAIN_BASE + 3, 0xCCCC),
        (dut.STATE_CV_DEPTH_BASE + 1, 0x7FE0),
        (dut.STATE_INPUT_CONFIG, 0x9A56),
        (dut.STATE_BANK_GROUP_BASE + 1, 0x3210),
        (dut.STATE_FEEDBACK_PRESET, 0x73A5),
        (dut.STATE_OUTPUT_BASE + 12, 0x00AD),
    )

    async def bench(ctx):
        state = [0] * dut.STATE_WORDS_V3
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
            state[dut.STATE_LEGACY_CV_BASE + 7] |= \
                (saved_frequencies[n] & 3) << (8 + (n - 1) * 2)
        for n in range(5, 9):
            state[dut.STATE_BANK_GROUP_BASE + 2] |= \
                (saved_frequencies[n] & 3) << (8 + (n - 5) * 2)

        saved_targets = (2, 8, 9, 10)
        input_config = 0b1110
        for n, target in enumerate(saved_targets):
            input_config |= (target & 7) << (4 + n * 3)
        state[dut.STATE_INPUT_CONFIG] = input_config
        clock_fields = (
            (1, 1),
            (RezoCore.CLOCK_ALGORITHM_TURING, 2),
            (RezoCore.SHIFT_BACKWARD, 2),
            (7, 4),
            (5, 3),
            (RezoCore.CLOCK_SOURCE_INTERNAL, 2),
            (173 & 7, 3),
            (73, 8),
            (RezoCore.TURING_TARGET_RANGE, 1),
            (3, 4),
            (RezoCore.DATA_SOURCE_RANDOM, 2),
            (sum(((target >> 3) & 1) << n
                 for n, target in enumerate(saved_targets)), 4),
            (4, 3),
            (RezoCore.WALK_STYLE_HEAD, 1),
            (3, 2),
            (5, 3),
        )
        clock_config = 0
        shift = 0
        for value, width in clock_fields:
            clock_config |= value << shift
            shift += width
        assert shift == 45
        clock_config |= (173 >> 3) << shift
        for n in range(4):
            state[dut.STATE_CLOCK_CONFIG_BASE + n] = \
                (clock_config >> (16 * n)) & 0xffff

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
        # its starting position after exactly STATE_WORDS_V3 cycles.
        captured = []
        ctx.set(dut.state_shift_enable, 1)
        for _ in state:
            captured.append(ctx.get(dut.state_read_data))
            await ctx.tick()
        ctx.set(dut.state_shift_enable, 0)
        assert captured == state

        # The removed FILTER fields remain reserved in the version-2 stream,
        # while BANK drive is always active. Band 5 restores signed 0xE400.
        assert ctx.get(dut.drive) == 0x1200
        assert ctx.get(dut.levels[5]) == -0x1C00
        assert ctx.get(dut.input_gains[3]) == 0xCCCC
        assert ctx.get(dut.palette) == 3
        assert ctx.get(dut.frequency_layout) == RezoCore.LAYOUT_USER
        assert tuple(ctx.get(dut.band_frequencies[n]) for n in range(10)) == \
            saved_frequencies
        assert tuple(ctx.get(dut.band_enables[n]) for n in range(10)) == \
            tuple((saved_enables >> n) & 1 for n in range(10))

        assert ctx.get(dut.clock_mode) == 1
        assert ctx.get(dut.clock_algorithm) == RezoCore.CLOCK_ALGORITHM_TURING
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_BACKWARD
        assert ctx.get(dut.turing_length) == 7
        assert ctx.get(dut.turing_change_index) == 5
        assert ctx.get(dut.clock_source) == RezoCore.CLOCK_SOURCE_INTERNAL
        assert ctx.get(dut.internal_clock_rate) == 173
        assert ctx.get(dut.clock_depth) == 73
        assert ctx.get(dut.turing_target) == RezoCore.TURING_TARGET_RANGE
        assert ctx.get(dut.turing_start) == 3
        assert ctx.get(dut.data_source) == RezoCore.DATA_SOURCE_RANDOM
        assert ctx.get(dut.walk_step_index) == 4
        assert ctx.get(dut.walk_style) == RezoCore.WALK_STYLE_HEAD
        assert ctx.get(dut.walk_drunk) == 3
        assert ctx.get(dut.walk_chance_index) == 5
        assert tuple(ctx.get(dut.cv_targets[n]) for n in range(4)) == \
            saved_targets

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


def test_ui_clock_mode_defaults_and_control_navigation():
    """CLOCK exposes source, tempo, direction, and TURING loop controls."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        assert ctx.get(dut.clock_mode) == 0
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_FORWARD
        assert ctx.get(dut.clock_source) == RezoCore.CLOCK_SOURCE_AUTO
        assert ctx.get(dut.internal_clock_rate) == 120
        assert tuple(ctx.get(dut.cv_targets[n]) for n in range(4)) == (
            RezoCore.CV_TARGET_RESONANCE,
            RezoCore.CV_TARGET_RESET,
            RezoCore.CV_TARGET_DATA,
            RezoCore.CV_TARGET_CLOCK,
        )

        # PAGE -> PRESET -> MODE, then edit BANK into CLOCK.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_PRESET
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_MODE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.clock_mode) == 1
        await _click(ctx, dut)

        # CLOCK main retains BANK's preset, ten bands, and three sliders. The
        # next control after MODE is the first band.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_BASE

        # Return to PAGE, then CLOCK's forward page order inserts the new
        # settings page before BANDS.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_PAGE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 7
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CLOCK_ALGORITHM
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.clock_algorithm) == RezoCore.CLOCK_ALGORITHM_ROTATE
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_FORWARD
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_SHIFT_DIRECTION
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_BACKWARD
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_FORWARD

        # Return to MODE and advance ROTATE -> TURING. TURING adds PING PONG
        # to FWD/REV and exposes its loop controls after the shared column.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_CLOCK_ALGORITHM
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.clock_algorithm) == RezoCore.CLOCK_ALGORITHM_TURING
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_FORWARD
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_SHIFT_DIRECTION
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_BACKWARD
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_PING_PONG
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_FORWARD
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CLOCK_SOURCE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.clock_source) == RezoCore.CLOCK_SOURCE_INTERNAL
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CLOCK_RATE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.internal_clock_rate) == 121
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.internal_clock_rate) == 123
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CLOCK_DEPTH
        assert ctx.get(dut.clock_depth) == 128
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.clock_depth) == 127
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_TURING_CHANGE
        assert ctx.get(dut.turing_change_index) == 3
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.turing_change_index) == 4
        assert ctx.get(dut.turing_change) == 64
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_TURING_TARGET
        assert ctx.get(dut.turing_target) == RezoCore.TURING_TARGET_ALL
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.turing_target) == RezoCore.TURING_TARGET_RANGE
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_TURING_START
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.turing_start) == 1
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_TURING_LENGTH
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.turing_length) == 8
        assert ctx.get(dut.turing_start) == 1

        # LOCK is a routable gate role beyond the legacy version-2 targets.
        assert RezoCore.CV_TARGET_MAX == RezoCore.CV_TARGET_LOCK

    sim.add_testbench(bench)
    sim.run()


def test_ui_shift_data_source_navigation_and_choices():
    """SHIFT exposes CV, RAND, and AUTO after the shared DEPTH control."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        assert ctx.get(dut.data_source) == RezoCore.DATA_SOURCE_CV

        # Enter CLOCK mode, return to PAGE, and open CLOCK settings.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 7
        await _click(ctx, dut)

        for expected in (
                dut.TARGET_CLOCK_ALGORITHM,
                dut.TARGET_SHIFT_DIRECTION,
                dut.TARGET_CLOCK_SOURCE,
                dut.TARGET_CLOCK_RATE,
                dut.TARGET_CLOCK_DEPTH,
                dut.TARGET_DATA_SOURCE):
            endpoint = await _turn(ctx, dut, endpoint, 1)
            assert ctx.get(dut.selected) == expected

        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.data_source) == RezoCore.DATA_SOURCE_RANDOM
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.data_source) == RezoCore.DATA_SOURCE_AUTO
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.data_source) == RezoCore.DATA_SOURCE_CV

    sim.add_testbench(bench)
    sim.run()


def test_ui_walk_skips_direction_and_starts_with_clock_source():
    """WALK shows RANDOM direction but skips its read-only row."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # Enter CLOCK mode and open its settings page.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CLOCK_ALGORITHM
        await _click(ctx, dut)
        # Reverse from SHIFT wraps directly to WALK.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.clock_algorithm) == RezoCore.CLOCK_ALGORITHM_WALK
        await _click(ctx, dut)

        # DIRECTION is read-only RANDOM in WALK, so navigation skips it. Its
        # legacy saved step value remains fixed for state-format compatibility.
        assert ctx.get(dut.walk_step_index) == RezoCore.WALK_STEP_DEFAULT
        assert ctx.get(dut.shift_direction) == RezoCore.SHIFT_FORWARD

        # WALK adds STYLE and DRUNK after the shared source/rate/depth rows.
        for expected in (
                dut.TARGET_CLOCK_SOURCE,
                dut.TARGET_CLOCK_RATE,
                dut.TARGET_CLOCK_DEPTH,
                dut.TARGET_WALK_STYLE):
            endpoint = await _turn(ctx, dut, endpoint, 1)
            assert ctx.get(dut.selected) == expected
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.walk_style) == RezoCore.WALK_STYLE_HEAD
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_WALK_DRUNK
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.walk_drunk) == 1
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_WALK_CHANCE
        assert ctx.get(dut.walk_chance_index) == RezoCore.WALK_CHANCE_DEFAULT
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.walk_chance_index) == \
            RezoCore.WALK_CHANCE_DEFAULT + 1

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
