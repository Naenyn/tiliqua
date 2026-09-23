"""Continuous four-lane level acquisition and calibration-output isolation."""
from amaranth.hdl import Fragment
from amaranth.sim import Simulator

from tiliqua.dsp.tuner import TunerPeripheral


def test_level_transport_has_no_pitch_detector_submodule():
    dut = TunerPeripheral(
        sample_rate=192000, multichannel=True, with_reference=False,
        level_window_log2=5,
    )
    fragment = Fragment.get(dut, None)
    names = [name for _, name, *_ in fragment.subfragments]
    assert "period_verifier" not in names
    assert all("pitch" not in (name or "") for name in names)


def test_four_inputs_keep_independent_levels():
    dut = TunerPeripheral(
        sample_rate=3200, multichannel=True, with_reference=False,
        level_window_log2=5, dc_filter_shift=20,
    )
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    amplitudes = [200, 400, 800, 1600]

    async def select(ctx, channel):
        ctx.set(dut.bus.addr, 0)
        ctx.set(dut.bus.w_data, channel)
        ctx.set(dut.bus.w_stb, 1)
        await ctx.tick()
        ctx.set(dut.bus.w_stb, 0)
        await ctx.tick().repeat(2)

    async def bench(ctx):
        ctx.set(dut.i.valid, 1)
        for n in range(128):
            for channel, amplitude in enumerate(amplitudes):
                ctx.set(dut.i.payload[channel].as_value(), amplitude if n % 8 < 4 else -amplitude)
            await ctx.tick()
        ctx.set(dut.i.valid, 0)
        for channel, amplitude in enumerate(amplitudes):
            await select(ctx, channel)
            assert ctx.get(dut._mean_square.f.value.r_data) == amplitude * amplitude
            assert ctx.get(dut._minimum.f.value.r_data) == (-amplitude) & 0xffffffff
            assert ctx.get(dut._maximum.f.value.r_data) == amplitude
            assert ctx.get(dut._level_sequence.f.sequence.r_data) > 0

    sim.add_testbench(bench)
    sim.run()


def test_calibration_command_preserves_level_sample_clock():
    dut = TunerPeripheral(
        sample_rate=3200, multichannel=True, with_reference=False,
        level_window_log2=5, dc_filter_shift=20,
    )
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def write(ctx, address, value, size=1):
        for offset in range(size):
            ctx.set(dut.bus.addr, address + offset)
            ctx.set(dut.bus.w_data, (value >> (8 * offset)) & 255)
            ctx.set(dut.bus.w_stb, 1)
            await ctx.tick()
            ctx.set(dut.bus.w_stb, 0)
            await ctx.tick()
        await ctx.tick().repeat(2)

    async def bench(ctx):
        ctx.set(dut.i.valid, 1)
        for n in range(160):
            for channel in range(4):
                ctx.set(dut.i.payload[channel].as_value(), 400 if n % 16 >= 8 else -400)
            await ctx.tick()
        ctx.set(dut.i.valid, 0)
        clock = ctx.get(dut._sample_clock.f.value.r_data)
        assert clock == 160
        command = 4000 | (3 << 16) | (1 << 18) | (2 << 19) | (17 << 21)
        await write(ctx, 0x5c, command, 4)
        assert ctx.get(dut.cal_active) == 0
        ctx.set(dut.reference_advance, 1)
        await ctx.tick().repeat(3)
        assert ctx.get(dut.cal_value) == 4000
        assert ctx.get(dut.cal_channel) == 3
        assert ctx.get(dut._cal_status.f.value.r_data) == (256 | 17)
        assert ctx.get(dut._sample_clock.f.value.r_data) == clock

    sim.add_testbench(bench)
    sim.run()
