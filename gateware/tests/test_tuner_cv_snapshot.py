from amaranth.sim import Simulator
from tiliqua.dsp.cv_snapshot import CVSnapshot


def test_dc_snapshot_signed_coherent_and_route_clear():
    dut = CVSnapshot(shift=2)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        for value in [-32768, -4000, 0, 4000, 32767]:
            ctx.set(dut.clear, 1)
            await ctx.tick()
            assert ctx.get(dut.packed) >> 31 == 0
            ctx.set(dut.clear, 0)
            ctx.set(dut.sample, value)
            ctx.set(dut.accept, 1)
            for _ in range(3):
                await ctx.tick()
                assert ctx.get(dut.packed) >> 31 == 0
            await ctx.tick()
            packed = ctx.get(dut.packed)
            assert packed >> 31 == 1
            assert packed & 65535 == value & 65535
            ctx.set(dut.accept, 0)
            for _ in range(8):
                await ctx.tick()
                assert ctx.get(dut.packed) == packed
        # Clear wins even on a coincident accepted sample.
        ctx.set(dut.clear, 1)
        ctx.set(dut.accept, 1)
        await ctx.tick()
        assert ctx.get(dut.packed) >> 31 == 0

    sim.add_testbench(bench)
    sim.run()


def test_cv_csr_selection_is_independent_of_tuner_focus_and_rearms_fresh():
    from tiliqua.dsp.tuner import TunerPeripheral
    dut = TunerPeripheral(sample_rate=192000, multichannel=True, with_reference=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        async def select(address, value):
            ctx.set(dut.bus.addr, address)
            ctx.set(dut.bus.w_data, value)
            ctx.set(dut.bus.w_stb, 1)
            await ctx.tick()
            ctx.set(dut.bus.w_stb, 0)
            await ctx.tick().repeat(2)

        ctx.set(dut.i.valid, 1)
        for ch, value in enumerate([-8000, -4000, 4000, 8000]):
            ctx.set(dut.i.payload[ch].as_value(), value)
        for cv_channel in range(4):
            await select(0x78, cv_channel)
            assert ctx.get(dut._cv_sample.f.value.r_data) >> 31 == 0
            await ctx.tick().repeat(64)
            for focus in range(4):
                await select(0, focus)
                packed = ctx.get(dut._cv_sample.f.value.r_data)
                assert packed >> 31 == 1
                assert packed & 65535 == [-8000, -4000, 4000, 8000][cv_channel] & 65535
            # Re-selecting the SAME CV source must also invalidate old data.
            ctx.set(dut.i.valid, 0)
            await select(0x78, cv_channel)
            await ctx.tick().repeat(70)
            assert ctx.get(dut._cv_sample.f.value.r_data) >> 31 == 0
            ctx.set(dut.i.valid, 1)

    sim.add_testbench(bench)
    sim.run()
