"""Behavior shared by every REZO-family persistence journal."""

import pytest

from amaranth import Module
from amaranth.sim import Simulator

from rezo_persistence_support import FlashModel, make_record, run_boot
from top.rezo.persistence import RezoStateJournal as RezomoJournal
from top.rezo.persistence_common import SPIFlashTransfer
from top.rezo.rezo_persistence import RezoStateJournal as RezoJournal
from top.rezo.strezo_persistence import RezoStateJournal as StrezoJournal
from tiliqua.periph.eurorack_pmod import _boot_slot_record


JOURNALS = [
    pytest.param(RezoJournal, id="rezo"),
    pytest.param(RezomoJournal, id="rezomo"),
    pytest.param(StrezoJournal, id="strezo"),
]


def test_boot_slot_record_has_crc_and_slot_identity():
    assert len(_boot_slot_record(4)) == 6
    assert _boot_slot_record(4) != _boot_slot_record(5)
    assert _boot_slot_record(4)[:2] == bytes((1, 4))


@pytest.mark.parametrize("journal_type", JOURNALS)
def test_state_record_has_future_growth_headroom(journal_type):
    assert journal_type.MAX_STATE_WORDS == 1024
    assert journal_type.HEADER_BYTES + 2 * 1024 <= journal_type.SECTOR_BYTES


def test_spi_transfer_enforces_four_cycle_cs_recovery():
    dut = SPIFlashTransfer()
    m = Module()
    m.submodules.dut = dut
    gaps = []

    async def phy(ctx):
        last_cs = False
        tracking_gap = False
        low_cycles = 0
        ctx.set(dut.spi.source.ready, 1)
        ctx.set(dut.spi.sink.valid, 1)
        while True:
            cs = bool(ctx.get(dut.spi.cs))
            if last_cs and not cs:
                tracking_gap = True
                low_cycles = 1
            elif tracking_gap and not cs:
                low_cycles += 1
            elif tracking_gap and cs:
                gaps.append(low_cycles)
                tracking_gap = False
            if ctx.get(dut.spi.source.valid):
                assert cs, "SPI data launched while physical CS was recovering"
            last_cs = cs
            await ctx.tick()

    async def transfer(ctx, value):
        ctx.set(dut.tx_data, value)
        ctx.set(dut.length, 8)
        ctx.set(dut.output_mask, 1)
        ctx.set(dut.start, 1)
        await ctx.tick()
        ctx.set(dut.start, 0)
        for _ in range(30):
            if ctx.get(dut.done):
                return
            await ctx.tick()
        raise AssertionError("SPI transfer did not complete")

    async def bench(ctx):
        for _ in range(5):
            await ctx.tick()
        ctx.set(dut.chip_select, 1)
        await transfer(ctx, 0x06)
        ctx.set(dut.chip_select, 0)
        await ctx.tick()
        ctx.set(dut.chip_select, 1)
        await transfer(ctx, 0x05)
        assert gaps and gaps[0] >= 4

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.add_testbench(phy, background=True)
    sim.run()


@pytest.mark.parametrize("journal_type", JOURNALS)
def test_each_slot_maps_to_its_own_option_window(journal_type):
    bases = [journal_type.OPTIONS_BASE_OFFSET +
             ((slot + 1) * journal_type.SLOT_BYTES)
             for slot in range(8)]
    assert len(set(bases)) == 8
    for left, right in zip(bases, bases[1:]):
        assert left + journal_type.OPTION_BYTES <= right


@pytest.mark.parametrize("journal_type", JOURNALS)
def test_synthesized_slot_address_covers_all_eight_slots(journal_type):
    for slot in range(8):
        base = journal_type.OPTIONS_BASE_OFFSET + \
            ((slot + 1) * journal_type.SLOT_BYTES)
        flash = run_boot(journal_type, {}, slot=slot)
        assert flash.transactions[0] == (32, 1, (0x03 << 24) | base)
        second_command = next(
            transaction for transaction in flash.transactions[1:]
            if transaction[0] == 32)
        assert second_command == (
            32, 1, (0x03 << 24) | base | journal_type.SECTOR_BYTES)


@pytest.mark.parametrize("journal_type", JOURNALS)
def test_corrupted_newer_record_falls_back_to_previous_sector(journal_type):
    slot = 2
    base = journal_type.OPTIONS_BASE_OFFSET + \
        ((slot + 1) * journal_type.SLOT_BYTES)
    good_words = [0x1234, 0x5678, 0x9abc, 0xdef0]
    good = make_record(journal_type, good_words, generation=7)
    corrupt = make_record(
        journal_type, [1, 2, 3, 4], generation=8, corrupt_at=18)
    contents = {base + n: byte for n, byte in enumerate(good)}
    contents.update({base + journal_type.SECTOR_BYTES + n: byte
                     for n, byte in enumerate(corrupt)})
    run_boot(journal_type, contents, good_words, slot=slot)


