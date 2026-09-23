import pytest
from amaranth import Module
from amaranth.sim import Simulator
from amaranth_stdio.serial import AsyncSerialRX
from top.tuner.experiment.buffered_uart import Peripheral


@pytest.mark.parametrize('divisor', [16, 31])
def test_tx_queue_backpressure_wrap_order_and_baud(divisor):
    dut=Peripheral(divisor=divisor)
    m=Module();m.submodules.uart=dut
    m.submodules.receiver=receiver=AsyncSerialRX(divisor=divisor)
    m.d.comb += [receiver.i.eq(dut.pins.tx.o), receiver.ack.eq(1)]
    received=[]
    async def monitor(ctx):
        while True:
            await ctx.tick()
            if ctx.get(receiver.rdy):
                assert not ctx.get(receiver.err.frame)
                received.append(ctx.get(receiver.data))
    async def bench(ctx):
        ctx.set(dut.pins.rx,1)
        async def write(addr,value):
            ctx.set(dut.bus.addr,addr);ctx.set(dut.bus.w_data,value)
            ctx.set(dut.bus.w_stb,1);await ctx.tick()
            ctx.set(dut.bus.w_stb,0);await ctx.tick()
        async def read(addr):
            ctx.set(dut.bus.addr,addr);ctx.set(dut.bus.r_stb,1)
            await ctx.tick();value=ctx.get(dut.bus.r_data)
            ctx.set(dut.bus.r_stb,0);await ctx.tick()
            return value
        assert await read(8)==1
        assert await read(16)==divisor
        expected=[(i*37)&255 for i in range(100)]
        # Fill sixteen queued bytes plus the active serializer. An illegal
        # extra write while full must not corrupt the retained queue.
        for value in expected[:17]:await write(0,value)
        assert await read(8)==0
        await write(0,255)
        for value in expected[17:]:
            while not await read(8):pass
            await write(0,value)
        await ctx.tick().repeat(divisor*12*18)
        assert received==expected
        assert await read(8)==1
        assert ctx.get(dut.pins.tx.o)==1
        assert ctx.get(dut.pins.tx.oe)==0
    sim=Simulator(m);sim.add_clock(1e-6)
    sim.add_testbench(monitor,background=True);sim.add_testbench(bench);sim.run()


def test_rx_registers_remain_compatible():
    dut=Peripheral(divisor=16)
    async def bench(ctx):
        ctx.set(dut.pins.rx,1);await ctx.tick().repeat(32)
        async def read(addr):
            ctx.set(dut.bus.addr,addr);ctx.set(dut.bus.r_stb,1)
            await ctx.tick();value=ctx.get(dut.bus.r_data)
            ctx.set(dut.bus.r_stb,0);await ctx.tick()
            return value
        assert await read(12)==0
        for value in [0,255,85,170]:
            for bit in [0]+[(value>>i)&1 for i in range(8)]+[1]:
                ctx.set(dut.pins.rx,bit);await ctx.tick().repeat(16)
            await ctx.tick().repeat(16)
            assert await read(12)==1
            assert await read(4)==value
            assert await read(12)==0
    sim=Simulator(dut);sim.add_clock(1e-6);sim.add_testbench(bench);sim.run()
