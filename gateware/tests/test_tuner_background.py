import pytest
from amaranth.sim import Simulator
from top.intono.background import BackgroundExchange, BackgroundLayout, SceneExchange


def test_scene_foreground_commits_do_not_implicitly_swap_backgrounds():
    dut = SceneExchange(BackgroundLayout(1280, 720), 16)
    sim = Simulator(dut)
    sim.add_clock(1.3e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        background = 0
        for index, swap in enumerate([False, True, False, True, False]):
            ctx.set(dut.payload, 100 + index)
            ctx.set(dut.swap_background, swap)
            ctx.set(dut.submit, 1)
            await ctx.tick("sync")
            ctx.set(dut.payload, 999)
            ctx.set(dut.swap_background, not swap)
            # Early visible boundaries and repeated submissions do nothing
            # until the DMA has acquired the held scene.
            ctx.set(dut.boundary, 1)
            await ctx.tick("sync").repeat(5)
            assert ctx.get(dut.busy)
            ctx.set(dut.submit, 0)
            ctx.set(dut.boundary, 0)
            background ^= swap
            assert ctx.get(dut.next_base) == (0x40000 if background else 0)
            ctx.set(dut.acquire, 1)
            await ctx.tick("sync")
            ctx.set(dut.acquire, 0)
            await ctx.tick("dvi").repeat(5)
            assert ctx.get(dut.busy), "DMA acquisition alone must not release text banks"
            ctx.set(dut.boundary, 1)
            await ctx.tick("dvi")
            ctx.set(dut.boundary, 0)
            assert ctx.get(dut.published) == 100 + index
            assert ctx.get(dut.front_bank) == ((index + 1) & 1)
            assert ctx.get(dut.visible_background) == background
            await ctx.tick("sync").repeat(5)
            assert not ctx.get(dut.busy)

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("width", [720, 1280])
def test_background_storage_does_not_overlap_firmware(width):
    layout = BackgroundLayout(width, 720)
    assert layout.word_bases == (0, 0x40000)
    assert layout.frame_bytes <= layout.stride
    assert layout.stride + layout.frame_bytes <= 0x200000
    assert layout.frame_bytes == width * 720


def test_invalid_background_layouts_are_rejected():
    for kwargs in ({"stride": 1}, {"stride": 0x80000}, {"firmware_start": 0x180000}):
        with pytest.raises(ValueError):
            BackgroundLayout(1280, 720, **kwargs)


def test_background_ownership_waits_for_reader_acquisition():
    layout = BackgroundLayout(1280, 720)
    dut = BackgroundExchange(layout)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        assert ctx.get(dut.writable)
        assert ctx.get(dut.draw_base) == 0x40000
        # Model a DMA reader latching a frame base before issuing any requests.
        current_frame = ctx.get(dut.next_base)
        assert current_frame == 0
        for expected_bank in [1, 0, 1, 0]:
            ctx.set(dut.submit, 1)
            await ctx.tick()
            assert ctx.get(dut.busy) and not ctx.get(dut.writable)
            old_bank = ctx.get(dut.front_bank)
            # Repeated submits during arbitrary bus stalls must not release
            # the old buffer or alter the reader's latched frame address.
            pending_base = ctx.get(dut.next_base)
            for _ in range(37):
                await ctx.tick()
                assert not ctx.get(dut.released)
                assert ctx.get(dut.front_bank) == old_bank
                assert ctx.get(dut.next_base) == pending_base
                assert not ctx.get(dut.writable)
            ctx.set(dut.submit, 0)
            candidate = ctx.get(dut.next_base)
            ctx.set(dut.acquire, 1)
            await ctx.tick()
            current_frame = candidate
            assert current_frame == layout.word_bases[expected_bank]
            assert ctx.get(dut.released) and ctx.get(dut.writable)
            assert ctx.get(dut.front_bank) == expected_bank
            assert ctx.get(dut.draw_bank) != expected_bank
            ctx.set(dut.acquire, 0)
            await ctx.tick()
            assert not ctx.get(dut.released)

        # A commit coincident with a frame start cannot retroactively change it.
        candidate = ctx.get(dut.next_base)
        ctx.set(dut.acquire, 1)
        ctx.set(dut.submit, 1)
        await ctx.tick()
        assert ctx.get(dut.busy)
        assert not ctx.get(dut.released)
        assert candidate == layout.word_bases[ctx.get(dut.front_bank)]
        ctx.set(dut.acquire, 0)
        ctx.set(dut.submit, 0)
        await ctx.tick().repeat(10)
        assert ctx.get(dut.busy)
        ctx.set(dut.acquire, 1)
        await ctx.tick()
        assert ctx.get(dut.writable) and ctx.get(dut.released)

    sim.add_testbench(bench)
    sim.run()


def test_static_guides_switch_atomically_without_changing_cal_draw_bank():
    dut = SceneExchange(BackgroundLayout(1280, 720), 16)
    sim = Simulator(dut)
    sim.add_clock(1.3e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    async def bench(ctx):
        cal_bank = 0
        for index, (source, swap) in enumerate([(1, False), (2, False),
                (0, True), (3, False), (4, False), (5, False), (6, False), (1, False), (2, False), (0, True)]):
            old_draw = ctx.get(dut.draw_base)
            ctx.set(dut.static_source, source)
            ctx.set(dut.swap_background, swap)
            ctx.set(dut.payload, index + 1)
            ctx.set(dut.submit, 1)
            await ctx.tick("sync")
            ctx.set(dut.submit, 0)
            ctx.set(dut.static_source, 3)
            ctx.set(dut.payload, 999)
            await ctx.tick("sync").repeat(8)
            cal_bank ^= swap
            expected = {1: 0x200000, 2: 0x240000, 3: 0x2C0000, 4: 0x280000, 5: 0x300000, 6: 0x340000}.get(source, cal_bank * 0x40000)
            assert ctx.get(dut.next_base) == expected
            assert ctx.get(dut.draw_base) == old_draw
            ctx.set(dut.acquire, 1)
            await ctx.tick("sync")
            ctx.set(dut.acquire, 0)
            await ctx.tick("dvi").repeat(5)
            assert ctx.get(dut.busy)
            assert ctx.get(dut.draw_base) == (1-cal_bank)*0x40000
            ctx.set(dut.boundary, 1)
            await ctx.tick("dvi")
            ctx.set(dut.boundary, 0)
            assert ctx.get(dut.published) == index + 1
            await ctx.tick("sync").repeat(5)
            assert not ctx.get(dut.busy)
            assert ctx.get(dut.next_base) == expected
    sim.add_testbench(bench)
    sim.run()
