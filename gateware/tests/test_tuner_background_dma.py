"""Actual DMA, asynchronous FIFO and scanout, using a delayed memory model."""
import pytest
from amaranth import Module, Signal, ResetSignal
from amaranth.sim import Simulator
from top.intono.background import BackgroundExchange, BackgroundLayout, SceneExchange
from tiliqua.video.framebuffer import DMAFramebuffer
from tiliqua.video.palette import ColorPalette, compute_color_palette


@pytest.mark.parametrize("memory_delay", [0, 1])
def test_first_page_visits_keep_scene_and_pixels_aligned_at_r5_clock_ratio(memory_delay):
    """Exercise immutable tuner/keyboard and mutable CAL at production clocks.

    Distinct image bytes catch stale FIFO contents even when they are otherwise
    legal palette colors. Each completed frame requests the next page midway
    through active scanout, then checks metadata at every visible pixel.
    """
    width, height = 128, 8
    layout = BackgroundLayout(width, height)
    owner = SceneExchange(layout, 8)
    palette = ColorPalette()
    colors = list(zip(*compute_color_palette()))
    dut = DMAFramebuffer(palette=palette, fifo_depth=512,
                         burst_threshold_words=128, frame_exchange=owner)
    m = Module()
    m.submodules.dut, m.submodules.palette = dut, palette
    sim = Simulator(m)
    sim.add_clock(1 / 60e6, domain="sync")
    sim.add_clock(1 / 74.25e6, domain="dvi")
    bases = {0: 0, 1: 0x200000, 3: 0x2C0000, 4: 0x280000,
             5: layout.word_bases[1], 6: 0x340000}
    pages = [(1, False, 1), (6, False, 6), (0, True, 5),
             (6, False, 6), (3, False, 3), (1, False, 1),
             (0, False, 5), (3, False, 3), (6, False, 6)]

    def pixel(image, offset):
        return (image << 4) | (offset % 13 + 1)

    async def memory(ctx):
        pending = None
        delay = 0
        while True:
            ctx.set(dut.bus.ack, 0)
            if ctx.get(dut.bus.cyc) and ctx.get(dut.bus.stb):
                transfer = ctx.get(dut.bus.adr), ctx.get(dut.bus.cti)
                if pending is None:
                    pending = transfer
                    delay = memory_delay + (2 if transfer[1] == 7 else 0)
                assert transfer == pending
                if delay == 0:
                    address = transfer[0]
                    image, base = max(((image, base) for image, base in bases.items()
                                       if base <= address), key=lambda pair: pair[1])
                    offset = address - base
                    assert 0 <= offset < width * height // 4
                    ctx.set(dut.bus.dat_r, sum(pixel(image, offset * 4 + n) << (8*n)
                                              for n in range(4)))
                    ctx.set(dut.bus.ack, 1)
                    await ctx.tick("sync")
                    pending = None
                    continue
                delay -= 1
            else:
                assert pending is None
            await ctx.tick("sync")

    async def screen(ctx):
        for field, value in dict(h_active=width, h_total=165, h_sync_start=139,
                h_sync_end=151, v_active=height, v_total=14, v_sync_start=10,
                v_sync_end=12, active_pixels=width*height).items():
            ctx.set(getattr(dut.fbp.timings, field), value)
        requested = 0
        completed = 0
        for _ in range(30000):
            ctx.set(owner.boundary, ctx.get(palette.i.x) == 0 and
                    ctx.get(palette.i.y) == -1 and not ctx.get(palette.i.de))
            ctx.set(owner.submit, 0)
            input_pixel = ctx.get(palette.i.pixel.as_value())
            input_timing = tuple(ctx.get(getattr(palette.i, field))
                                 for field in ("de", "hsync", "vsync"))
            await ctx.tick("dvi")
            assert tuple(ctx.get(getattr(palette.o, field))
                         for field in ("r", "g", "b")) == colors[input_pixel]
            assert tuple(ctx.get(getattr(palette.o, field))
                         for field in ("de", "hsync", "vsync")) == input_timing
            if not ctx.get(palette.i.de):
                continue
            x, y = ctx.get(palette.i.x), ctx.get(palette.i.y)
            if completed:
                image = ctx.get(owner.published)
                assert ctx.get(palette.i.pixel.as_value()) == pixel(image, y*width+x), \
                    f"frame {completed}, ({x}, {y}), scene {image}"
            if y == 3 and x == 32 and completed and requested < len(pages):
                assert not ctx.get(owner.busy)
                source, swap, image = pages[requested]
                ctx.set(owner.static_source, source)
                ctx.set(owner.swap_background, swap)
                ctx.set(owner.payload, image)
                ctx.set(owner.submit, 1)
                # One pixel period is shorter than a CPU period: hold the
                # request long enough for a synchronous register write.
                await ctx.tick("sync")
                requested += 1
            if x == width-1 and y == height-1:
                completed += 1
                if completed == len(pages) + 3:
                    break
        assert completed == len(pages) + 3
        assert requested == len(pages)
        assert ctx.get(dut.scanout_gaps) == 0

    sim.add_testbench(memory, background=True)
    sim.add_testbench(screen)
    sim.run()


