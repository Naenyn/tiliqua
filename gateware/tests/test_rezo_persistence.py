from amaranth import Module
from amaranth.sim import Simulator

from top.rezo.persistence import RezoStateJournal, SPIFlashTransfer
from tiliqua.periph.eurorack_pmod import _crc32_bzip2, _boot_slot_record


def make_record(words, generation=1, corrupt_at=None,
                version=RezoStateJournal.VERSION):
    payload = b"".join(int(word & 0xffff).to_bytes(2, "little")
                       for word in words)
    header = (b"REZO" + version.to_bytes(2, "little") +
              len(words).to_bytes(2, "little") +
              generation.to_bytes(4, "little"))
    crc = _crc32_bzip2(header + payload).to_bytes(4, "little")
    record = bytearray(header + crc + payload)
    if corrupt_at is not None:
        record[corrupt_at] ^= 0x40
    return record


class FlashModel:
    """Transaction-level W25Q model sufficient for the journal protocol."""

    def __init__(self, dut, contents=None):
        self.dut = dut
        self.mem = {} if contents is None else dict(contents)
        self.mode = None
        self.pointer = 0
        self.write_enable = False
        self.last_cs = False
        self.touched = set()
        self.transactions = []

    async def run(self, ctx):
        pending = None
        ctx.set(self.dut.xfer_done, 0)
        while True:
            ctx.set(self.dut.xfer_done, 0)
            cs = bool(ctx.get(self.dut.xfer_cs))
            if self.last_cs and not cs:
                self.mode = None
            self.last_cs = cs

            if pending is not None:
                ctx.set(self.dut.xfer_rx, pending)
                ctx.set(self.dut.xfer_done, 1)
                pending = None
            elif ctx.get(self.dut.xfer_start):
                tx = ctx.get(self.dut.xfer_tx)
                length = ctx.get(self.dut.xfer_length)
                mask = ctx.get(self.dut.xfer_mask)
                self.transactions.append((length, mask, tx))
                rx = 0
                if length == 32 and mask == 1:
                    command = (tx >> 24) & 0xff
                    self.pointer = tx & 0xffffff
                    if command == 0x03:
                        self.mode = "read"
                    elif command == 0x20:
                        assert self.write_enable, self.transactions[-8:]
                        base = self.pointer & ~0xfff
                        for address in range(base, base + 0x1000):
                            self.mem[address] = 0xff
                            self.touched.add(address)
                        self.write_enable = False
                        self.mode = None
                    elif command == 0x02:
                        assert self.write_enable
                        self.mode = "program"
                    else:
                        raise AssertionError(f"unexpected SPI command {command:#x}")
                elif length == 8 and mask == 1:
                    byte = tx & 0xff
                    if self.mode == "program":
                        self.mem[self.pointer] = self.mem.get(self.pointer, 0xff) & byte
                        self.touched.add(self.pointer)
                        self.pointer += 1
                    elif byte == 0x06:
                        self.write_enable = True
                    elif byte == 0x05:
                        self.mode = "status"
                    else:
                        raise AssertionError(f"unexpected SPI byte {byte:#x}")
                elif length == 8 and mask == 0:
                    if self.mode == "read":
                        rx = self.mem.get(self.pointer, 0xff)
                        self.pointer += 1
                    elif self.mode == "status":
                        rx = 0
                    else:
                        raise AssertionError("read byte outside read/status transaction")
                else:
                    raise AssertionError((length, mask, tx))
                pending = rx
            await ctx.tick()


def run_boot(contents, expected_words=None, slot=2, state_words=4,
             journal_kwargs=None):
    dut = RezoStateJournal(state_words, **(journal_kwargs or {}))
    m = Module()
    m.submodules.dut = dut
    flash = FlashModel(dut, contents)
    restored = []

    async def bench(ctx):
        ctx.set(dut.boot_slot, slot)
        ctx.set(dut.boot_slot_valid, 1)
        ctx.set(dut.boot_slot_checked, 1)
        for _ in range(20_000):
            if (ctx.get(dut.state_shift_enable) and
                    ctx.get(dut.state_shift_load)):
                restored.append(ctx.get(dut.state_write_data))
            if ctx.get(dut.startup_done):
                break
            await ctx.tick()
        else:
            raise AssertionError("journal startup did not complete")

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.add_testbench(flash.run, background=True)
    sim.run()
    if expected_words is None:
        assert restored == []
    else:
        assert restored == expected_words
    return flash


def test_boot_slot_record_has_crc_and_slot_identity():
    assert len(_boot_slot_record(4)) == 6
    assert _boot_slot_record(4) != _boot_slot_record(5)
    assert _boot_slot_record(4)[:2] == bytes((1, 4))


def test_state_record_has_future_growth_headroom():
    assert RezoStateJournal.MAX_STATE_WORDS == 1024
    assert RezoStateJournal.HEADER_BYTES + 2 * 1024 <= \
        RezoStateJournal.SECTOR_BYTES


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


def test_each_slot_maps_to_its_own_option_window():
    bases = [RezoStateJournal.OPTIONS_BASE_OFFSET +
             ((slot + 1) * RezoStateJournal.SLOT_BYTES)
             for slot in range(8)]
    assert len(set(bases)) == 8
    for left, right in zip(bases, bases[1:]):
        assert left + RezoStateJournal.OPTION_BYTES <= right


