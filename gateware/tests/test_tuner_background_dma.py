"""Actual DMA, asynchronous FIFO and scanout, using a delayed memory model."""
import pytest
from amaranth import Module, Signal, ResetSignal
from amaranth.sim import Simulator
from top.intono.background import BackgroundExchange, BackgroundLayout, SceneExchange
from tiliqua.video.framebuffer import DMAFramebuffer
from tiliqua.video.palette import ColorPalette


@pytest.mark.parametrize("invert", [False, True])
@pytest.mark.parametrize("coordinated", [False, True])
def test_background_dma_reads_complete_frames_and_presents_matching_pixels(invert, coordinated):
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
                    bank = int(address >= layout.word_bases[1])
                    offset = address - layout.word_bases[bank]
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
