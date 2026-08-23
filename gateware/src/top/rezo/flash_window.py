"""Slot-confined SPI flash access for firmware-owned REZO persistence.

Firmware can address only the two 4 KiB option sectors belonging to the
bootloader-validated active slot. It cannot provide a raw flash address or an
arbitrary SPI command, so a firmware defect cannot erase bitstreams or the
bootloader.
"""

from amaranth import Module, Signal, unsigned
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr


class RezoFlashWindowEngine(wiring.Component):
    """Execute byte reads/programs and sector erases in the option window."""

    OP_READ = 1
    OP_PROGRAM = 2
    OP_ERASE = 3
    OPTIONS_BASE_OFFSET = 0x0E0000

    def __init__(self):
        super().__init__({
            "boot_slot": In(unsigned(3)),
            "boot_slot_valid": In(1),
            "boot_slot_checked": In(1),
            "start": In(1),
            "operation": In(unsigned(2)),
            "sector": In(1),
            "offset": In(unsigned(12)),
            "write_data": In(unsigned(8)),
            "busy": Out(1),
            "done": Out(1),
            "error": Out(1),
            "read_data": Out(unsigned(8)),
            "xfer_start": Out(1),
            "xfer_cs": Out(1),
            "xfer_tx": Out(unsigned(32)),
            "xfer_length": Out(unsigned(6)),
            "xfer_mask": Out(unsigned(8)),
            "xfer_rx": In(unsigned(32)),
            "xfer_done": In(1),
        })

    def elaborate(self, platform):
        m = Module()

        operation = Signal.like(self.operation)
        sector = Signal.like(self.sector)
        offset = Signal.like(self.offset)
        write_data = Signal.like(self.write_data)
        done = Signal()
        error = Signal()
        read_data = Signal.like(self.read_data)
        cs_active = Signal()
        flash_address = Signal(unsigned(24))
        options_base = Signal(unsigned(24))

        # options_base = 0xe0000 + (slot + 1) * 0x100000. The option and
        # sector offsets occupy zero bits in the aligned base, so OR avoids a
        # software-controlled 24-bit address adder.
        m.d.comb += [
            options_base.eq(
                ((self.boot_slot + 1) << 20) | self.OPTIONS_BASE_OFFSET),
            flash_address.eq(options_base | (sector << 12) | offset),
            self.done.eq(done),
            self.error.eq(error),
            self.read_data.eq(read_data),
            self.xfer_cs.eq(cs_active),
        ]
        m.d.sync += self.xfer_start.eq(0)

        def start_xfer(data_value, length, mask):
            m.d.sync += [
                self.xfer_tx.eq(data_value),
                self.xfer_length.eq(length),
                self.xfer_mask.eq(mask),
                self.xfer_start.eq(1),
            ]

        with m.FSM(reset="IDLE") as fsm:
            with m.State("IDLE"):
                with m.If(self.start):
                    m.d.sync += [
                        operation.eq(self.operation),
                        sector.eq(self.sector),
                        offset.eq(self.offset),
                        write_data.eq(self.write_data),
                        done.eq(0),
                        error.eq(0),
                    ]
                    with m.If(~self.boot_slot_checked |
                              ~self.boot_slot_valid |
                              (self.operation == 0)):
                        m.d.sync += [done.eq(1), error.eq(1)]
                    with m.Elif(self.operation == self.OP_READ):
                        m.next = "READ-CMD-START"
                    with m.Elif((self.operation == self.OP_PROGRAM) |
                                (self.operation == self.OP_ERASE)):
                        m.next = "WRITE-ENABLE-START"
                    with m.Else():
                        m.d.sync += [done.eq(1), error.eq(1)]

            with m.State("READ-CMD-START"):
                m.d.sync += cs_active.eq(1)
                start_xfer((0x03 << 24) | flash_address, 32, 1)
                m.next = "READ-CMD-WAIT"
            with m.State("READ-CMD-WAIT"):
                with m.If(self.xfer_done):
                    start_xfer(0, 8, 0)
                    m.next = "READ-DATA-WAIT"
            with m.State("READ-DATA-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += [
                        read_data.eq(self.xfer_rx[:8]),
                        cs_active.eq(0),
                        done.eq(1),
                    ]
                    m.next = "IDLE"

            with m.State("WRITE-ENABLE-START"):
                m.d.sync += cs_active.eq(1)
                start_xfer(0x06, 8, 1)
                m.next = "WRITE-ENABLE-WAIT"
            with m.State("WRITE-ENABLE-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += cs_active.eq(0)
                    with m.If(operation == self.OP_PROGRAM):
                        m.next = "PROGRAM-CMD-START"
                    with m.Else():
                        m.next = "ERASE-CMD-START"

            with m.State("PROGRAM-CMD-START"):
                m.d.sync += cs_active.eq(1)
                start_xfer((0x02 << 24) | flash_address, 32, 1)
                m.next = "PROGRAM-CMD-WAIT"
            with m.State("PROGRAM-CMD-WAIT"):
                with m.If(self.xfer_done):
                    start_xfer(write_data, 8, 1)
                    m.next = "PROGRAM-DATA-WAIT"
            with m.State("PROGRAM-DATA-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += cs_active.eq(0)
                    m.next = "POLL-START"

            with m.State("ERASE-CMD-START"):
                m.d.sync += cs_active.eq(1)
                start_xfer((0x20 << 24) | flash_address, 32, 1)
                m.next = "ERASE-CMD-WAIT"
            with m.State("ERASE-CMD-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += cs_active.eq(0)
                    m.next = "POLL-START"

            with m.State("POLL-START"):
                m.d.sync += cs_active.eq(1)
                start_xfer(0x05, 8, 1)
                m.next = "POLL-CMD-WAIT"
            with m.State("POLL-CMD-WAIT"):
                with m.If(self.xfer_done):
                    start_xfer(0, 8, 0)
                    m.next = "POLL-DATA-WAIT"
            with m.State("POLL-DATA-WAIT"):
                with m.If(self.xfer_done):
                    m.d.sync += cs_active.eq(0)
                    with m.If(self.xfer_rx[0]):
                        m.next = "POLL-START"
                    with m.Else():
                        m.d.sync += done.eq(1)
                        m.next = "IDLE"

        m.d.comb += self.busy.eq(~fsm.ongoing("IDLE"))
        return m


class RezoFlashWindowPeripheral(wiring.Component):
    """CSR wrapper around :class:`RezoFlashWindowEngine`."""

    class CommandReg(csr.Register, access="w"):
        operation: csr.Field(csr.action.W, unsigned(2))
        sector: csr.Field(csr.action.W, unsigned(1))
        offset: csr.Field(csr.action.W, unsigned(12))
        data: csr.Field(csr.action.W, unsigned(8))

    class StatusReg(csr.Register, access="r"):
        busy: csr.Field(csr.action.R, unsigned(1))
        done: csr.Field(csr.action.R, unsigned(1))
        error: csr.Field(csr.action.R, unsigned(1))
        data: csr.Field(csr.action.R, unsigned(8))

    class SlotReg(csr.Register, access="r"):
        checked: csr.Field(csr.action.R, unsigned(1))
        valid: csr.Field(csr.action.R, unsigned(1))
        slot: csr.Field(csr.action.R, unsigned(3))

    def __init__(self):
        regs = csr.Builder(addr_width=8, data_width=8)
        self._command = regs.add("command", self.CommandReg(), offset=0x00)
        self._status = regs.add("status", self.StatusReg(), offset=0x04)
        self._slot = regs.add("slot", self.SlotReg(), offset=0x08)
        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__({
            "bus": wiring.In(csr.Signature(
                addr_width=regs.addr_width, data_width=regs.data_width)),
            "boot_slot": In(unsigned(3)),
            "boot_slot_valid": In(1),
            "boot_slot_checked": In(1),
            "xfer_start": Out(1),
            "xfer_cs": Out(1),
            "xfer_tx": Out(unsigned(32)),
            "xfer_length": Out(unsigned(6)),
            "xfer_mask": Out(unsigned(8)),
            "xfer_rx": In(unsigned(32)),
            "xfer_done": In(1),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        m.submodules.engine = engine = RezoFlashWindowEngine()
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        command = self._command
        m.d.comb += [
            engine.boot_slot.eq(self.boot_slot),
            engine.boot_slot_valid.eq(self.boot_slot_valid),
            engine.boot_slot_checked.eq(self.boot_slot_checked),
            engine.start.eq(command.element.w_stb),
            engine.operation.eq(command.f.operation.w_data),
            engine.sector.eq(command.f.sector.w_data),
            engine.offset.eq(command.f.offset.w_data),
            engine.write_data.eq(command.f.data.w_data),
            self._status.f.busy.r_data.eq(engine.busy),
            self._status.f.done.r_data.eq(engine.done),
            self._status.f.error.r_data.eq(engine.error),
            self._status.f.data.r_data.eq(engine.read_data),
            self._slot.f.checked.r_data.eq(self.boot_slot_checked),
            self._slot.f.valid.r_data.eq(self.boot_slot_valid),
            self._slot.f.slot.r_data.eq(self.boot_slot),
            self.xfer_start.eq(engine.xfer_start),
            self.xfer_cs.eq(engine.xfer_cs),
            self.xfer_tx.eq(engine.xfer_tx),
            self.xfer_length.eq(engine.xfer_length),
            self.xfer_mask.eq(engine.xfer_mask),
            engine.xfer_rx.eq(self.xfer_rx),
            engine.xfer_done.eq(self.xfer_done),
        ]
        return m
