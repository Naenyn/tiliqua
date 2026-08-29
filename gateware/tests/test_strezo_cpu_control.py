"""Focused STREZO CPU command-boundary coverage."""

from amaranth import Module
from amaranth.sim import Simulator
from amaranth_soc import csr
from amaranth_soc.csr import wishbone

from tiliqua.test import csr as csr_util
from top.rezo.cpu_control import (
    StrezoFirmwareUIState,
    StrezoUIControlPeripheral,
)


def test_strezo_command_port_updates_stereo_and_cross_state():
    m = Module()
    ui = StrezoFirmwareUIState()
    dut = StrezoUIControlPeripheral(ui)
    decoder = csr.Decoder(addr_width=28, data_width=8)
    decoder.add(dut.bus, addr=0, name="dut")
    bridge = wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
    m.submodules += [dut, decoder, bridge]

    async def bench(ctx):
        async def command(kind, index, value):
            packed = kind | (index << 6) | ((value & 0xffff) << 11)
            await csr_util.wb_csr_w(
                ctx, dut.bus, bridge.wb_bus, packed, "command")

        await command(18, 0, 99)
        await command(19, 0, 71)
        await command(23, 0, 1)
        await command(24, 0, 5)
        await command(32, 0, 2)
        await command(35, 0, 127)
        await command(36, 2, 1)
        await command(37, 6, 13)
        await command(38, 0, 87)
        await command(39, 0, 42)
        await command(9, 7, 16)
        assert ctx.get(ui.same_feedback) == 99
        assert ctx.get(ui.cross_feedback) == 71
        assert ctx.get(ui.cross_curve) == 1
        assert ctx.get(ui.cross_layout) == 5
        assert ctx.get(ui.motion_source) == 2
        assert ctx.get(ui.motion_depth) == 127
        assert ctx.get(ui.output_sides[2]) == 1
        assert ctx.get(ui.cross_matrix[6]) == 13
        assert ctx.get(ui.mid_gain) == 87
        assert ctx.get(ui.side_gain) == 42
        assert ctx.get(ui.output_sends[7]) == 16
        assert ctx.get(ui.output_routes[1]) == 0b01111

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()


def test_strezo_firmware_defaults_match_cpu_less_product_state():
    ui = StrezoFirmwareUIState()
    assert [signal.init for signal in ui.band_frequencies] == \
        [4, 16, 24, 36, 48, 60, 76, 88, 100, 112]
    assert [signal.init for signal in ui.input_gains] == \
        [0xCCCC, 0xCCCC, 0, 0]
    assert [signal.init for signal in ui.input_modes] == [0, 1, 2, 2]
    assert [signal.init for signal in ui.output_sides] == [0, 1, 0, 1]
    assert [signal.init for signal in ui.output_sends] == [
        16, 16, 16, 16, 0,
        16, 16, 16, 16, 0,
        16, 0, 16, 0, 0,
        16, 0, 16, 0, 0,
    ]
    assert [signal.init for signal in ui.cross_matrix] == [
        16, 0, 0, 0,
        0, 16, 0, 0,
        0, 0, 16, 0,
        0, 0, 0, 16,
    ]
    assert ui.mid_gain.init == 64
    assert ui.side_gain.init == 64
