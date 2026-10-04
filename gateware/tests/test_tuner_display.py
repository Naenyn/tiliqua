from collections import deque
from math import cos, pi, sin

import pytest
from amaranth import Module, unsigned
from amaranth.hdl import Fragment
from amaranth.lib.memory import Memory
from amaranth.sim import Simulator

from top.intono.display import FONT, FONT_CHARS, FONT_INDEX, Peripheral, IntonoOverlay
from top.intono.font_9x15 import MENU_FONT_BOLD, MENU_FONT_NORMAL
from top.intono.top import IntonoSoc


def test_blank_backdrop_keeps_text_and_restores_cached_pixels():
    tiles=Memory(shape=unsigned(16),depth=4096,init=[(ord("A")-32)|(0xF9<<8)])
    menu=Memory(shape=unsigned(8),depth=512,init=[])
    dut=IntonoOverlay(tiles,menu,h_active=720,ascii_text=True,double_buffered=True)
    m=Module();m.submodules.dut=dut;m.submodules.tiles=tiles;m.submodules.menu=menu
    sim=Simulator(m);sim.add_clock(1e-6,domain="dvi")
    async def bench(ctx):
        ctx.set(dut.i.de,1);ctx.set(dut.i.pixel.as_value(),0x59)
        for blank in [0,1,0]:
            ctx.set(dut.blank_background,blank)
            ctx.set(dut.i.x,300);ctx.set(dut.i.y,300)
            await ctx.tick("dvi").repeat(dut.LATENCY+1)
            assert ctx.get(dut.o.pixel.as_value()) == (0 if blank else 0x59)
            # Find an actual ink pixel in the shared normal A glyph.
            row=next(y for y in range(15) if MENU_FONT_NORMAL[(ord("A")-32)*15+y])
            bits=MENU_FONT_NORMAL[(ord("A")-32)*15+row]
            x=next(x for x in range(9) if bits&(1<<(8-x)))
            ctx.set(dut.i.x,90+x);ctx.set(dut.i.y,row)
            await ctx.tick("dvi").repeat(dut.LATENCY+1)
            assert ctx.get(dut.o.pixel.as_value()) == 0xF9
    sim.add_testbench(bench);sim.run()


