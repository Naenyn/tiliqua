"""Safety and protocol coverage for firmware-owned REZO persistence."""

import pytest

from amaranth import Module
from amaranth.sim import Simulator
from amaranth_soc import csr
from amaranth_soc.csr.wishbone import WishboneCSRBridge

from tiliqua.test import csr as csr_test
from top.rezo.flash_window import RezoFlashWindowEngine, RezoFlashWindowPeripheral


async def _complete_transfer(ctx, dut, *, rx=0):
    ctx.set(dut.xfer_rx, rx)
    ctx.set(dut.xfer_done, 1)
    await ctx.tick()
    ctx.set(dut.xfer_done, 0)


@pytest.mark.parametrize("slot", range(8))
@pytest.mark.parametrize("sector", range(2))
def test_read_address_is_confined_to_active_slot_options(slot, sector):
    dut = RezoFlashWindowEngine()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        offset = 0x2a5
        ctx.set(dut.boot_slot, slot)
        ctx.set(dut.boot_slot_checked, 1)
        ctx.set(dut.boot_slot_valid, 1)
        ctx.set(dut.operation, dut.OP_READ)
        ctx.set(dut.sector, sector)
        ctx.set(dut.offset, offset)
        ctx.set(dut.start, 1)
        await ctx.tick()
        ctx.set(dut.start, 0)

        while not ctx.get(dut.xfer_start):
            await ctx.tick()
        address = 0x0e0000 + ((slot + 1) << 20) + (sector << 12) + offset
        assert ctx.get(dut.xfer_tx) == (0x03 << 24) | address
        assert ctx.get(dut.xfer_length) == 32
        assert ctx.get(dut.xfer_mask) == 1
        assert ctx.get(dut.xfer_cs) == 1
        await _complete_transfer(ctx, dut)

        assert ctx.get(dut.xfer_start) == 1
        assert ctx.get(dut.xfer_length) == 8
        assert ctx.get(dut.xfer_mask) == 0
        await _complete_transfer(ctx, dut, rx=0x5a)

        assert ctx.get(dut.done) == 1
        assert ctx.get(dut.error) == 0
        assert ctx.get(dut.read_data) == 0x5a

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize(
    "checked,valid", ((0, 0), (1, 0)),
)
def test_invalid_boot_identity_rejects_flash_commands(checked, valid):
    dut = RezoFlashWindowEngine()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.boot_slot_checked, checked)
        ctx.set(dut.boot_slot_valid, valid)
        ctx.set(dut.operation, dut.OP_ERASE)
        ctx.set(dut.start, 1)
        await ctx.tick()
        ctx.set(dut.start, 0)
        await ctx.tick()
        assert ctx.get(dut.busy) == 0
        assert ctx.get(dut.done) == 1
        assert ctx.get(dut.error) == 1
        assert ctx.get(dut.xfer_start) == 0

    sim.add_testbench(bench)
    sim.run()


def test_firmware_sized_wishbone_accesses_reach_flash_window():
    """Exercise the exact 32-bit accesses issued by the RV32 firmware."""
    m = Module()
    dut = RezoFlashWindowPeripheral()
    decoder = csr.Decoder(addr_width=8, data_width=8)
    decoder.add(dut.bus, addr=0, name="flash_window")
    bridge = WishboneCSRBridge(decoder.bus, data_width=32)
    m.submodules += [dut, decoder, bridge]

    sim = Simulator(m)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.boot_slot_checked, 1)
        ctx.set(dut.boot_slot_valid, 1)
        ctx.set(dut.boot_slot, 2)

        # Firmware uses read_volatile::<u32>(FLASH_SLOT), not an 8-bit read.
        slot = await csr_test.wb_transaction(
            ctx, bridge.wb_bus, adr=2, we=0, sel=0b1111)
        assert slot & 0x1f == 0b01011

        # Firmware likewise writes the packed 23-bit command as a u32.
        command = (
            RezoFlashWindowEngine.OP_READ
            | (1 << 2)
            | (0x2a5 << 3)
        )
        await csr_test.wb_transaction(
            ctx, bridge.wb_bus, adr=0, we=1, sel=0b1111,
            dat_w=command)
        for _ in range(8):
            if ctx.get(dut.xfer_start):
                break
            await ctx.tick()
        assert ctx.get(dut.xfer_start) == 1
        assert ctx.get(dut.xfer_tx) == 0x033e12a5

    sim.add_testbench(bench)
    sim.run()
