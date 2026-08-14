# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Lean, CPU-free persistent-state journal for REZO.

The journal is deliberately bounded to the two 4 KiB option sectors belonging
to the bootloader-validated active slot. It never accepts a software-provided
flash address.
"""

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.memory import Memory
from amaranth.lib.wiring import In, Out

from luna_soc.gateware.core.spiflash.port import SPIControlPort


def crc32_bzip2_next(crc, byte):
    """One synthesizable byte update for CRC-32/BZIP2 (before final XOR)."""
    value = crc ^ (byte << 24)
    for _ in range(8):
        shifted = Cat(Const(0, 1), value[:31])
        value = Mux(value[31], shifted ^ 0x04c11db7, shifted)
    return value


def _crc32_bzip2_table():
    """Build the non-reflected CRC table once at gateware generation time."""
    table = []
    for index in range(256):
        value = index << 24
        for _ in range(8):
            value = (((value << 1) & 0xffffffff) ^
                     (0x04c11db7 if value & 0x80000000 else 0))
        table.append(value)
    return table


class SPIFlashTransfer(wiring.Component):
    """Issue one 1-bit-wide transfer through LUNA's configuration-flash PHY."""

    def __init__(self):
        super().__init__({
            "spi": Out(SPIControlPort(32)),
            "start": In(1),
            "chip_select": In(1),
            "tx_data": In(unsigned(32)),
            "length": In(unsigned(6)),
            "output_mask": In(unsigned(8)),
            "rx_data": Out(unsigned(32)),
            "busy": Out(1),
            "done": Out(1),
        })

    def elaborate(self, platform):
        m = Module()
        last_chip_select = Signal()
        cs_recovery = Signal(4)
        cs_ready = Signal()

        m.d.comb += [
            cs_ready.eq(~cs_recovery.any()),
            self.spi.cs.eq(self.chip_select & cs_ready),
            # The journal holds the request fields until the next start pulse,
            # so retaining a second copy in this bridge only adds registers.
            self.spi.source.data.eq(self.tx_data),
            self.spi.source.len.eq(self.length),
            self.spi.source.width.eq(1),
            self.spi.source.mask.eq(self.output_mask),
        ]
        m.d.sync += self.done.eq(0)

        # The CPU flash driver naturally leaves ample software time between
        # commands. This CPU-free bridge must enforce the W25Q128's CS#-high
        # recovery itself. A requested deselect starts a four-cycle holdoff;
        # physical CS and the next transfer remain inactive during that time.
        m.d.sync += last_chip_select.eq(self.chip_select)
        with m.If(last_chip_select & ~self.chip_select):
            m.d.sync += cs_recovery.eq(0b1111)
        with m.Elif(cs_recovery.any()):
            m.d.sync += cs_recovery.eq(cs_recovery >> 1)

        with m.FSM() as fsm:
            m.d.comb += self.busy.eq(~fsm.ongoing("IDLE"))
            with m.State("IDLE"):
                with m.If(self.start):
                    m.next = "SEND"
            with m.State("SEND"):
                m.d.comb += self.spi.source.valid.eq(
                    self.chip_select & cs_ready)
                with m.If(self.chip_select & cs_ready &
                          self.spi.source.ready):
                    m.next = "RECEIVE"
            with m.State("RECEIVE"):
                m.d.comb += self.spi.sink.ready.eq(1)
                with m.If(self.spi.sink.valid):
                    m.d.sync += [
                        self.rx_data.eq(self.spi.sink.data),
                        self.done.eq(1),
                    ]
                    m.next = "IDLE"
        return m

