"""Focused REZO CPU command-boundary coverage."""

from amaranth import Module
from amaranth.sim import Simulator
from amaranth_soc import csr
from amaranth_soc.csr import wishbone

from tiliqua.test import csr as csr_util
from top.rezo.cpu_control import RezoFirmwareUIState, RezoUIControlPeripheral


def test_rezo_command_port_updates_row_dry_preference():
    m = Module()
    ui = RezoFirmwareUIState()
    dut = RezoUIControlPeripheral(ui)
    decoder = csr.Decoder(addr_width=28, data_width=8)
    decoder.add(dut.bus, addr=0, name="dut")
    bridge = wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
    m.submodules += [dut, decoder, bridge]

    async def bench(ctx):
        packed = 30 | (1 << 5)
        await csr_util.wb_csr_w(
            ctx, dut.bus, bridge.wb_bus, packed, "command")
        assert ctx.get(ui.row_dry_include) == 0

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
