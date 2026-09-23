"""Focused REZOMO CPU command-boundary coverage."""

from amaranth import Module
from amaranth.lib import wiring
from amaranth.sim import Simulator
from amaranth_soc import csr
from amaranth_soc.csr import wishbone

from tiliqua.test import csr as csr_util
from top.rezo.cpu_control import (
    RezoProgramMemory,
    RezomoFirmwareUIState,
    RezomoUIControlPeripheral,
)
from top.rezo.top import _aligned_string_table_layout


def test_rezomo_program_rom_supports_twenty_kibibytes():
    dut = RezoProgramMemory(size=0x5000, init=[0x12345678])
    assert dut._mem.depth == 0x5000 // 4


def test_rezomo_string_tables_have_unique_or_safe_addresses():
    counts = {
        "direction": 4, "walk_style": 2, "walk_drunk": 4,
        "walk_chance": 6, "algorithm": 4, "turing_length": 9,
        "turing_change": 7, "clock_source": 4, "data_source": 4,
        "turing_target": 2, "turing_start": 10, "mode": 2, "nav": 2,
        "preset": 7, "target": 11, "palette": 5, "damp": 5,
        "save": 5, "layout": 4,
    }
    tables = tuple((name, ("",) * count) for name, count in counts.items())
    _ordered, bases, reserved = _aligned_string_table_layout(tables)
    addresses = set()
    for name, count in counts.items():
        for value in range(count):
            for position in range(16):
                address = bases[name] | (value << 4) | position
                assert address not in addresses
                addresses.add(address)
    assert reserved == 2048
    assert max(addresses) < reserved


def test_rezomo_command_port_updates_clock_and_routing_state():
    m = Module()
    ui = RezomoFirmwareUIState()
    dut = RezomoUIControlPeripheral(ui)
    decoder = csr.Decoder(addr_width=28, data_width=8)
    decoder.add(dut.bus, addr=0, name="dut")
    bridge = wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
    m.submodules += [dut, decoder, bridge]

    async def bench(ctx):
        async def command(kind, index, value):
            packed = kind | (index << 6) | ((value & 0xffff) << 11)
            await csr_util.wb_csr_w(
                ctx, dut.bus, bridge.wb_bus, packed, "command")

        await command(18, 0, 1)
        await command(19, 0, 3)
        await command(25, 0, 5)
        await command(34, 0, 247)
        await command(39, 0, 4)
        await command(9, 7, 16)
        await command(30, 1, 0)
        assert ctx.get(ui.clock_mode) == 1
        assert ctx.get(ui.clock_algorithm) == 3
        assert ctx.get(ui.turing_change_index) == 5
        assert ctx.get(ui.turing_change) == 128
        assert ctx.get(ui.internal_clock_rate) == 247
        assert ctx.get(ui.walk_chance_index) == 4
        assert ctx.get(ui.output_sends[7]) == 16
        assert ctx.get(ui.output_routes[1]) == 0b00100
        assert ctx.get(ui.row_dry_include) == 0

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