class RezoStateJournal(wiring.Component):
    """Two-sector, CRC-checked, power-loss-safe STREZO state journal."""

    MAGIC = 0x5a525453  # little-endian bytes spell "STRZ"
    VERSION = 5
    LEGACY_VERSION = 4
    OLDEST_VERSION = 3
    HEADER_BYTES = 16
    SECTOR_BYTES = 0x1000
    OPTION_BYTES = 0x2000
    OPTIONS_BASE_OFFSET = 0x0e0000
    SLOT_BYTES = 0x100000
    MAX_STATE_WORDS = 1024

    PURPOSE_BOOT_A = 0
    PURPOSE_BOOT_B = 1
    PURPOSE_LOAD = 2
    PURPOSE_VERIFY = 3

    def __init__(self, state_words, *, legacy_state_words=None,
                 legacy_tail_words=(), oldest_state_words=None,
                 oldest_tail_words=()):
        if not 0 < state_words <= self.MAX_STATE_WORDS:
            raise ValueError("state_words exceeds the reserved 2 KiB payload")
        if legacy_state_words is not None:
            if not 0 < legacy_state_words < state_words:
                raise ValueError("legacy_state_words must precede current state")
            if len(legacy_tail_words) != state_words - legacy_state_words:
                raise ValueError("legacy tail must fill the current state")
        if oldest_state_words is not None:
            if legacy_state_words is None:
                raise ValueError("oldest state requires a legacy state")
            if not 0 < oldest_state_words < legacy_state_words:
                raise ValueError("oldest_state_words must precede legacy state")
            if len(oldest_tail_words) != state_words - oldest_state_words:
                raise ValueError("oldest tail must fill the current state")
        self.state_words = state_words
        self.legacy_state_words = legacy_state_words
        self.legacy_tail_words = tuple(legacy_tail_words)
        self.oldest_state_words = oldest_state_words
        self.oldest_tail_words = tuple(oldest_tail_words)
        self.record_bytes = self.HEADER_BYTES + state_words * 2
        super().__init__({
            "boot_slot": In(unsigned(3)),
            "boot_slot_valid": In(1),
            "boot_slot_checked": In(1),
            "state_read_data": In(unsigned(16)),
            "state_write_data": Out(unsigned(16)),
            # The UI exposes its packed state as a 16-bit circular scan
            # stream. SAVE rotates one word after sampling it; LOAD shifts a
            # validated word in. After state_words SAVE rotations the live
            # state is bit-for-bit unchanged, without a wide address mux.
            "state_shift_enable": Out(1),
            "state_shift_load": Out(1),
            "save_request": In(1),
            "available": Out(1),
            "busy": Out(1),
            "save_done": Out(1),
            "save_error": Out(1),
            "startup_done": Out(1),
            # Abstract one-transfer-at-a-time SPI interface. Keeping the flash
            # protocol separate makes corruption and power-loss tests possible
            # without a bit-level SPI model.
            "xfer_start": Out(1),
            "xfer_cs": Out(1),
            "xfer_tx": Out(unsigned(32)),
            "xfer_length": Out(unsigned(6)),
            "xfer_mask": Out(unsigned(8)),
            "xfer_rx": In(unsigned(32)),
            "xfer_done": In(1),
        })

    @staticmethod
    def _header_prefix_byte(index, state_words, version=None):
        if version is None:
            version = RezoStateJournal.VERSION
        header = Array([
            Const((RezoStateJournal.MAGIC >> (8 * n)) & 0xff, 8)
            for n in range(4)
        ] + [
            Const(version & 0xff, 8),
            Const((version >> 8) & 0xff, 8),
            Const(state_words & 0xff, 8),
            Const((state_words >> 8) & 0xff, 8),
        ])
        return header[index[:3]]

    def elaborate(self, platform):
        m = Module()

        # Allocate only the current payload in BRAM. MAX_STATE_WORDS reserves
        # on-flash format capacity for future features; synthesizing all 1024
        # words now would widen every RAM address for storage we cannot yet use.
        state_init = [0] * self.state_words
        if self.oldest_state_words is not None:
            state_init[self.oldest_state_words:] = self.oldest_tail_words
        elif self.legacy_state_words is not None:
            state_init[self.legacy_state_words:] = self.legacy_tail_words
        state_mem = Memory(shape=unsigned(16), depth=self.state_words,
                           init=state_init, attrs={"ram_style": "block"})
        m.submodules.state_mem = state_mem
        state_r = state_mem.read_port()
        state_w = state_mem.write_port(granularity=8)

        # A single 8 KiBit ROM replaces several fully-unrolled eight-round
        # CRC networks. CRC throughput is still one byte per two sync clocks,
        # which is negligible beside SPI flash transfers and erase latency.
        crc_mem = Memory(shape=unsigned(32), depth=256,
                         init=_crc32_bzip2_table())
        m.submodules.crc_mem = crc_mem
        crc_r = crc_mem.read_port()
        options_base = Signal(unsigned(24))
        scan_sector = Signal()
        scan_purpose = Signal(unsigned(2))
        scan_index = Signal(range(self.record_bytes + 1))
        scan_crc = Signal(unsigned(32), init=0xffffffff)
        scan_header_valid = Signal(init=1)
        scan_version = Signal(unsigned(16))
        scan_declared_words = Signal(unsigned(16))
        scan_record_words = Signal(unsigned(16), init=self.state_words)
        scan_generation = Signal(unsigned(32))
        scan_stored_crc = Signal(unsigned(32))
        scan_valid = Signal()
        active_generation = Signal(unsigned(32))
        active_sector = Signal()
        have_active = Signal()
        save_word = Signal(range(self.state_words + 1))
        save_header_index = Signal(range(13))
        save_byte_phase = Signal()
        program_index = Signal(range(self.record_bytes + 1))
        cs_active = Signal()
        saving = Signal()
        startup_done = Signal()

        scan_address = Signal(unsigned(24))
        m.d.comb += [
            # Both sector and record offsets occupy zero bits in the aligned
            # option base, so OR is exactly equivalent to addition and avoids
            # putting 24-bit adders in the flash-control path.
            scan_address.eq(options_base |
                            Mux(scan_sector, self.SECTOR_BYTES, 0)),
            scan_valid.eq(
                scan_header_valid &
                ((scan_crc ^ 0xffffffff) == scan_stored_crc)),
            self.available.eq(self.boot_slot_valid & startup_done),
            self.busy.eq(saving),
            self.startup_done.eq(startup_done),
            self.xfer_cs.eq(cs_active),
        ]
        m.d.sync += [
            self.xfer_start.eq(0),
            self.save_done.eq(0),
            self.save_error.eq(0),
        ]
        m.d.comb += [
            self.state_shift_enable.eq(0),
            self.state_shift_load.eq(0),
        ]

        # Default memory addressing. Individual states override write enable
        # and data; the read address is prefetch-aware below.
        m.d.comb += [
            state_w.en.eq(0),
            state_w.addr.eq(0),
            state_w.data.eq(0),
            state_r.addr.eq(save_word),
            crc_r.addr.eq(0),
        ]

        def start_xfer(data_value, length, mask):
            m.d.sync += [
                self.xfer_tx.eq(data_value),
                self.xfer_length.eq(length),
                self.xfer_mask.eq(mask),
                self.xfer_start.eq(1),
            ]

        def start_crc(byte_value):
            m.d.comb += crc_r.addr.eq(scan_crc[24:32] ^ byte_value)

        def finish_scan_byte():
            scan_record_bytes = self.HEADER_BYTES + (scan_record_words << 1)
            with m.If(scan_index == scan_record_bytes - 1):
                m.d.sync += cs_active.eq(0)
                m.next = "SCAN-VALIDATE"
            with m.Else():
                m.d.sync += scan_index.eq(scan_index + 1)
                m.next = "SCAN-BYTE-START"

        # Keep the reset state explicit: helper states may be reordered without
        # ever turning a power-up into a flash command.
        with m.FSM(reset="WAIT-SLOT") as fsm:
            with m.State("WAIT-SLOT"):
                with m.If(self.boot_slot_checked):
                    with m.If(self.boot_slot_valid):
                        # options_base = 0xe0000 + (slot + 1) * 0x100000
                        m.d.sync += [
                            options_base.eq(Cat(
                                Const(self.OPTIONS_BASE_OFFSET, 20),
                                self.boot_slot + 1,
                            )),
                            scan_sector.eq(0),
                            scan_purpose.eq(self.PURPOSE_BOOT_A),
                        ]
                        m.next = "SCAN-BEGIN"
                    with m.Else():
                        # Invalid slot identity is safe: use factory defaults
                        # and permanently disable saving for this boot.
                        m.d.sync += startup_done.eq(1)
                        m.next = "IDLE"

            with m.State("SCAN-BEGIN"):
                m.d.sync += [
                    scan_index.eq(0),
                    scan_crc.eq(0xffffffff),
                    scan_header_valid.eq(1),
                    scan_version.eq(0),
                    scan_declared_words.eq(0),
                    scan_record_words.eq(self.state_words),
                    scan_generation.eq(0),
                    scan_stored_crc.eq(0),
                    cs_active.eq(1),
                ]
                start_xfer((0x03 << 24) | scan_address, 32, 1)
                m.next = "SCAN-CMD-WAIT"

            with m.State("SCAN-CMD-WAIT"):
                with m.If(self.xfer_done):
                    m.next = "SCAN-BYTE-START"

            with m.State("SCAN-BYTE-START"):
                start_xfer(0, 8, 0)
                m.next = "SCAN-BYTE-WAIT"

            with m.State("SCAN-BYTE-WAIT"):
                with m.If(self.xfer_done):
                    byte = self.xfer_rx[:8]
                    with m.If(scan_index < 4):
                        expected_magic = self._header_prefix_byte(
                            scan_index, self.state_words)
                        with m.If(byte != expected_magic):
                            m.d.sync += scan_header_valid.eq(0)
                    with m.Elif(scan_index == 4):
                        m.d.sync += scan_version[:8].eq(byte)
                    with m.Elif(scan_index == 5):
                        m.d.sync += scan_version[8:16].eq(byte)
                    with m.Elif(scan_index == 6):
                        m.d.sync += scan_declared_words[:8].eq(byte)
                    with m.Elif(scan_index == 7):
                        record_words = Cat(scan_declared_words[:8], byte)
                        current_header = ((scan_version == self.VERSION) &
                                          (record_words == self.state_words))
                        if self.legacy_state_words is None:
                            valid_header = current_header
                        else:
                            valid_header = current_header | (
                                (scan_version == self.LEGACY_VERSION) &
                                (record_words == self.legacy_state_words))
                            if self.oldest_state_words is not None:
                                valid_header = valid_header | (
                                    (scan_version == self.OLDEST_VERSION) &
                                    (record_words == self.oldest_state_words))
                        with m.If(~valid_header):
                            m.d.sync += scan_header_valid.eq(0)
                        with m.Else():
                            m.d.sync += scan_record_words.eq(record_words)
                    with m.Elif(scan_index < 12):
                        m.d.sync += scan_generation.eq(Cat(
                            scan_generation[8:], byte))
                    with m.Elif(scan_index < 16):
                        m.d.sync += scan_stored_crc.eq(Cat(
                            scan_stored_crc[8:], byte))
                    with m.If((scan_purpose == self.PURPOSE_LOAD) &
                              (scan_index >= self.HEADER_BYTES)):
                        payload_index = scan_index - self.HEADER_BYTES
                        m.d.comb += [
                            state_w.addr.eq(payload_index >> 1),
                            state_w.data.eq(Mux(payload_index[0],
                                               byte << 8, byte)),
                            state_w.en.eq(Mux(payload_index[0], 0b10, 0b01)),
                        ]
                    with m.If((scan_index < 12) | (scan_index >= 16)):
                        start_crc(byte)
                        m.next = "SCAN-CRC-WAIT"
                    with m.Else():
                        finish_scan_byte()

            with m.State("SCAN-CRC-WAIT"):
                m.d.sync += scan_crc.eq((scan_crc << 8) ^ crc_r.data)
                finish_scan_byte()

            with m.State("SCAN-VALIDATE"):
                with m.Switch(scan_purpose):
                    with m.Case(self.PURPOSE_BOOT_A):
                        m.d.sync += [
                            have_active.eq(scan_valid),
                            active_generation.eq(scan_generation),
                            scan_sector.eq(1),
                            scan_purpose.eq(self.PURPOSE_BOOT_B),
                        ]
                        m.next = "SCAN-BEGIN"
                    with m.Case(self.PURPOSE_BOOT_B):
                        with m.If(scan_valid &
                                  (~have_active |
                                   (scan_generation > active_generation))):
                            m.d.sync += [
                                active_sector.eq(1),
                                active_generation.eq(scan_generation),
                                have_active.eq(1),
                                scan_sector.eq(1),
                                scan_purpose.eq(self.PURPOSE_LOAD),
                            ]
                            m.next = "SCAN-BEGIN"
                        with m.Elif(have_active):
                            m.d.sync += [
                                active_sector.eq(0),
                                have_active.eq(1),
                                scan_sector.eq(0),
                                scan_purpose.eq(self.PURPOSE_LOAD),
                            ]
                            m.next = "SCAN-BEGIN"
                        with m.Else():
                            m.d.sync += startup_done.eq(1)
                            m.next = "IDLE"
                    with m.Case(self.PURPOSE_LOAD):
                        with m.If(scan_valid):
                            m.d.sync += save_word.eq(0)
                            m.next = "APPLY-PRIME"
                        with m.Else():
                            # Metadata was valid but the second read was not;
                            # never apply a partial buffer.
                            m.d.sync += startup_done.eq(1)
                            m.next = "IDLE"
                    with m.Case(self.PURPOSE_VERIFY):
                        with m.If(scan_valid &
                                  (scan_generation == active_generation)):
                            m.d.sync += [
                                active_sector.eq(scan_sector),
                                have_active.eq(1),
                                self.save_done.eq(1),
                            ]
                        with m.Else():
                            m.d.sync += self.save_error.eq(1)
                        m.d.sync += saving.eq(0)
                        m.next = "IDLE"

            with m.State("APPLY-PRIME"):
                m.d.comb += state_r.addr.eq(0)
                m.next = "APPLY"

            with m.State("APPLY"):
                m.d.comb += [
                    self.state_write_data.eq(state_r.data),
                    self.state_shift_enable.eq(1),
                    self.state_shift_load.eq(1),
                ]
                with m.If(save_word == self.state_words - 1):
                    m.d.sync += startup_done.eq(1)
                    m.next = "IDLE"
                with m.Else():
                    m.d.comb += state_r.addr.eq(save_word + 1)
                    m.d.sync += save_word.eq(save_word + 1)

            with m.State("IDLE"):
                with m.If(self.save_request & self.boot_slot_valid & startup_done):
                    next_generation = Mux(
                        have_active, active_generation + 1, 1)
                    m.d.sync += [
                        saving.eq(1),
                        scan_sector.eq(Mux(have_active, ~active_sector, 0)),
                        active_generation.eq(next_generation),
                        # Reuse the scan register as a byte shifter so header
                        # serialization does not build two 32-bit byte muxes.
                        scan_generation.eq(next_generation),
                        save_header_index.eq(0),
                        scan_crc.eq(0xffffffff),
                    ]
                    m.next = "SAVE-HEADER-CRC"

            with m.State("SAVE-HEADER-CRC"):
                header_byte = Mux(
                    save_header_index < 8,
                    self._header_prefix_byte(
                        save_header_index, self.state_words),
                    scan_generation[:8])
                start_crc(header_byte)
                with m.If(save_header_index >= 8):
                    m.d.sync += scan_generation.eq(scan_generation >> 8)
                m.next = "SAVE-HEADER-CRC-WAIT"

            with m.State("SAVE-HEADER-CRC-WAIT"):
                    m.d.sync += scan_crc.eq((scan_crc << 8) ^ crc_r.data)
                    with m.If(save_header_index == 11):
                        m.d.sync += save_word.eq(0)
                        m.next = "SAVE-CAPTURE"
                    with m.Else():
                        m.d.sync += save_header_index.eq(save_header_index + 1)
                        m.next = "SAVE-HEADER-CRC"

            with m.State("SAVE-CAPTURE"):
                m.d.comb += [
                    state_w.addr.eq(save_word),
                    state_w.data.eq(self.state_read_data),
                    state_w.en.eq(0b11),
                    self.state_shift_enable.eq(1),
                ]
                with m.If(save_word == self.state_words - 1):
                    m.d.sync += [
                        save_word.eq(0),
                        save_byte_phase.eq(0),
                    ]
                    m.next = "SAVE-CRC-PRIME"
                with m.Else():
                    m.d.sync += save_word.eq(save_word + 1)

            with m.State("SAVE-CRC-PRIME"):
                m.d.comb += state_r.addr.eq(0)
                m.next = "SAVE-CRC-PAYLOAD"

            with m.State("SAVE-CRC-PAYLOAD"):
                payload_byte = Mux(save_byte_phase, state_r.data[8:16],
                                   state_r.data[:8])
                start_crc(payload_byte)
                m.next = "SAVE-CRC-PAYLOAD-WAIT"

            with m.State("SAVE-CRC-PAYLOAD-WAIT"):
                crc_next = (scan_crc << 8) ^ crc_r.data
                m.d.sync += scan_crc.eq(crc_next)
                with m.If(save_byte_phase):
                    with m.If(save_word == self.state_words - 1):
                        m.d.sync += [
                            scan_stored_crc.eq(crc_next ^ 0xffffffff),
                            cs_active.eq(1),
                        ]
                        start_xfer(0x06, 8, 1)
                        m.next = "ERASE-WREN-WAIT"
                    with m.Else():
                        m.d.comb += state_r.addr.eq(save_word + 1)
                        m.d.sync += [
                            save_word.eq(save_word + 1),
                            save_byte_phase.eq(0),
                        ]
                        m.next = "SAVE-CRC-PAYLOAD"
                with m.Else():
                    m.d.sync += save_byte_phase.eq(1)
                    m.next = "SAVE-CRC-PAYLOAD"

            with m.State("ERASE-WREN-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += cs_active.eq(0)
                    m.next = "ERASE-START"

            with m.State("ERASE-START"):
                m.d.sync += cs_active.eq(1)
                start_xfer((0x20 << 24) | scan_address, 32, 1)
                m.next = "ERASE-WAIT"

            with m.State("ERASE-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += cs_active.eq(0)
                    m.next = "ERASE-POLL-START"

            with m.State("ERASE-POLL-START"):
                m.d.sync += cs_active.eq(1)
                start_xfer(0x05, 8, 1)
                m.next = "ERASE-POLL-CMD-WAIT"

            with m.State("ERASE-POLL-CMD-WAIT"):
                with m.If(self.xfer_done):
                    start_xfer(0, 8, 0)
                    m.next = "ERASE-POLL-DATA-WAIT"

            with m.State("ERASE-POLL-DATA-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += cs_active.eq(0)
                    with m.If(self.xfer_rx[0]):
                        m.next = "ERASE-POLL-START"
                    with m.Else():
                        m.d.sync += program_index.eq(0)
                        m.next = "PROGRAM-WREN-START"

            with m.State("PROGRAM-WREN-START"):
                m.d.sync += cs_active.eq(1)
                start_xfer(0x06, 8, 1)
                m.next = "PROGRAM-WREN-WAIT"

            with m.State("PROGRAM-WREN-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += cs_active.eq(0)
                    m.next = "PROGRAM-CMD-START"

            with m.State("PROGRAM-CMD-START"):
                m.d.sync += cs_active.eq(1)
                with m.If(program_index == 0):
                    m.d.sync += scan_generation.eq(active_generation)
                start_xfer((0x02 << 24) | (scan_address | program_index),
                           32, 1)
                m.next = "PROGRAM-CMD-WAIT"

            with m.State("PROGRAM-CMD-WAIT"):
                with m.If(self.xfer_done):
                    m.next = "PROGRAM-BYTE-PREP"

            with m.State("PROGRAM-BYTE-PREP"):
                with m.If(program_index >= self.HEADER_BYTES):
                    m.d.comb += state_r.addr.eq(
                        (program_index - self.HEADER_BYTES) >> 1)
                m.next = "PROGRAM-BYTE-START"

            with m.State("PROGRAM-BYTE-START"):
                payload_index = program_index - self.HEADER_BYTES
                payload_byte = Mux(payload_index[0], state_r.data[8:16],
                                   state_r.data[:8])
                header_byte = Mux(
                    program_index < 8,
                    self._header_prefix_byte(program_index, self.state_words),
                    scan_generation[:8])
                record_byte = Mux(
                    program_index < self.HEADER_BYTES,
                    header_byte, payload_byte)
                start_xfer(record_byte, 8, 1)
                with m.If((program_index >= 8) &
                          (program_index < self.HEADER_BYTES)):
                    with m.If(program_index == 11):
                        m.d.sync += scan_generation.eq(scan_stored_crc)
                    with m.Else():
                        m.d.sync += scan_generation.eq(scan_generation >> 8)
                m.next = "PROGRAM-BYTE-WAIT"

            with m.State("PROGRAM-BYTE-WAIT"):
                with m.If(self.xfer_done):
                    end_record = program_index == self.record_bytes - 1
                    end_page = program_index[:8] == 0xff
                    with m.If(end_record | end_page):
                        m.d.sync += cs_active.eq(0)
                        with m.If(~end_record):
                            m.d.sync += program_index.eq(program_index + 1)
                        m.next = "PROGRAM-POLL-START"
                    with m.Else():
                        m.d.sync += program_index.eq(program_index + 1)
                        m.next = "PROGRAM-BYTE-PREP"

            with m.State("PROGRAM-POLL-START"):
                m.d.sync += cs_active.eq(1)
                start_xfer(0x05, 8, 1)
                m.next = "PROGRAM-POLL-CMD-WAIT"

            with m.State("PROGRAM-POLL-CMD-WAIT"):
                with m.If(self.xfer_done):
                    start_xfer(0, 8, 0)
                    m.next = "PROGRAM-POLL-DATA-WAIT"

            with m.State("PROGRAM-POLL-DATA-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += cs_active.eq(0)
                    with m.If(self.xfer_rx[0]):
                        m.next = "PROGRAM-POLL-START"
                    with m.Elif(program_index == self.record_bytes - 1):
                        m.d.sync += scan_purpose.eq(self.PURPOSE_VERIFY)
                        m.next = "SCAN-BEGIN"
                    with m.Else():
                        m.next = "PROGRAM-WREN-START"

        return m
