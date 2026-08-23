"""REZO CPU program-memory bus coverage."""

from amaranth.sim import Simulator

from top.rezo.hybrid_control import RezoProgramMemory


def test_instruction_and_data_ports_read_concurrently():
    words = [0x11223344, 0x55667788, 0x99aabbcc, 0xddeeff00]
    dut = RezoProgramMemory(size=16, init=words)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.ibus.adr, 1)
        ctx.set(dut.ibus.cyc, 1)
        ctx.set(dut.ibus.stb, 1)
        ctx.set(dut.dbus.adr, 2)
        ctx.set(dut.dbus.cyc, 1)
        ctx.set(dut.dbus.stb, 1)
        await ctx.tick()
        assert ctx.get(dut.ibus.ack) == 1
        assert ctx.get(dut.dbus.ack) == 1
        assert ctx.get(dut.ibus.dat_r) == words[1]
        assert ctx.get(dut.dbus.dat_r) == words[2]
        assert ctx.get(dut.ibus.err) == 0
        assert ctx.get(dut.dbus.err) == 0

    sim.add_testbench(bench)
    sim.run()
