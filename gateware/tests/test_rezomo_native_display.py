from amaranth.sim import Simulator

from top.rezo.top import RezoCore, RezoTileDisplay


def _render_samples(*, h_active=1280, rotate_left=False, points=(), page=0,
                    clock_algorithm=RezoCore.CLOCK_ALGORITHM_SHIFT,
                    turing_target=RezoCore.TURING_TARGET_ALL,
                    band_enables=(), feedback_sends=(), input_gains=()):
    """Render settled pixels from the native REZOMO coordinate space."""
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
        ctx.set(dut.clock_algorithm, clock_algorithm)
        ctx.set(dut.turing_target, turing_target)
        for index, value in enumerate(band_enables):
            ctx.set(dut.band_enables[index], value)
        for index, value in enumerate(feedback_sends):
            ctx.set(dut.feedback_sends[index], value)
        for index, value in enumerate(input_gains):
            ctx.set(dut.input_gains[index], value)
        ctx.set(dut.de, 1)
        for panel_x, panel_y in points:
            if rotate_left:
                # ui_x = physical_y; ui_y = 719 - physical_x.
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


def test_native_canvas_is_centered_without_scaling_on_standard_video():
    points = ((106, 106), (613, 613), (105, 300), (614, 300))
    pixels = _render_samples(points=points)
    line = RezoTileDisplay.PALETTE["line"]
    blank = RezoTileDisplay.PALETTE["blank"]

    assert pixels == [
        (line, line, line),
        (line, line, line),
        (blank, blank, blank),
        (blank, blank, blank),
    ]


def test_interactive_content_stays_inside_the_508_pixel_safe_square():
    # The identity is intentionally allowed in the circular top arc. These
    # samples instead guard the four sides around the interactive content.
    points = ((100, 300), (620, 300), (300, 100), (300, 620))
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(points=points, page=7) == [
        (blank, blank, blank),
    ] * len(points)


def test_clock_editor_uses_native_stacked_control_rows():
    points = (
        (320, 260),  # algorithm value
        (320, 292),  # direction value
        (320, 328),  # source value
        (320, 356),  # BPM value
        (320, 388),  # depth rail
        (320, 420),  # algorithm-specific row
        (320, 484),  # third algorithm-specific row
        (320, 516),  # fourth algorithm-specific row
    )
    panel = RezoTileDisplay.PALETTE["panel"]
    assert _render_samples(
        points=points,
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_TURING,
        turing_target=RezoCore.TURING_TARGET_RANGE,
    ) == [
        (panel, panel, panel),
    ] * len(points)


def test_round_rotation_preserves_native_pixels_without_scaling():
    points = (
        (106, 106),
        (120, 130),
        (140, 260),
        (320, 424),
        (613, 613),
    )
    preview = _render_samples(points=points, page=7)
    circular = _render_samples(
        h_active=720,
        rotate_left=True,
        points=points,
        page=7,
    )
    assert circular == preview


def test_bands_enable_buttons_reuse_feedback_button_geometry():
    points = (
        (140, 283),  # top edge
        (140, 290),  # body
        (140, 316),  # bottom edge
        (140, 317),  # immediately below
    )
    kwargs = dict(
        points=points,
        band_enables=(1,),
        feedback_sends=(1,),
    )
    assert _render_samples(page=6, **kwargs) == _render_samples(page=1, **kwargs)


def test_input_audio_value_fill_stays_inside_its_panel():
    accent = RezoTileDisplay.PALETTE["control"]
    pixels = _render_samples(
        page=2,
        input_gains=(255,),
        points=((570, 260), (575, 260)),
    )
    assert pixels[0] == (accent, accent, accent)
    assert pixels[1] != (accent, accent, accent)
