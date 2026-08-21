from amaranth.sim import Simulator

from top.rezo.top import RezoCore, RezoHardwareUI, RezoTileDisplay


def test_clock_main_reuses_bank_view_and_settings_page_is_discrete():
    """CLOCK main is BANK-like; TURING adds discrete loop controls."""
    dut = RezoTileDisplay(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x, panel_y):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, panel_y)
        ctx.set(dut.de, 1)
        for _ in range(8):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.clock_mode, 1)
        ctx.set(dut.levels[0], 0)
        ctx.set(dut.effective_levels[0], 64)
        ctx.set(dut.band_enables[0], 1)

        await sample(ctx, 60, 250)   # captured modulation in band 0
        await sample(ctx, 150, 110)  # shared preset chip

        ctx.set(dut.page, 7)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_CLOCK_ALGORITHM)
        await sample(ctx, 150, 110)  # shared algorithm chip interior
        await sample(ctx, 131, 110)  # selected algorithm outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_SHIFT_DIRECTION)
        await sample(ctx, 200, 240)  # direction chip interior
        await sample(ctx, 60, 250)   # no band pipeline on settings page

        ctx.set(dut.selected, RezoHardwareUI.TARGET_CLOCK_SOURCE)
        await sample(ctx, 200, 320)  # source chip interior
        await sample(ctx, 187, 320)  # selected source outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_CLOCK_RATE)
        await sample(ctx, 200, 400)  # BPM chip interior
        await sample(ctx, 187, 400)  # selected BPM outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_CLOCK_DEPTH)
        ctx.set(dut.clock_depth, 64)
        await sample(ctx, 300, 488)  # filled half of full-width depth slider
        await sample(ctx, 600, 488)  # unfilled half remains panel-colored
        await sample(ctx, 164, 488)  # selected depth outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_DATA_SOURCE)
        await sample(ctx, 520, 240)  # SHIFT DATA chip interior
        await sample(ctx, 507, 240)  # selected DATA outline

        ctx.set(dut.clock_algorithm, RezoCore.CLOCK_ALGORITHM_TURING)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_TURING_CHANGE)
        await sample(ctx, 520, 240)  # mutation chance chip interior
        await sample(ctx, 507, 240)  # selected change outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_TURING_TARGET)
        await sample(ctx, 520, 320)  # BANDS chip interior
        await sample(ctx, 507, 320)  # selected BANDS outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_TURING_LENGTH)
        await sample(ctx, 520, 400)  # ALL length chip interior
        await sample(ctx, 507, 400)  # selected length outline
        ctx.set(dut.turing_target, RezoCore.TURING_TARGET_RANGE)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_TURING_START)
        await sample(ctx, 520, 400)  # RANGE start chip interior
        await sample(ctx, 507, 400)  # selected start outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_TURING_LENGTH)
        await sample(ctx, 520, 480)  # RANGE length chip interior
        await sample(ctx, 507, 480)  # selected length outline

        ctx.set(dut.clock_algorithm, RezoCore.CLOCK_ALGORITHM_WALK)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_CLOCK_SOURCE)
        await sample(ctx, 200, 240)  # read-only RANDOM direction chip
        await sample(ctx, 200, 320)  # source remains in second row
        await sample(ctx, 187, 320)  # selected source outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_CLOCK_RATE)
        await sample(ctx, 200, 400)  # BPM remains in third row
        await sample(ctx, 187, 400)  # selected BPM outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_CLOCK_DEPTH)
        await sample(ctx, 600, 488)  # full-width depth remains fourth row
        await sample(ctx, 164, 488)  # selected depth outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_WALK_STYLE)
        await sample(ctx, 520, 240)  # WALK style chip interior
        await sample(ctx, 507, 240)  # selected style outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_WALK_DRUNK)
        await sample(ctx, 520, 320)  # drunkenness chip interior
        await sample(ctx, 507, 320)  # selected drunkenness outline
        ctx.set(dut.selected, RezoHardwareUI.TARGET_WALK_CHANCE)
        await sample(ctx, 520, 400)  # stumble chance chip interior
        await sample(ctx, 507, 400)  # selected chance outline

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["modulation"],
        palette["panel"],
        palette["panel"],
        palette["selected"],
        palette["panel"],
        palette["background"],
    ] + [
        palette["panel"], palette["selected"]
    ] * 2 + [
        palette["control"], palette["panel"], palette["selected"],
    ] + [
        palette["panel"], palette["selected"]
    ] * 6 + [
        palette["panel"],
    ] + [
        palette["panel"], palette["selected"]
    ] * 6


def test_input_page_draws_post_value_audio_and_raw_bipolar_cv_meters():
    """The one-pixel telemetry line distinguishes audio and CV semantics."""
    dut = RezoTileDisplay(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x, panel_y):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, panel_y)
        ctx.set(dut.de, 1)
        for _ in range(8):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 2)
        ctx.set(dut.input_modes[0], RezoCore.INPUT_MODE_AUDIO)
        ctx.set(dut.input_meters[0], 20)
        ctx.set(dut.input_modes[1], RezoCore.INPUT_MODE_CV)
        ctx.set(dut.input_meters[1], -10)

        await sample(ctx, 400, 259)
        await sample(ctx, 550, 259)
        await sample(ctx, 460, 355)
        await sample(ctx, 520, 355)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["modulation"], palette["background"],
        palette["modulation"], palette["background"],
    ]