@pytest.mark.parametrize("rotate_left", [False, True])
def test_settings_first_letter_has_clear_left_border_padding(rotate_left):
    tiles = Memory(shape=unsigned(16), depth=4096, init=[])
    menu = Memory(shape=unsigned(8), depth=512,
                  init=[128 + ord(c)-32 for c in "SETTINGS"])
    dut = IntonoOverlay(tiles, menu, h_active=720 if rotate_left else 1280,
                       rotate_left=rotate_left, ascii_text=True, double_buffered=True)
    m = Module()
    m.submodules.dut, m.submodules.tiles, m.submodules.menu = dut, tiles, menu
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        ctx.set(dut.menu_active, 1)
        ctx.set(dut.i.de, 1)
        assert dut.MENU_TEXT_X - (dut.MENU_X + 2) >= 4
        for gy in range(15):
            for x in range(dut.MENU_X, dut.MENU_TEXT_X + 9):
                y = dut.MENU_TEXT_Y + gy
                px, py = (719-y,x) if rotate_left else (x+280,y)
                ctx.set(dut.i.x, px)
                ctx.set(dut.i.y, py)
                gx = x-dut.MENU_TEXT_X
                ink = gx >= 0 and (MENU_FONT_BOLD[(ord("S")-32)*15+gy] >> (8-gx)) & 1
                expected = 0xA9 if x < dut.MENU_X+2 else (0xF9 if ink else 0)
                await ctx.tick("dvi").repeat(dut.LATENCY+1)
                assert ctx.get(dut.o.pixel.as_value()) == expected

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("rotate_left", [False, True])
def test_production_four_colored_markers(rotate_left):
    tiles = Memory(shape=unsigned(16), depth=4096, init=[])
    menu = Memory(shape=unsigned(8), depth=512, init=[])
    dut = IntonoOverlay(tiles, menu, h_active=720 if rotate_left else 1280,
                       rotate_left=rotate_left, ascii_text=True, double_buffered=True)
    m = Module()
    m.submodules.dut, m.submodules.tiles, m.submodules.menu = dut, tiles, menu
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        # Distinct colors, partial overlap, all orientations, and disable.
        for orientation in range(32):
            descriptors = [(340 + slot * 12, 300 + slot * 4,
                            (orientation + slot * 7) % 32, slot + 2,
                            orientation != 31) for slot in range(4)]
            mx, my, shape, hue, enabled = descriptors[0]
            for name, value in (("marker_x", mx), ("marker_y", my),
                                ("marker_lens_base", (shape % 11) * 1089),
                                ("marker_lens_bank", shape // 11),
                                ("marker_hue", hue), ("marker_valid", enabled)):
                ctx.set(getattr(dut, name), value)
            for slot, (mx, my, shape, hue, enabled) in enumerate(descriptors[1:], 1):
                ctx.set(getattr(dut, f"marker{slot}"), mx | (my << 10) |
                        (shape << 20) | (hue << 25) | (enabled << 29))
            centers = [(719-y, x) if rotate_left else (x+280, y)
                       for x, y, *_ in descriptors]
            for row in range(min(y for x, y in centers)-17,
                             max(y for x, y in centers)+18, 3):
                ctx.set(dut.i.y, row)
                ctx.set(dut.i.de, 0)
                for x in range(-16, 0):
                    ctx.set(dut.i.x, x)
                    await ctx.tick("dvi")
                ctx.set(dut.i.de, 1)
                queue = deque()
                for x in range(min(x for x, y in centers)-20,
                               max(x for x, y in centers)+30):
                    ctx.set(dut.i.x, x)
                    expected = 0
                    for (cx, cy), (_, _, shape, hue, enabled) in zip(centers, descriptors):
                        dx, dy = x-cx, row-cy
                        lx, ly = (dy, -dx) if rotate_left else (dx, dy)
                        angle = shape * pi / 32
                        tangent = lx*cos(angle) + ly*sin(angle)
                        normal = -lx*sin(angle) + ly*cos(angle)
                        if (enabled and abs(dx) <= 16 and abs(dy) <= 16 and
                                tangent*tangent*49 + normal*normal*256 <= 16*16*49):
                            expected = 0xC0 | hue
                    queue.append(expected)
                    await ctx.tick("dvi")
                    if len(queue) >= dut.LATENCY:
                        assert ctx.get(dut.o.pixel.as_value()) == queue.popleft()

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("rotate_left", [False, True])
def test_scanline_marker_all_orientations_and_frame_changes(rotate_left):
    tiles = Memory(shape=unsigned(6), depth=4096, init=[])
    menu = Memory(shape=unsigned(8), depth=512, init=[])
    dut = IntonoOverlay(tiles, menu, h_active=720 if rotate_left else 1280,
                       rotate_left=rotate_left, double_buffered=True)
    m = Module()
    m.submodules.dut, m.submodules.tiles, m.submodules.menu = dut, tiles, menu
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        for orientation in list(range(32)) + [0]:
            # Including 31->0 catches atlas wrap and stale scanline caches.
            mx, my = 350 + orientation, 270 + orientation
            cx, cy = (719 - my, mx) if rotate_left else (mx + 280, my)
            ctx.set(dut.marker_x, mx)
            ctx.set(dut.marker_y, my)
            ctx.set(dut.marker_valid, 1)
            ctx.set(dut.marker_hue, 3)
            ctx.set(dut.marker_lens_bank, orientation // 11)
            ctx.set(dut.marker_lens_base, (orientation % 11) * 1089)
            for dy in range(-17, 18):
                ctx.set(dut.i.y, cy + dy)
                ctx.set(dut.i.de, 0)
                for x in range(-16, 0):
                    ctx.set(dut.i.x, x)
                    await ctx.tick("dvi")
                ctx.set(dut.i.de, 1)
                queue = deque()
                for dx in range(-20, 21):
                    ctx.set(dut.i.x, cx + dx)
                    lx, ly = (dy, -dx) if rotate_left else (dx, dy)
                    angle = orientation * pi / 32
                    tangent = lx * cos(angle) + ly * sin(angle)
                    normal = -lx * sin(angle) + ly * cos(angle)
                    hit = (abs(dx) <= 16 and abs(dy) <= 16 and
                           tangent*tangent*49 + normal*normal*256 <= 16*16*49)
                    queue.append((cx + dx, cy + dy, 15 if hit else 0))
                    await ctx.tick("dvi")
                    if len(queue) >= dut.LATENCY:
                        assert (ctx.get(dut.o.x), ctx.get(dut.o.y),
                                ctx.get(dut.o.pixel.intensity)) == queue.popleft()
                for _ in range(dut.LATENCY - 1):
                    await ctx.tick("dvi")
                    assert (ctx.get(dut.o.x), ctx.get(dut.o.y),
                            ctx.get(dut.o.pixel.intensity)) == queue.popleft()

    sim.add_testbench(bench)
    sim.run()


def test_tuner_cpu_ram_has_interrupt_headroom():
    # main() currently reserves about 7.25 KiB before nested calls or interrupt
    # frames. The old 8-KiB allocation booted far enough to draw static content
    # and then silently corrupted the stack when the live UI started.
    assert IntonoSoc.MAINRAM_SIZE >= 0x4000


def test_tuner_font_contract():
    assert FONT_INDEX[" "] == 0
    assert len(FONT_CHARS) < 64
    assert len(set(FONT_CHARS)) == len(FONT_CHARS)
    assert all(char in FONT for char in FONT_CHARS)
    assert all(len(FONT[char]) == 7 for char in FONT_CHARS)
    assert all(0 <= row < 32 for char in FONT_CHARS for row in FONT[char])
    assert len(MENU_FONT_NORMAL) == 95 * 15
    assert len(MENU_FONT_BOLD) == 95 * 15
    assert all(0 <= row < 512 for row in MENU_FONT_NORMAL + MENU_FONT_BOLD)


def test_tuner_display_elaborates():
    # This catches accidental cross-domain memory-port conflicts and invalid
    # structured pixel expressions before the comparatively expensive FPGA build.
    Fragment.get(Peripheral(), platform=None)


@pytest.mark.parametrize("rotate_left", [False, True])
def test_compact_main_text_pitch_and_margins(rotate_left):
    cells = [(n + 33) | ((n % 2) << 7) | (0xD9 << 8) for n in range(45)]
    tiles = Memory(shape=unsigned(16), depth=4096, init=cells)
    menu = Memory(shape=unsigned(8), depth=512, init=[])
    dut = IntonoOverlay(tiles, menu, h_active=720 if rotate_left else 1280,
                       rotate_left=rotate_left, ascii_text=True)
    m = Module()
    m.submodules.dut, m.submodules.tiles, m.submodules.menu = dut, tiles, menu
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        queue = deque()
        ctx.set(dut.i.de, 1)
        for y in range(16):
            for x in range(720):
                hit = False
                if 90 <= x < 630 and y < 15:
                    column, gx = divmod(x - 90, 12)
                    font = MENU_FONT_BOLD if column % 2 else MENU_FONT_NORMAL
                    hit = gx < 9 and font[(column + 33) * 15 + y] & (1 << (8 - gx))
                px, py = (719-y, x) if rotate_left else (x+280, y)
                ctx.set(dut.i.x, px)
                ctx.set(dut.i.y, py)
                queue.append((px, py, 13 if hit else 0))
                await ctx.tick("dvi")
                if len(queue) >= dut.LATENCY:
                    assert (ctx.get(dut.o.x), ctx.get(dut.o.y),
                            ctx.get(dut.o.pixel.intensity)) == queue.popleft()
        for _ in range(dut.LATENCY - 1):
            await ctx.tick("dvi")
            assert (ctx.get(dut.o.x), ctx.get(dut.o.y),
                    ctx.get(dut.o.pixel.intensity)) == queue.popleft()

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("rotate_left", [False, True])
def test_shared_atlas_preserves_every_legacy_tuner_glyph(rotate_left):
    contents = list(range(len(FONT_CHARS))) + [0] * (45 * 45 - len(FONT_CHARS))
    tiles = Memory(shape=unsigned(6), depth=len(contents), init=contents)
    menu = Memory(shape=unsigned(8), depth=28 * 9, init=[])
    dut = IntonoOverlay(tiles, menu, h_active=720 if rotate_left else 1280,
                       rotate_left=rotate_left)
    m = Module()
    m.submodules.dut = dut
    m.submodules.tiles = tiles
    m.submodules.menu = menu
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        queue = deque()
        ctx.set(dut.i.de, 1)
        for y in range(16):
            for x in range(720):
                column, gx = divmod(x, 16)
                gy = y // 2
                gx //= 2
                glyph = FONT[FONT_CHARS[contents[column]]]
                hit = gx < 5 and gy < 7 and glyph[gy] & (1 << (4 - gx))
                physical_x, physical_y = (719 - y, x) if rotate_left else (x + 280, y)
                ctx.set(dut.i.x, physical_x)
                ctx.set(dut.i.y, physical_y)
                queue.append((physical_x, physical_y, 13 if hit else 0))
                await ctx.tick("dvi")
                if len(queue) >= dut.LATENCY:
                    assert (ctx.get(dut.o.x), ctx.get(dut.o.y),
                            ctx.get(dut.o.pixel.intensity)) == queue.popleft()
        for _ in range(dut.LATENCY - 1):
            await ctx.tick("dvi")
            assert (ctx.get(dut.o.x), ctx.get(dut.o.y),
                    ctx.get(dut.o.pixel.intensity)) == queue.popleft()

    sim.add_testbench(bench)
    sim.run()


def test_tuner_display_target_transforms_are_compile_time():
    async def check_border(ctx, dut, physical_x, physical_y):
        ctx.set(dut.i.de, 1)
        ctx.set(dut.menu_active, 1)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        ctx.set(dut.i.x, physical_x)
        ctx.set(dut.i.y, physical_y)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 10

    def run_target(*, h_active, rotate_left, physical_x, physical_y):
        tiles = Memory(
            shape=unsigned(6), depth=IntonoOverlay.COLS * IntonoOverlay.ROWS,
            init=[0] * (IntonoOverlay.COLS * IntonoOverlay.ROWS))
        menu = Memory(
            shape=unsigned(8),
            depth=IntonoOverlay.MENU_COLS * IntonoOverlay.MENU_ROWS,
            init=[0] * (IntonoOverlay.MENU_COLS * IntonoOverlay.MENU_ROWS))
        dut = IntonoOverlay(
            tiles, menu, h_active=h_active, rotate_left=rotate_left)
        m = Module()
        m.submodules.dut = dut
        m.submodules.tiles = tiles
        m.submodules.menu = menu
        sim = Simulator(m)
        sim.add_clock(1e-6, domain="dvi")

        async def bench(ctx):
            await check_border(ctx, dut, physical_x, physical_y)

        sim.add_testbench(bench)
        sim.run()

    # Standard HDMI centers the native canvas at x=280 without rotation.
    run_target(
        h_active=1280, rotate_left=False,
        physical_x=IntonoOverlay.MENU_X + 280, physical_y=400)
    # The production panel applies the inverse of its physical left rotation.
    run_target(
        h_active=720, rotate_left=True,
        physical_x=719 - 400, physical_y=IntonoOverlay.MENU_X)


def test_tuner_display_composites_framebuffer_marker_and_menu():
    tiles = Memory(
        shape=unsigned(6), depth=IntonoOverlay.COLS * IntonoOverlay.ROWS,
        init=[0] * (IntonoOverlay.COLS * IntonoOverlay.ROWS))
    menu = Memory(
        shape=unsigned(8),
        depth=IntonoOverlay.MENU_COLS * IntonoOverlay.MENU_ROWS,
        init=[0] * (IntonoOverlay.MENU_COLS * IntonoOverlay.MENU_ROWS))
    dut = IntonoOverlay(tiles, menu)
    m = Module()
    m.submodules.dut = dut
    m.submodules.tiles = tiles
    m.submodules.menu = menu
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        async def prepare_row(y):
            ctx.set(dut.i.de, 0)
            ctx.set(dut.i.y, y)
            for x in range(-16, 0):
                ctx.set(dut.i.x, x)
                await ctx.tick("dvi")
            ctx.set(dut.i.de, 1)

        ctx.set(dut.i.de, 1)

        # Static guide pixels arrive from the retained PSRAM framebuffer and
        # pass through the live overlay unchanged.
        ctx.set(dut.i.pixel.color, 9)
        ctx.set(dut.i.pixel.intensity, 5)
        ctx.set(dut.i.x, 360)
        ctx.set(dut.i.y, 360 - 52)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 5

        # An eighth-turn later, the guide has moved smoothly clockwise and
        # outward rather than remaining on the C0 circle.
        ctx.set(dut.i.x, 399)
        ctx.set(dut.i.y, 321)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 5

        # Consecutive samples on the outer turn are several pixels apart. The
        # connecting raster must fill their midpoint rather than showing dots.
        ctx.set(dut.i.x, 572)
        ctx.set(dut.i.y, 356)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 5

        # Background pixels pass through as black.
        ctx.set(dut.i.pixel.intensity, 0)
        ctx.set(dut.i.x, 393)
        ctx.set(dut.i.y, 400)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 0

        # The modal menu masks only its established right-side panel while leaving the live
        # tuner visible around it.
        ctx.set(dut.menu_active, 1)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        ctx.set(dut.i.x, 500)
        ctx.set(dut.i.y, 400)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 0

        # A retained radial tick outside the box remains live.
        ctx.set(dut.i.pixel.intensity, 2)
        ctx.set(dut.i.x, 477)
        ctx.set(dut.i.y, 157)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 2

        # The panel border is procedural and does not depend on stale tiles.
        ctx.set(dut.i.x, IntonoOverlay.MENU_X)
        ctx.set(dut.i.y, 400)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 10
        ctx.set(dut.menu_active, 0)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)

        # Closing the menu reveals the retained guide again.
        ctx.set(dut.i.x, 477)
        ctx.set(dut.i.y, 157)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 2

        # Retained radial divisions continue through the center.
        ctx.set(dut.i.x, 360)
        ctx.set(dut.i.y, 360)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 2

        # ARC mode highlights a short run of the actual spiral around the
        # detected pitch rather than drawing an unrelated cursor shape.
        ctx.set(dut.marker_x, 492)
        ctx.set(dut.marker_y, 228)
        ctx.set(dut.marker_hue, 2)
        ctx.set(dut.marker_valid, 1)
        ctx.set(dut.marker_visualizer, 0)
        ctx.set(dut.marker_lens_base, 8 * 33 * 33)  # 45-degree tangent
        ctx.set(dut.marker_lens_bank, 0)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        # Analytical mode renders a filled, rounded lens centered on the stored
        # spiral rather than only recoloring its thin centerline.
        await prepare_row(228)
        ctx.set(dut.i.x, 492)
        ctx.set(dut.i.y, 228)
        ctx.set(dut.i.pixel.intensity, 5)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 15

        # The long axis follows the 45-degree tangent.
        await prepare_row(237)
        ctx.set(dut.i.x, 501)
        ctx.set(dut.i.y, 237)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 15

        # The perpendicular axis remains narrow enough not to touch the next
        # octave band. This also guards against screen-axis widening artifacts.
        await prepare_row(219)
        ctx.set(dut.i.x, 501)
        ctx.set(dut.i.y, 219)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) != 15

        # Exercise consecutive pixels as HDMI does, instead of holding each
        # coordinate for the complete pipeline. The latter masked a bank/data
        # phase error in a cascaded synchronous ROM and allowed the filled lens
        # to fragment into horizontal slats on hardware.
        ctx.set(dut.marker_lens_base, 0)  # horizontal major axis
        ctx.set(dut.marker_lens_bank, 0)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        white_by_row = {}
        for y in range(210, 247):
            await prepare_row(y)
            for x in range(470, 515):
                ctx.set(dut.i.x, x)
                ctx.set(dut.i.y, y)
                await ctx.tick("dvi")
                out_x = ctx.get(dut.o.x)
                out_y = ctx.get(dut.o.y)
                if (470 <= out_x < 515 and 210 <= out_y < 247 and
                        ctx.get(dut.o.pixel.intensity) == 15):
                    white_by_row.setdefault(out_y, set()).add(out_x)
        await ctx.tick("dvi").repeat(4)
        center = sorted(white_by_row[228])
        assert len(center) >= 31
        assert center[-1] - center[0] + 1 == len(center)
        assert all(white_by_row.get(y) for y in range(221, 236))

        # VISUALIZER mode provides a rounded, layered halo independent of the
        # static guide, with the middle band deliberately softer than its core.
        ctx.set(dut.marker_x, 500)
        ctx.set(dut.marker_y, 250)
        ctx.set(dut.marker_visualizer, 1)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        ctx.set(dut.i.x, 510)
        ctx.set(dut.i.y, 250)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 8

        # The square corner is outside the official panel's circular viewport.
        ctx.set(dut.i.pixel.intensity, 0)
        ctx.set(dut.i.x, 0)
        ctx.set(dut.i.y, 0)
        await ctx.tick("dvi").repeat(IntonoOverlay.LATENCY + 1)
        assert ctx.get(dut.o.pixel.intensity) == 0

    sim.add_testbench(bench)
    sim.run()

