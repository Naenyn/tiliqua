from amaranth.sim import Simulator

from top.rezo.top import RezoHardwareUI


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

        # Select MODE, enter edit, and switch BANK -> FILTER.
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
    """The indexed feedback toggle changes exactly the selected band."""
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

        # Counter-direction entry selects the final feedback band.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK_SEND_BASE + 9
        await _click(ctx, dut)
        assert ctx.get(dut.feedback_sends[9]) == 0
        assert all(ctx.get(dut.feedback_sends[n]) == 1 for n in range(9))

    sim.add_testbench(bench)
    sim.run()


def test_ui_advanced_palette_selection_wraps():
    """ADVANCED exposes a palette control with five wrapping themes."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> ADVANCED.
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
        state = [0] * dut.STATE_WORDS_V1
        for address, value in writes:
            state[address] = value

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
        # its starting position after exactly STATE_WORDS_V1 cycles.
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

    sim.add_testbench(bench)
    sim.run()


def test_ui_save_default_click_requests_once():
    """SAVE DEFAULT emits one request from one explicit encoder click."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        ctx.set(dut.save_default_available, 1)

        # PAGE edit: BANK -> ADVANCED.
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
