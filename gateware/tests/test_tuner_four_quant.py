from amaranth.sim import Simulator
from tiliqua.dsp.tuner import TunerPeripheral


def test_four_cv_outputs_fault_isolation_and_cal_priority():
    dut = TunerPeripheral(sample_rate=192000, multichannel=True,
                          with_reference=False, with_legacy_pitch=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        async def write(address, value):
            for byte in range(4):
                ctx.set(dut.bus.addr, address + byte)
                ctx.set(dut.bus.w_data, (value >> (byte * 8)) & 255)
                ctx.set(dut.bus.w_stb, 1)
                await ctx.tick()
            ctx.set(dut.bus.w_stb, 0)
            await ctx.tick().repeat(3)

        ctx.set(dut.i.valid, 1)
        ctx.set(dut.reference_advance, 1)
        values = [-12000, -4000, 4000, 16000]
        for n, value in enumerate(values):
            ctx.set(dut.i.payload[n].as_value(), value)
        await ctx.tick().repeat(64)
        for n, value in enumerate(values):
            packed = ctx.get(dut._quant_cv[n].f.value.r_data)
            assert packed >> 31 and packed & 65535 == value & 65535
            await write(0x90 + n * 4, (value & 65535) | (1 << 18) | ((n + 1) << 21) | (1 << 29))
            assert all(ctx.get(dut.quant_value[i]) == 0 for i in range(4))
        await write(0xb0, 1)
        for n, value in enumerate(values):
            assert ctx.get(dut.quant_value[n]) == value & 65535
            assert ctx.get(dut._quant_status[n].f.value.r_data) == 256 + n + 1
        # Stage a second frame. No lane changes until the common DAC edge;
        # pending frames cannot be overwritten under DAC backpressure.
        ctx.set(dut.reference_advance, 0)
        for n in range(4):
            await write(0x90+4*n, (1000+n) | (1 << 18) | (10 << 21) | (1 << 29))
            assert [ctx.get(dut.quant_value[i]) for i in range(4)] == [v & 65535 for v in values]
        await write(0xb0, 1)
        await write(0x90, 9000 | (1 << 18) | (11 << 21))
        assert [ctx.get(dut.quant_value[i]) for i in range(4)] == [v & 65535 for v in values]
        ctx.set(dut.reference_advance, 1)
        await ctx.tick()
        values = [1000+n for n in range(4)]
        assert [ctx.get(dut.quant_value[i]) for i in range(4)] == values
        for n in range(4):
            assert ctx.get(dut._quant_status[n].f.value.r_data) == 266
        # A bad command faults just its own output, not its neighbors.
        await write(0x94, 25000 | (1 << 18))
        assert ctx.get(dut.quant_value[1]) == 0
        assert ctx.get(dut._quant_status[1].f.value.r_data) & 512
        for n in [0, 2, 3]:
            assert ctx.get(dut.quant_value[n]) == values[n] & 65535
        # Calibration owns only OUT0; other quantizer outputs keep running.
        await write(0x5c, 8000 | (1 << 18) | (1 << 21))
        assert ctx.get(dut.cal_active)
        assert ctx.get(dut.quant_value[0]) == 0
        for n in [2,3]:
            assert ctx.get(dut.quant_value[n]) == values[n]
            await write(0x90 + 4*n, 4000 | (1 << 18))
        await write(0x90, 4000 | (1 << 18))
        await write(0xb0, 1)
        assert ctx.get(dut.quant_value[0]) == 0
        for n in [2,3]:assert ctx.get(dut.quant_value[n]) == 4000
        await write(0x5c, 0)
        assert not ctx.get(dut.cal_active)
        assert ctx.get(dut.quant_value[0]) == 0  # no surprise rearming
        for n in [2,3]:assert ctx.get(dut.quant_value[n]) == 4000
        await write(0x90, 4000 | (1 << 18))
        assert ctx.get(dut.quant_value[0]) == 0
        await write(0xb0, 1)
        assert ctx.get(dut.quant_value[0]) == 4000

    sim.add_testbench(bench)
    sim.run()