@pytest.mark.parametrize("journal_type", JOURNALS)
def test_corrupted_only_record_keeps_factory_state(journal_type):
    slot = 3
    base = journal_type.OPTIONS_BASE_OFFSET + \
        ((slot + 1) * journal_type.SLOT_BYTES)
    corrupt = make_record(
        journal_type, [1, 2, 3, 4], generation=1, corrupt_at=0)
    contents = {base + n: byte for n, byte in enumerate(corrupt)}
    run_boot(journal_type, contents, expected_words=None, slot=slot)


@pytest.mark.parametrize("journal_type", JOURNALS)
def test_explicit_save_is_bounded_to_active_slot_option_sector(journal_type):
    slot = 1
    base = journal_type.OPTIONS_BASE_OFFSET + \
        ((slot + 1) * journal_type.SLOT_BYTES)
    dut = journal_type(4)
    m = Module()
    m.submodules.dut = dut
    flash = FlashModel(dut)
    values = [0x1111, 0x2222, 0x3333, 0x4444]

    async def bench(ctx):
        scan_index = 0
        ctx.set(dut.boot_slot, slot)
        ctx.set(dut.boot_slot_valid, 1)
        ctx.set(dut.boot_slot_checked, 1)
        for _ in range(20_000):
            ctx.set(dut.state_read_data, values[scan_index])
            if ctx.get(dut.startup_done):
                break
            await ctx.tick()
        ctx.set(dut.save_request, 1)
        await ctx.tick()
        ctx.set(dut.save_request, 0)
        for _ in range(40_000):
            ctx.set(dut.state_read_data, values[scan_index])
            if (ctx.get(dut.state_shift_enable) and
                    not ctx.get(dut.state_shift_load)):
                scan_index = (scan_index + 1) % len(values)
            if ctx.get(dut.save_done):
                break
            assert not ctx.get(dut.save_error)
            await ctx.tick()
        else:
            raise AssertionError("save did not complete")

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.add_testbench(flash.run, background=True)
    sim.run()

    assert flash.touched
    assert all(base <= address < base + journal_type.SECTOR_BYTES
               for address in flash.touched)
    saved = bytes(flash.mem.get(base + n, 0xff) for n in range(24))
    assert saved == make_record(journal_type, values, generation=1)


@pytest.mark.parametrize("journal_type", JOURNALS)
def test_record_programming_continues_across_flash_page_boundary(journal_type):
    slot = 0
    base = journal_type.OPTIONS_BASE_OFFSET + \
        ((slot + 1) * journal_type.SLOT_BYTES)
    values = [(0x1234 + n * 0x101) & 0xffff for n in range(130)]
    dut = journal_type(len(values))
    m = Module()
    m.submodules.dut = dut
    flash = FlashModel(dut)

    async def bench(ctx):
        scan_index = 0
        ctx.set(dut.boot_slot, slot)
        ctx.set(dut.boot_slot_valid, 1)
        ctx.set(dut.boot_slot_checked, 1)
        for _ in range(20_000):
            if ctx.get(dut.startup_done):
                break
            await ctx.tick()
        else:
            raise AssertionError("journal startup did not complete")

        ctx.set(dut.save_request, 1)
        await ctx.tick()
        ctx.set(dut.save_request, 0)
        for _ in range(80_000):
            ctx.set(dut.state_read_data, values[scan_index])
            if (ctx.get(dut.state_shift_enable) and
                    not ctx.get(dut.state_shift_load)):
                scan_index = (scan_index + 1) % len(values)
            if ctx.get(dut.save_done):
                break
            assert not ctx.get(dut.save_error)
            await ctx.tick()
        else:
            raise AssertionError("multi-page save did not complete")

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.add_testbench(flash.run, background=True)
    sim.run()

    expected = make_record(journal_type, values, generation=1)
    saved = bytes(flash.mem.get(base + n, 0xff)
                  for n in range(len(expected)))
    assert len(expected) > 256
    assert saved == expected
    program_commands = [transaction for transaction in flash.transactions
                        if transaction[0] == 32 and
                        (transaction[2] >> 24) == 0x02]
    assert program_commands == [
        (32, 1, (0x02 << 24) | base),
        (32, 1, (0x02 << 24) | base | 0x100),
    ]