@pytest.mark.parametrize('rotate_left', [False, True])
@pytest.mark.parametrize('glyph,bold', [('M', False), ('g', True)])
@pytest.mark.parametrize('legacy_menu_active', [False, True])
def test_large_ux_text_retains_stride_bank_and_pixel_scale(rotate_left, glyph, bold, legacy_menu_active, column_override=None):
    from top.intono.font_9x15 import MENU_FONT_NORMAL, MENU_FONT_BOLD
    font = MENU_FONT_BOLD if bold else MENU_FONT_NORMAL
    column, row = ((20 if legacy_menu_active else 7), 5) if column_override is None else (column_override,10)
    contents = [0] * 4096
    contents[2048 + row * 45 + column] = (ord(glyph) - 32) | (int(bold) << 7) | (0xF9 << 8)
    tiles = Memory(shape=unsigned(16), depth=4096, init=contents)
    menu = Memory(shape=unsigned(8), depth=512, init=[])
    dut = IntonoOverlay(tiles, menu, h_active=720 if rotate_left else 1280,
                       rotate_left=rotate_left, ascii_text=True,
                       double_buffered=True, large_text=True)
    m = Module()
    m.submodules.dut, m.submodules.tiles, m.submodules.menu = dut, tiles, menu
    sim = Simulator(m)
    sim.add_clock(1e-6, domain='dvi')
    async def bench(ctx):
        queue = deque()
        ctx.set(dut.i.de, 1)
        ctx.set(dut.menu_active, legacy_menu_active)
        for bank in (0, 1):
            ctx.set(dut.front_bank, bank)
            for gy in range(32):
                for gx in range(12):
                    hit = bank == 1 and gx < 9 and gy < 15 and bool(
                        font[(ord(glyph) - 32) * 15 + gy]
                        & (1 << (8 - gx)))
                    x, y = 120 + column * 12 + gx, row * 32 + gy
                    px, py = (719-y, x) if rotate_left else (x+280, y)
                    ctx.set(dut.i.x, px); ctx.set(dut.i.y, py)
                    queue.append((px, py, 15 if hit else 0))
                    await ctx.tick('dvi')
                    if len(queue) >= dut.LATENCY:
                        assert (ctx.get(dut.o.x), ctx.get(dut.o.y), ctx.get(dut.o.pixel.intensity)) == queue.popleft()
        for _ in range(dut.LATENCY - 1):
            await ctx.tick('dvi')
            assert (ctx.get(dut.o.x), ctx.get(dut.o.y), ctx.get(dut.o.pixel.intensity)) == queue.popleft()
    sim.add_testbench(bench)
    sim.run()


