import pytest
from amaranth import Module
from amaranth.sim import Simulator
from amaranth_stdio.serial import AsyncSerialRX
from top.intono.experiment.buffered_uart import Peripheral


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


@pytest.mark.parametrize('read_delay', [0, 7, 60])
def test_rx_packets_while_wishbone_reads_drain_fifo(read_delay):
    from amaranth_soc.csr.wishbone import WishboneCSRBridge
    dut = Peripheral(divisor=16)
    m = Module()
    m.submodules.uart = dut
    m.submodules.bridge = bridge = WishboneCSRBridge(dut.bus, data_width=32)
    values = ([73, 80, 1, 1, 0, 1] + [0] * 25 + [101]) * 4
    received = []
    async def sender(ctx):
        ctx.set(dut.pins.rx, 1)
        await ctx.tick().repeat(32)
        for value in values:
            for bit in [0] + [(value >> i) & 1 for i in range(8)] + [1]:
                ctx.set(dut.pins.rx, bit)
                await ctx.tick().repeat(16)
        await ctx.tick().repeat(16 * 20)
        for _ in range(16 * 20 * len(values)):
            if len(received) == len(values):
                break
            await ctx.tick()
        assert received == values
    async def consumer(ctx):
        async def read(addr):
            bus = bridge.wb_bus
            ctx.set(bus.adr, addr // 4)
            ctx.set(bus.sel, 15)
            ctx.set(bus.cyc, 1)
            ctx.set(bus.stb, 1)
            for _ in range(20):
                await ctx.tick()
                if ctx.get(bus.ack):
                    break
            else:
                raise AssertionError('Wishbone read did not complete')
            result = ctx.get(bus.dat_r)
            ctx.set(bus.cyc, 0)
            ctx.set(bus.stb, 0)
            await ctx.tick().repeat(3 + read_delay)
            return result
        while len(received) < len(values):
            if await read(12):
                received.append(await read(4))
    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(consumer, background=True)
    sim.add_testbench(sender)
    sim.run()


def test_rx_queue_retains_packet_and_wraps_without_foreground_reads():
    dut=Peripheral(divisor=16)
    async def bench(ctx):
        ctx.set(dut.pins.rx,1);await ctx.tick().repeat(32)
        async def send(value):
            for bit in [0]+[(value>>i)&1 for i in range(8)]+[1]:
                ctx.set(dut.pins.rx,bit);await ctx.tick().repeat(16)
            await ctx.tick().repeat(16)
        async def read(addr):
            ctx.set(dut.bus.addr,addr);ctx.set(dut.bus.r_stb,1)
            await ctx.tick();value=ctx.get(dut.bus.r_data)
            ctx.set(dut.bus.r_stb,0);await ctx.tick();return value
        for batch in range(4):
            values=[(batch*47+i*13)&255 for i in range(64)]
            for value in values:await send(value)
            for value in values:
                assert await read(12)==1
                assert await read(4)==value
            assert await read(12)==0
    sim=Simulator(dut);sim.add_clock(1e-6);sim.add_testbench(bench);sim.run()
