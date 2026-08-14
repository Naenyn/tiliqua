from amaranth.sim import Simulator

from top.rezo.strezo_variant import RezoCore, RezoTileDisplay


def _render_samples(*, h_active=1280, rotate_left=False, points=(), page=0,
                    input_gains=(), input_modes=(), cv_targets=(),
                    band_enables=(), feedback_sends=()):
    """Render settled pixels from STREZO's upright native canvas."""
    dut = RezoTileDisplay(
        h_active=h_active,
        rotate_left=rotate_left,
        compact_layout=True,
    )
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, page)
        for index, value in enumerate(input_gains):
            ctx.set(dut.input_gains[index], value)
        for index, value in enumerate(input_modes):
            ctx.set(dut.input_modes[index], value)
        for index, value in enumerate(cv_targets):
            ctx.set(dut.cv_targets[index], value)
        for index, value in enumerate(band_enables):
            ctx.set(dut.band_enables[index], value)
        for index, value in enumerate(feedback_sends):
            ctx.set(dut.feedback_sends[index], value)
        ctx.set(dut.de, 1)
        for _ in range(320):
            await ctx.tick("dvi")
        for panel_x, panel_y in points:
            if rotate_left:
                physical_x = 719 - panel_y
                physical_y = panel_x
            else:
                physical_x = dut.x_offset + panel_x
                physical_y = panel_y
            ctx.set(dut.x, physical_x)
            ctx.set(dut.y, physical_y)
            for _ in range(12):
                await ctx.tick("dvi")
            samples.append((ctx.get(dut.r), ctx.get(dut.g), ctx.get(dut.b)))

    sim.add_testbench(bench)
    sim.run()
    return samples


def test_native_canvas_uses_the_508_pixel_safe_square():
    points = ((106, 106), (613, 613), (105, 300), (614, 300))
    line = RezoTileDisplay.PALETTE["line"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(points=points) == [
        (line, line, line),
        (line, line, line),
        (blank, blank, blank),
        (blank, blank, blank),
    ]


def test_every_interactive_page_is_blank_beyond_the_safe_square():
    points = ((100, 300), (620, 300), (300, 100), (300, 620))
    blank = RezoTileDisplay.PALETTE["blank"]
    for page in range(8):
        assert _render_samples(points=points, page=page) == [
            (blank, blank, blank),
        ] * len(points)


def test_standard_and_circular_targets_render_identical_native_pixels():
    points = (
        (106, 106), (120, 130), (140, 283),
        (320, 424), (560, 544), (613, 613),
    )
    preview = _render_samples(points=points, page=6, band_enables=(1,))
    circular = _render_samples(
        h_active=720,
        rotate_left=True,
        points=points,
        page=6,
        band_enables=(1,),
    )
    assert circular == preview


def test_input_audio_fill_remains_inside_its_native_value_lane():
    control = RezoTileDisplay.PALETTE["control"]
    panel = RezoTileDisplay.PALETTE["panel"]
    pixels = _render_samples(
        page=2,
        input_gains=(255,),
        input_modes=(RezoCore.INPUT_MODE_LEFT,),
        points=((557, 257), (574, 257)),
    )
    assert pixels == [
        (control, control, control),
        (panel, panel, panel),
    ]


def test_cross_feedback_tracks_end_before_the_safe_square_edge():
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=7,
        points=((559, 550), (560, 550), (559, 582), (560, 582)),
    ) == [
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
    ]