def test_compact_ux_font_has_crisp_capitals_and_complete_labels():
    from top.intono.font_7x10 import UX_FONT_NORMAL, UX_FONT_BOLD
    assert len(UX_FONT_NORMAL) == len(UX_FONT_BOLD) == 95 * 10
    for index in range(95):
        normal = UX_FONT_NORMAL[index * 10:(index + 1) * 10]
        bold = UX_FONT_BOLD[index * 10:(index + 1) * 10]
        assert all(0 <= row < 128 for row in normal + bold)
        if index:
            assert any(normal), chr(index + 32)
        if index:
            assert any(bold), chr(index + 32)
    for char in 'abcdefghijklmnopqrstuvwxyz':
        def rows(c):
            offset = (ord(c) - 32) * 10
            return UX_FONT_NORMAL[offset:offset + 10]
        assert rows(char) == rows(char.upper())
    assert UX_FONT_NORMAL[(ord('M') - 32) * 10:(ord('M') - 31) * 10] == [
        0, 0x42, 0x66, 0x66, 0x5a, 0x5a, 0x42, 0x42, 0x42, 0x42]

@pytest.mark.parametrize("rotate_left", [False, True])
def test_keyboard_fills_follow_mask_without_covering_edges_or_text(rotate_left):
    cells=[0]*4096
    cells[10*45+6]=(ord("C")-32)|(0x19<<8)
    tiles=Memory(shape=unsigned(16),depth=4096,init=cells)
    menu=Memory(shape=unsigned(8),depth=512,init=[])
    dut=IntonoOverlay(tiles,menu,h_active=720 if rotate_left else 1280,
        rotate_left=rotate_left,ascii_text=True,large_text=True,double_buffered=True)
    m=Module();m.submodules.dut=dut;m.submodules.tiles=tiles;m.submodules.menu=menu
    sim=Simulator(m);sim.add_clock(1e-6,domain="dvi")
    async def sample(ctx,x,y,tag=None):
        # Retained raster tag for this sample, including black-key occlusion.
        pixel=0x49
        for black_pass in [False,True]:
            for note,(pos,black) in enumerate([(0,False),(1,True),(1,False),(2,True),
                    (2,False),(3,False),(4,True),(4,False),(5,True),(5,False),(6,True),(6,False)]):
                if black!=black_pass:continue
                left=164+pos*56-(18 if black else 0)
                width,height=(36,40) if black else (57,72)
                if left<=x<left+width and 280<=y<280+height:
                    pixel=0xe0+note if left<x<left+width-1 and 280<y<280+height-1 else 0x49
        ctx.set(dut.i.pixel.as_value(),pixel if tag is None else tag)
        px,py=(719-y,x) if rotate_left else (280+x,y)
        ctx.set(dut.i.x,px);ctx.set(dut.i.y,py)
        await ctx.tick("dvi").repeat(dut.LATENCY+1)
        return ctx.get(dut.o.pixel.as_value())
    async def bench(ctx):
        ctx.set(dut.i.de,1);ctx.set(dut.i.pixel.as_value(),0x49)
        ctx.set(dut.keyboard_enable,1)
        ctx.set(dut.keyboard_second,1)
        keys=[(0,False),(1,True),(1,False),(2,True),(2,False),(3,False),
              (4,True),(4,False),(5,True),(5,False),(6,True),(6,False)]
        for mask in [0,1,0xad6,0xfff]:
            ctx.set(dut.keyboard_mask,mask)
            for note,(pos,black) in enumerate(keys):
                center=164+pos*56+(0 if black else 28)
                color=0xa9 if mask&(1<<note) else (0x09 if black else 0xf9)
                assert await sample(ctx,center,300 if black else 336)==color
                left=164+pos*56-(18 if black else 0)
                assert await sample(ctx,left,300 if black else 336)==0x49
            assert await sample(ctx,150,300)==0x49
            assert await sample(ctx,200,280)==0x49
        # Two published masks remain independent, including empty/full cycles.
        for ma,mb in [(0,0xfff),(0xfff,0),(0xad6,0x249),(1,2)]:
            ctx.set(dut.keyboard_mask,ma);ctx.set(dut.keyboard_mask_b,mb)
            for octave,mask in enumerate([ma,mb]):
                for note in range(12):
                    tag=0xe0+octave*16+note
                    black=note in [1,3,6,8,10]
                    expected=0xa9 if mask&(1<<note) else (0x09 if black else 0xf9)
                    assert await sample(ctx,200,300+octave*128,tag)==expected
                    if not black:
                        body=expected
                        assert await sample(ctx,200,336+octave*128,tag)==body
        # Membership and cursor are independent of piano identity, in each
        # visible octave and in the centered single-octave geometry.
        for second in (0,1):
            ctx.set(dut.keyboard_second,second)
            for octave in range(2 if second else 1):
                offset=octave*128+(0 if second else 64)
                for note,black in ((0,False),(1,True)):
                    center=192 if note==0 else 220
                    yy=(312 if black else 344)+offset
                    tag=0xe0+octave*16+note
                    for included in (False,True):
                        ctx.set(dut.keyboard_mask,(1<<note) if included else 0)
                        ctx.set(dut.keyboard_mask_b,(1<<note) if included else 0)
                        assert await sample(ctx,center,yy,tag)==(0xa9 if included else (0x09 if black else 0xf9))
                        assert await sample(ctx,center,yy-3,tag)==(0xa9 if included else (0x09 if black else 0xf9))
                    ctx.set(dut.keyboard_focus,octave*16+note)
                    left=202 if black else 164
                    assert await sample(ctx,left+1,yy,tag)==0x09
                    assert await sample(ctx,left+2,yy,tag)==0xd2
                    assert await sample(ctx,left+3,yy,tag)==0xd2
                    assert await sample(ctx,left+4,yy,tag)==0x09
                    # Rounded corners match an inset of the retained radius-4
                    # keys, mirrored on all four corners and both key sizes.
                    width,height=(36,40) if black else (57,72)
                    top=280+offset
                    for cy in (2,3,4):
                        for cx in (2,3,4):
                            inset=4 if cy==2 else 3 if cy==3 else 2
                            expected=0xd2 if cx>=inset and not (cx>=4 and cy>=4) else 0x09
                            for xx in (cx,width-1-cx):
                                for yyy in (cy,height-1-cy):
                                    assert await sample(ctx,left+xx,top+yyy,tag)==expected
                    ctx.set(dut.keyboard_focus,31)
                    assert await sample(ctx,left+2,yy,tag)==0xa9
        ctx.set(dut.keyboard_second,1)
        # Text remains above the filled key, with the selected natural-key dark ink color.
        ctx.set(dut.keyboard_mask,1)
        glyph=MENU_FONT_NORMAL[(ord("C")-32)*15:(ord("C")-32+1)*15]
        gy=next(y for y,bits in enumerate(glyph) if bits)
        gx=next(x for x in range(9) if glyph[gy]&(1<<(8-x)))
        assert await sample(ctx,192+gx,320+gy)==0x19
        ctx.set(dut.keyboard_enable,0)
        assert await sample(ctx,192,336)==0xe0
        ctx.set(dut.i.de,0)
        await ctx.tick("dvi").repeat(dut.LATENCY+1)
        assert ctx.get(dut.o.pixel.as_value())==0
    sim.add_testbench(bench);sim.run()


