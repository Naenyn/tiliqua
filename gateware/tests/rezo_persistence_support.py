"""Shared simulation support for REZO-family persistence contracts."""

from amaranth import Module
from amaranth.sim import Simulator

from tiliqua.periph.eurorack_pmod import _crc32_bzip2


def make_record(journal_type, words, generation=1, corrupt_at=None,
                version=None):
    if version is None:
        version = journal_type.VERSION
    payload = b"".join(int(word & 0xffff).to_bytes(2, "little")
                       for word in words)
    header = (journal_type.MAGIC.to_bytes(4, "little") +
              version.to_bytes(2, "little") +
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
                        raise AssertionError(
                            f"unexpected SPI command {command:#x}")
                elif length == 8 and mask == 1:
                    byte = tx & 0xff
                    if self.mode == "program":
                        self.mem[self.pointer] = \
                            self.mem.get(self.pointer, 0xff) & byte
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
                        raise AssertionError(
                            "read byte outside read/status transaction")
                else:
                    raise AssertionError((length, mask, tx))
                pending = rx
            await ctx.tick()


def run_boot(journal_type, contents, expected_words=None, slot=2,
             state_words=4, journal_kwargs=None):
    dut = journal_type(state_words, **(journal_kwargs or {}))
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