def test_memory_gap_blanks_background_instead_of_repeating_a_bright_pixel():
    """Keep video timing running while deliberately starving an active scan."""
    width, height = 64, 8
    owner = SceneExchange(BackgroundLayout(width, height), 8)
    palette = ColorPalette()
    dut = DMAFramebuffer(palette=palette, fifo_depth=16, burst_threshold_words=4,
                         frame_exchange=owner)
    m = Module()
    m.submodules.dut, m.submodules.palette = dut, palette
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(11.3e-6, domain="dvi")
    stalled = [False]

    async def memory(ctx):
        while True:
            ctx.set(dut.bus.ack, int(not stalled[0] and
                    ctx.get(dut.bus.cyc) and ctx.get(dut.bus.stb)))
            ctx.set(dut.bus.dat_r, 0x69696969)
            await ctx.tick("sync")

    async def screen(ctx):
        for field, value in dict(h_active=width, h_total=96, h_sync_start=80,
                h_sync_end=88, v_active=height, v_total=14, v_sync_start=10,
                v_sync_end=12, active_pixels=width*height).items():
            ctx.set(getattr(dut.fbp.timings, field), value)
        started = False
        before = 0
        gaps = 0
        recovered = False
        for _ in range(4000):
            await ctx.tick("dvi")
            if not ctx.get(palette.i.de):
                continue
            x, y = ctx.get(palette.i.x), ctx.get(palette.i.y)
            pixel = ctx.get(palette.i.pixel.as_value())
            if not started and y == 2 and pixel == 0x69:
                before = ctx.get(dut.scanout_gaps)
                stalled[0] = True
                started = True
            if started and stalled[0] and y == 4:
                # More than a full FIFO's worth of pixels since the pause.
                assert pixel == 0, "last bright pixel was stretched across a gap"
                gaps += 1
            if started and y == 5:
                stalled[0] = False
            if started and not stalled[0] and y == 0 and pixel == 0x69:
                recovered = True
                break
        assert gaps == width and recovered
        assert ctx.get(dut.scanout_gaps) > before

    sim.add_testbench(memory, background=True)
    sim.add_testbench(screen)
    sim.run()