@pytest.mark.parametrize("rotate_left", [False, True])
def test_loading_view_hides_control_outlines_without_hiding_text(rotate_left):
    from amaranth.lib.memory import Memory
    from amaranth import unsigned
    col,row,glyph=18,8,"I"
    contents=[0]*4096
    contents[2048+row*45+col]=(ord(glyph)-32)|(1<<7)|(0xF9<<8)
    tiles=Memory(shape=unsigned(16),depth=4096,init=contents)
    menu=Memory(shape=unsigned(8),depth=512,init=[])
    dut=IntonoOverlay(tiles,menu,h_active=1280 if not rotate_left else 720,
        rotate_left=rotate_left,ascii_text=True,large_text=True,double_buffered=True)
    m=Module();m.submodules.dut=dut;m.submodules.tiles=tiles;m.submodules.menu=menu
    sim=Simulator(m);sim.add_clock(1e-6,domain="dvi")
    async def pixel(ctx,x,y):
        px,py=(719-y,x) if rotate_left else (x+280,y)
        ctx.set(dut.i.x,px);ctx.set(dut.i.y,py)
        await ctx.tick("dvi").repeat(dut.LATENCY+1)
        return ctx.get(dut.o.pixel.intensity)
    async def bench(ctx):
        ctx.set(dut.i.de,1);ctx.set(dut.front_bank,1)
        gx,gy=next((x,y) for y in range(15) for x in range(9)
            if MENU_FONT_BOLD[(ord(glyph)-32)*15+y] & (1<<(8-x)))
        for ready in (0,1,0):
            ctx.set(dut.ui_ready,ready)
            assert await pixel(ctx,148+10,90)==(6 if ready else 0)
            assert await pixel(ctx,120+col*12+gx,row*32+gy)==15
    sim.add_testbench(bench);sim.run()


