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
