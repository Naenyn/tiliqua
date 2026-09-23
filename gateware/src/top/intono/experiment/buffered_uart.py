# UART register/RX implementation adapted from LUNA luna_soc/gateware/core/uart.py.
# Copyright (c) 2020-2025 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause
"""Experimental drop-in UART: sixteen register-backed queued transmit bytes.

No new CSRs, IRQs, EBRs or software buffers. TX-ready means queue space, not
wire idle. The serial engine drains independently between foreground visits.
RX, baud divisor and physical output-enable behavior match the original UART.
"""
from amaranth import Array, Module, Signal
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

        rx_buf = Signal(8)
        rx_avail = Signal()
        m.submodules.rx = rx = AsyncSerialRX(divisor=self._init_divisor, divisor_bits=24)
        with m.If(self._rx_data.f.data.r_stb):
            m.d.sync += rx_avail.eq(0)
        with m.If(rx.rdy):
            m.d.sync += [rx_buf.eq(rx.data), rx_avail.eq(1)]
        m.d.comb += [
            rx.i.eq(self.pins.rx), rx.ack.eq(~rx_avail),
            rx.divisor.eq(self._divisor.f.div.data),
            self._rx_data.f.data.r_data.eq(rx_buf),
            self._rx_avail.f.rxe.r_data.eq(rx_avail),
        ]
        return m