@pytest.mark.parametrize("bad_pixel,bad_x", [(0xA4,740),(0x29,1279)])
def test_background_diagnostic_distinguishes_bad_samples_from_composited_colors(bad_pixel,bad_x):
    """Observe unexpected DMA colors without masking or changing any pixels."""
    from amaranth.lib.memory import Memory
    from amaranth import unsigned
    tiles=Memory(shape=unsigned(16),depth=4096,init=[])
    menu=Memory(shape=unsigned(8),depth=512,init=[])
    dut=IntonoOverlay(tiles,menu,h_active=1280,ascii_text=True,
                     large_text=True,double_buffered=True)
    m=Module();m.submodules.dut=dut;m.submodules.tiles=tiles;m.submodules.menu=menu
    sim=Simulator(m);sim.add_clock(1e-6,domain="dvi");sim.add_clock(1.3e-6,domain="sync")
    async def sample(ctx,pixel,x=740,de=1):
        ctx.set(dut.i.x,x);ctx.set(dut.i.y,360)
        ctx.set(dut.i.de,de);ctx.set(dut.i.pixel.as_value(),pixel)
        await ctx.tick("dvi").repeat(16)
        return ctx.get(dut.background_errors)
    async def bench(ctx):
        for raw in (0,0x29,0x59,0x69,0xFF,0xDB,0xD2,0xD0,0xE0,0xEB,0xF0,0xFB):
            assert await sample(ctx,raw)==0
        assert await sample(ctx,0xA4,de=0)==0, "blanking data is irrelevant"
        expected = 3 if bad_x == 1279 else 1
        assert await sample(ctx,bad_pixel,x=bad_x)==expected
        assert ctx.get(dut.o.pixel.as_value())==bad_pixel, "diagnostic must not alter output"
        assert await sample(ctx,0xA4)==expected, "evidence remains latched"
        assert await sample(ctx,0)==expected
        assert await sample(ctx,0x29,x=1279)==3, "incoming and output checks both latch"
        assert await sample(ctx,0,x=1279)==3
        for _ in range(5):
            await sample(ctx,0xA4)
            await sample(ctx,0)
        assert ctx.get(dut.background_errors)==3, "evidence must remain set until reset"
    sim.add_testbench(bench);sim.run()


