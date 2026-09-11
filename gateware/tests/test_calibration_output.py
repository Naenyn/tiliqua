from amaranth.sim import Simulator
from tiliqua.dsp.calibration_output import CalibrationOutput


def test_performance_commands_ack_without_resetting_audio_measurements():
    dut = CalibrationOutput(watchdog_cycles=20)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.advance, 1)
        for token, performance in [(1, True), (2, True), (3, False), (4, True)]:
            ctx.set(dut.command, 4000 | (1 << 18) | (token << 21) | (int(performance) << 29))
            ctx.set(dut.write, 1)
            await ctx.tick()
            ctx.set(dut.write, 0)
            assert ctx.get(dut.changed) == int(not performance)
            await ctx.tick()
            assert ctx.get(dut.token) == token
            assert ctx.get(dut.value) == 4000 and ctx.get(dut.active)
        await ctx.tick().repeat(21)
        assert ctx.get(dut.fault) and not ctx.get(dut.active)
        assert ctx.get(dut.value) == 0

    sim.add_testbench(bench)
    sim.run()


def test_calibration_output_ack_watchdog_bounds_and_rearm():
    dut = CalibrationOutput(watchdog_cycles=12)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def write(ctx, value=4000, enable=True, token=1):
        ctx.set(dut.command, (value & 0xffff) | (3<<16) | (int(enable)<<18) | (2<<19) | (token<<21))
        ctx.set(dut.write,1)
        await ctx.tick()
        ctx.set(dut.write,0)

    async def bench(ctx):
        assert ctx.get(dut.active)==0
        await write(ctx)
        await ctx.tick().repeat(2)
        assert ctx.get(dut.active)==0 and ctx.get(dut.token)==0
        ctx.set(dut.advance,1)
        assert ctx.get(dut.changed)==1 and ctx.get(dut.input)==2
        await ctx.tick()
        assert ctx.get(dut.active)==1 and ctx.get(dut.value)==4000
        assert ctx.get(dut.channel)==3 and ctx.get(dut.token)==1
        for _ in range(4):
            await write(ctx)
            assert ctx.get(dut.changed)==0
            await ctx.tick().repeat(3)
            assert ctx.get(dut.active)==1
        await ctx.tick().repeat(14)
        assert ctx.get(dut.active)==0 and ctx.get(dut.value)==0 and ctx.get(dut.fault)==1
        await write(ctx, token=2)
        await ctx.tick().repeat(2)
        assert ctx.get(dut.active)==0  # enabled writes cannot clear a fault
        await write(ctx, value=0,enable=False,token=3)
        await ctx.tick().repeat(2)
        assert ctx.get(dut.fault)==0 and ctx.get(dut.token)==3
        await write(ctx,value=8000,token=4)
        await ctx.tick().repeat(2)
        assert ctx.get(dut.value)==8000
        await write(ctx,value=20001,token=5)
        assert ctx.get(dut.fault)==1 and ctx.get(dut.active)==0
    sim.add_testbench(bench)
    sim.run()


def test_signed_envelope_all_payloads_and_negative_watchdog():
    dut = CalibrationOutput(watchdog_cycles=8)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def command(ctx, bits, enabled=True):
        ctx.set(dut.command, bits | (int(enabled)<<18) | (2<<16) | (1<<19) | (7<<21))
        ctx.set(dut.write, 1)
        await ctx.tick()
        ctx.set(dut.write, 0)
        await ctx.tick()

    async def bench(ctx):
        ctx.set(dut.advance, 1)
        for bits in range(65536):
            await command(ctx, 0, False)
            await command(ctx, bits)
            signed = bits if bits < 32768 else bits-65536
            valid = -20000 <= signed <= 20000
            assert ctx.get(dut.fault) == int(not valid), signed
            assert ctx.get(dut.active) == int(valid), signed
            assert ctx.get(dut.value) == (bits if valid else 0), signed
            if valid:
                assert ctx.get(dut.channel) == 2
                assert ctx.get(dut.input) == 1
        await command(ctx, 0, False)
        await command(ctx, (-20000) & 0xffff)
        await ctx.tick().repeat(10)
        assert ctx.get(dut.fault) == 1
        assert ctx.get(dut.value) == 0
        await command(ctx, 4000)
        assert ctx.get(dut.active) == 0

    sim.add_testbench(bench)
    sim.run()
