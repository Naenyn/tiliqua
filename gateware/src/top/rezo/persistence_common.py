# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Shared configuration-flash transport for REZO-family firmware."""

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out

from luna_soc.gateware.core.spiflash.port import SPIControlPort

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
            # Firmware holds the request fields until the next start pulse, so
            # retaining a second copy in this bridge only adds registers.
            self.spi.source.data.eq(self.tx_data),
            self.spi.source.len.eq(self.length),
            self.spi.source.width.eq(1),
            self.spi.source.mask.eq(self.output_mask),
        ]
        m.d.sync += self.done.eq(0)

        # Enforce the W25Q128's CS#-high recovery in hardware. A requested
        # deselect starts a four-cycle holdoff; physical CS and the next
        # transfer remain inactive during that time.
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