def test_output_diagnostic_detects_overlay_leak_with_clean_background():
    """A deliberately misplaced text plane isolates the post-overlay flag."""
    from amaranth.lib.memory import Memory
    from amaranth import unsigned
    tiles = Memory(shape=unsigned(16), depth=4096,
                   init=[(ord("A")-32) | (0xF9 << 8)])
    menu = Memory(shape=unsigned(8), depth=512, init=[])
    dut = IntonoOverlay(tiles, menu, h_active=1280, ascii_text=True,
                       large_text=True, double_buffered=True)
    dut.UX_TEXT_X = -280  # Inject bad layout: its first glyph is at physical X=0.
    m = Module(); m.submodules.dut = dut
    m.submodules.tiles = tiles; m.submodules.menu = menu
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi"); sim.add_clock(1.3e-6, domain="sync")
    async def bench(ctx):
        ctx.set(dut.i.de, 1)
        ctx.set(dut.i.pixel.as_value(), 0)
        for y in range(15):
            ctx.set(dut.i.y, y)
            for x in range(9):
                ctx.set(dut.i.x, x)
                await ctx.tick("dvi").repeat(16)
        assert ctx.get(dut.background_errors) == 2
        ctx.set(dut.i.x, 740)
        await ctx.tick("dvi").repeat(16)
        assert ctx.get(dut.background_errors) == 2, "output evidence is sticky"
    sim.add_testbench(bench); sim.run()

@pytest.mark.parametrize("rotate_left",[False,True])
def test_octave_scroll_text_reaches_the_rightmost_native_column(rotate_left):
    test_large_ux_text_retains_stride_bank_and_pixel_scale(rotate_left,"W",False,False,42)