def test_synthesized_slot_address_covers_all_eight_slots():
    for slot in range(8):
        base = RezoStateJournal.OPTIONS_BASE_OFFSET + \
            ((slot + 1) * RezoStateJournal.SLOT_BYTES)
        flash = run_boot({}, slot=slot)
        assert flash.transactions[0] == (32, 1, (0x03 << 24) | base)
        second_command = next(
            transaction for transaction in flash.transactions[1:]
            if transaction[0] == 32)
        assert second_command == (32, 1,
                                  (0x03 << 24) | base |
                                  RezoStateJournal.SECTOR_BYTES)


def test_corrupted_newer_record_falls_back_to_previous_sector():
    slot = 2
    base = 0x0e0000 + ((slot + 1) << 20)
    good_words = [0x1234, 0x5678, 0x9abc, 0xdef0]
    good = make_record(good_words, generation=7)
    corrupt = make_record([1, 2, 3, 4], generation=8, corrupt_at=18)
    contents = {base + n: byte for n, byte in enumerate(good)}
    contents.update({base + 0x1000 + n: byte for n, byte in enumerate(corrupt)})
    run_boot(contents, good_words, slot=slot)


def test_corrupted_only_record_keeps_factory_state():
    slot = 3
    base = 0x0e0000 + ((slot + 1) << 20)
    corrupt = make_record([1, 2, 3, 4], generation=1, corrupt_at=0)
    contents = {base + n: byte for n, byte in enumerate(corrupt)}
    run_boot(contents, expected_words=None, slot=slot)


def test_version_one_record_loads_with_current_tail_defaults():
    slot = 4
    base = 0x0e0000 + ((slot + 1) << 20)
    old_words = [0x1234, 0x5678, 0x9abc, 0xdef0]
    tail = (0x1357, 0x2468)
    record = make_record(old_words, generation=5,
                         version=RezoStateJournal.LEGACY_VERSION)
    contents = {base + n: byte for n, byte in enumerate(record)}
    run_boot(contents, old_words + list(tail), slot=slot, state_words=6,
             journal_kwargs={"legacy_state_words": 4,
                             "legacy_tail_words": tail})


def test_version_three_loads_v2_and_v1_with_progressive_tail_defaults():
    slot = 4
    base = 0x0e0000 + ((slot + 1) << 20)
    v1_words = [0x1111, 0x2222]
    v2_words = [0x3333, 0x4444, 0x5555, 0x6666]
    tail = (0xaaaa, 0xbbbb, 0xcccc, 0xdddd)
    journal_kwargs = {
        "legacy_records": (
            (RezoStateJournal.PREVIOUS_VERSION, 4),
            (RezoStateJournal.LEGACY_VERSION, 2),
        ),
        "legacy_tail_words": tail,
    }

    v2_record = make_record(
        v2_words, generation=6,
        version=RezoStateJournal.PREVIOUS_VERSION)
    v2_contents = {base + n: byte for n, byte in enumerate(v2_record)}
    run_boot(v2_contents, v2_words + list(tail[2:]), slot=slot,
             state_words=6, journal_kwargs=journal_kwargs)

    v1_record = make_record(
        v1_words, generation=5,
        version=RezoStateJournal.LEGACY_VERSION)
    v1_contents = {base + n: byte for n, byte in enumerate(v1_record)}
    run_boot(v1_contents, v1_words + list(tail), slot=slot,
             state_words=6, journal_kwargs=journal_kwargs)


def test_equal_length_v2_record_replaces_repurposed_words_with_defaults():
    slot = 4
    base = 0x0e0000 + ((slot + 1) << 20)
    v2_words = [0x1111, 0x2222, 0x3333, 0x4444]
    record = make_record(
        v2_words, generation=7,
        version=RezoStateJournal.PREVIOUS_VERSION)
    contents = {base + n: byte for n, byte in enumerate(record)}
    run_boot(
        contents, [0x1111, 0xaaaa, 0xbbbb, 0x4444], slot=slot,
        state_words=4,
        journal_kwargs={
            "legacy_records": ((RezoStateJournal.PREVIOUS_VERSION, 4),),
            "legacy_word_defaults": ((1, 0xaaaa), (2, 0xbbbb)),
        })


def test_explicit_save_is_bounded_to_active_slot_option_sector():
    slot = 1
    base = 0x0e0000 + ((slot + 1) << 20)
    dut = RezoStateJournal(4)
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
    assert all(base <= address < base + 0x1000 for address in flash.touched)
    saved = bytes(flash.mem.get(base + n, 0xff) for n in range(24))
    assert saved == make_record(values, generation=1)


def test_record_programming_continues_across_flash_page_boundary():
    slot = 0
    base = RezoStateJournal.OPTIONS_BASE_OFFSET + \
        ((slot + 1) * RezoStateJournal.SLOT_BYTES)
    values = [(0x1234 + n * 0x101) & 0xffff for n in range(130)]
    dut = RezoStateJournal(len(values))
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

    expected = make_record(values, generation=1)
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
