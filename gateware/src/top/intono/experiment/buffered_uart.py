# UART register/RX implementation adapted from LUNA luna_soc/gateware/core/uart.py.
# Copyright (c) 2020-2025 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
"""Drop-in UART: sixteen queued transmit bytes and 64 queued receive bytes.

No new CSRs, IRQs, EBRs or software buffers. TX-ready means queue space, not
wire idle. The serial engine drains independently between foreground visits.
The RX queue accepts a complete profile-transfer packet while foreground work
is busy. Baud divisor and physical output-enable behavior remain unchanged.
"""
from amaranth import Array, Module, Signal, unsigned
from amaranth.lib.memory import Memory
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import connect, flipped
from amaranth_stdio.serial import AsyncSerialRX, AsyncSerialTX
from luna_soc.gateware.core.uart import Peripheral as BasePeripheral


class Peripheral(BasePeripheral):
    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        connect(m, flipped(self.bus), self._bridge.bus)
        m.submodules.tx = tx = AsyncSerialTX(divisor=self._init_divisor, divisor_bits=24)
        queue = Array(Signal(8, name=f"tx_byte_{i}") for i in range(16))
        head = Signal(4)
        tail = Signal(4)
        count = Signal(range(17))
        push = Signal()
        pop = Signal()
        m.d.comb += [
            self._tx_ready.f.txe.r_data.eq(count < 16),
            push.eq(self._tx_data.f.data.w_stb & (count < 16)),
            pop.eq(tx.rdy & (count != 0)),
            tx.data.eq(queue[head]), tx.ack.eq(pop),
            tx.divisor.eq(self._divisor.f.div.data),
            self.pins.tx.o.eq(tx.o), self.pins.tx.oe.eq(~tx.rdy),
        ]
        with m.If(push):
            m.d.sync += [queue[tail].eq(self._tx_data.f.data.w_data), tail.eq(tail + 1)]
        with m.If(pop):
            m.d.sync += head.eq(head + 1)
        with m.If(push & ~pop):
            m.d.sync += count.eq(count + 1)
        with m.Elif(pop & ~push):
            m.d.sync += count.eq(count - 1)

        m.submodules.rx_queue = rx_queue = Memory(
            shape=unsigned(8), depth=64, init=[], attrs={"ram_style": "distributed"})
        rx_read = rx_queue.read_port(domain="comb")
        rx_write = rx_queue.write_port()
        rx_head = Signal(6)
        rx_tail = Signal(6)
        rx_count = Signal(range(65))
        rx_push = Signal()
        rx_pop = Signal()
        m.submodules.rx = rx = AsyncSerialRX(divisor=self._init_divisor, divisor_bits=24)
        # AsyncSerialRX only inserts its own synchronizer when given platform
        # pins. Our provider supplies a logical pin interface instead, so the
        # external UART signal must cross into the system clock here.
        m.submodules.rx_sync = FFSynchronizer(self.pins.rx, rx.i, init=1)
        with m.If(rx_push):
            m.d.sync += rx_tail.eq(rx_tail + 1)
        with m.If(rx_pop):
            m.d.sync += rx_head.eq(rx_head + 1)
        with m.If(rx_push & ~rx_pop):
            m.d.sync += rx_count.eq(rx_count + 1)
        with m.Elif(rx_pop & ~rx_push):
            m.d.sync += rx_count.eq(rx_count - 1)
        m.d.comb += [
            rx.ack.eq(rx_count < 64),
            rx_push.eq(rx.rdy & (rx_count < 64)),
            rx_pop.eq(self._rx_data.f.data.r_stb & (rx_count != 0)),
            rx.divisor.eq(self._divisor.f.div.data),
            rx_read.addr.eq(rx_head), rx_write.addr.eq(rx_tail),
            rx_write.data.eq(rx.data), rx_write.en.eq(rx_push),
            self._rx_data.f.data.r_data.eq(rx_read.data),
            self._rx_avail.f.rxe.r_data.eq(rx_count != 0),
        ]
        return m