@pytest.mark.parametrize("static_source", [0, 1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("invert", [False, True])
@pytest.mark.parametrize("coordinated", [False, True])
def test_background_dma_reads_complete_frames_and_presents_matching_pixels(invert, coordinated, static_source):
    if static_source and not coordinated:
        pytest.skip("immutable sources use coordinated exchange")
    width, height = 32, 8
    layout = BackgroundLayout(width, height)
    owner = SceneExchange(layout, 8) if coordinated else BackgroundExchange(layout)
    palette = ColorPalette()
    dut = DMAFramebuffer(palette=palette, fifo_depth=16, burst_threshold_words=4,
                         frame_exchange=owner)
    m = Module()
    reset = Signal(init=1)
    m.d.comb += ResetSignal("dvi").eq(reset)
    m.submodules.dut, m.submodules.palette = dut, palette
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(11.3e-6, domain="dvi")
    transactions = []
    acquisitions = []

    def pixel(bank, offset):
        return ((offset * 7 + 3) & 0x7F) | (bank << 7)

    async def memory(ctx):
        pending = None
        delay = 0
        submit = False
        for cycle in range(60000):
            if ctx.get(owner.acquire):
                acquisitions.append(ctx.get(owner.next_base))
            if ctx.get(owner.busy):
                ctx.set(owner.submit, 0)
            # Commit while first frame is already being fetched, not at vsync.
            if len(transactions) == 3 and not submit:
                if coordinated:
                    ctx.set(owner.static_source, static_source)
                    ctx.set(owner.payload, 0xB1)
                    ctx.set(owner.swap_background, 1)
                ctx.set(owner.submit, 1)
                submit = True
            ctx.set(dut.bus.ack, 0)
            if ctx.get(dut.bus.cyc) and ctx.get(dut.bus.stb):
                transfer = (ctx.get(dut.bus.adr), ctx.get(dut.bus.cti))
                if pending is None:
                    pending = transfer
                    # Stall every terminal transfer, including the final word.
                    delay = 7 if transfer[1] == 7 else 2
                assert transfer == pending, "bus transfer changed before ACK"
                if delay == 0:
                    address = transfer[0]
                    new_base = {1: 0x200000, 2: 0x240000, 3: 0x2C0000, 4: 0x280000, 5: 0x300000, 6: 0x340000}.get(static_source, layout.word_bases[1])
                    bank = int(address >= new_base)
                    offset = address - (new_base if bank else 0)
                    assert 0 <= offset < width * height // 4
                    ctx.set(dut.bus.dat_r, sum(pixel(bank,offset*4+n) << (8*n) for n in range(4)))
                    ctx.set(dut.bus.ack, 1)
                    transactions.append(address)
                    await ctx.tick("sync")
                    pending = None
                    continue
                delay -= 1
            else:
                assert pending is None, "unacknowledged transfer abandoned"
            await ctx.tick("sync")

    async def screen(ctx):
        for field,value in dict(h_active=width,h_total=64,h_sync_start=48,h_sync_end=56,
                                v_active=height,v_total=14,v_sync_start=10,v_sync_end=12,
                                active_pixels=width*height,h_sync_invert=invert,
                                v_sync_invert=invert).items():
            ctx.set(getattr(dut.fbp.timings,field),value)
        await ctx.delay(30e-6)
        ctx.set(reset, 0)
        frames = []
        current = []
        for _ in range(6000):
            if coordinated:
                ctx.set(owner.boundary, ctx.get(palette.i.x) == 0 and
                        ctx.get(palette.i.y) == -1 and not ctx.get(palette.i.de))
            await ctx.tick("dvi")
            if ctx.get(palette.i.de):
                x,y = ctx.get(palette.i.x),ctx.get(palette.i.y)
                assert 0 <= x < width and 0 <= y < height
                if x == 0 and y == 0:
                    current = []
                current.append(ctx.get(palette.i.pixel.as_value()))
                if coordinated:
                    # Synthetic scene metadata stands in for the latched
                    # text bank + marker payload; check at EVERY visible pixel.
                    bank = ctx.get(palette.i.pixel.as_value()) >> 7
                    assert ctx.get(owner.visible_background) == bank
                    assert ctx.get(owner.published) == (0xB1 if bank else 0)
                if x == width-1 and y == height-1:
                    frames.append(current)
                    if len(frames) == 5: break
        assert len(frames) == 5
        # Startup starts from the first internal vsync; complete displayed
        # frames must be the old bank followed by the committed bank.
        assert frames[0] == [0] * (width*height)  # startup before DMA's first vsync
        assert frames[1] == [pixel(0,n) for n in range(width*height)]
        assert all(frame == [pixel(1,n) for n in range(width*height)] for frame in frames[2:])
        count = width*height//4
        for index, base in enumerate(acquisitions[:4]):
            assert transactions[index*count:(index+1)*count] == list(range(base,base+count))

    sim.add_testbench(memory, background=True)
    sim.add_testbench(screen)
    sim.run()


@pytest.mark.parametrize("production_clocks", [False, True])
@pytest.mark.parametrize("stall_ticks", [280, 1800])
@pytest.mark.parametrize("switch_scene", [False, True])
def test_memory_gap_recovery_preserves_pixel_positions(stall_ticks, switch_scene, production_clocks):
    """Late pixels are discarded, even across a frame and pending page change."""
    width, height = 64, 8
    owner = SceneExchange(BackgroundLayout(width, height), 8)
    palette = ColorPalette()
    dut = DMAFramebuffer(palette=palette, fifo_depth=16, burst_threshold_words=4,
                         frame_exchange=owner)
    m = Module()
    m.submodules.dut, m.submodules.palette = dut, palette
    sim = Simulator(m)
    sim.add_clock(1 / 60e6 if production_clocks else 1e-6, domain="sync")
    sim.add_clock(1 / 74.25e6 if production_clocks else 11.3e-6, domain="dvi")
    stalled = [False]

    def pixel(image, offset):
        return (offset * 7 + image * 89) % 251 + 1

    async def memory(ctx):
        while True:
            ctx.set(dut.bus.ack, int(not stalled[0] and
                    ctx.get(dut.bus.cyc) and ctx.get(dut.bus.stb)))
            address = ctx.get(dut.bus.adr)
            image = int(address >= 0x200000)
            offset = address - image * 0x200000
            ctx.set(dut.bus.dat_r, sum(pixel(image, offset*4+n) << (8*n) for n in range(4)))
            await ctx.tick("sync")

    async def screen(ctx):
        for field, value in dict(h_active=width, h_total=96, h_sync_start=80,
                h_sync_end=88, v_active=height, v_total=14, v_sync_start=10,
                v_sync_end=12, active_pixels=width*height).items():
            ctx.set(getattr(dut.fbp.timings, field), value)
        started_at = None
        blanked = 0
        recovered_frames = 0
        frame_pixels = 0
        for cycle in range(10000):
            ctx.set(owner.boundary, ctx.get(palette.i.x) == 0 and
                    ctx.get(palette.i.y) == -1 and not ctx.get(palette.i.de))
            if ctx.get(owner.busy):
                ctx.set(owner.submit, 0)
            if started_at is not None and cycle - started_at >= stall_ticks:
                stalled[0] = False
            await ctx.tick("dvi")
            if not ctx.get(palette.i.de):
                continue
            x, y = ctx.get(palette.i.x), ctx.get(palette.i.y)
            value = ctx.get(palette.i.pixel.as_value())
            if x == 0 and y == 0:
                frame_pixels = 0
            if value:
                expected = pixel(ctx.get(owner.published), y*width+x)
                assert value == expected, f"Displaced pixel at ({x},{y}): {value} != {expected}"
                frame_pixels += 1
            elif started_at is not None:
                blanked += 1
            if started_at is None and y == 2 and value:
                stalled[0] = True
                started_at = cycle
                if switch_scene:
                    ctx.set(owner.static_source, 1)
                    ctx.set(owner.payload, 1)
                    ctx.set(owner.submit, 1)
            if started_at is not None and not stalled[0] and x == width-1 and y == height-1:
                if frame_pixels == width*height:
                    recovered_frames += 1
                    if recovered_frames == 2:
                        break
        assert blanked > 0 and recovered_frames == 2
        assert ctx.get(dut.scanout_gaps) > 0
        assert ctx.get(owner.published) == int(switch_scene)

    sim.add_testbench(memory, background=True)
    sim.add_testbench(screen)
    sim.run()
