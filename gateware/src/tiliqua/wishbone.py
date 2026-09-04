# Copyright (c) 2026
#
# SPDX-License-Identifier: BSD-3-Clause

"""Small Wishbone timing adapters."""

from amaranth import Module, Signal
from amaranth.lib.wiring import Component, In, Out
from amaranth_soc import wishbone


class ResponseBuffer(Component):
    """Register a Wishbone response while leaving requests combinational.

    The downstream request is held active until ``ack`` or ``err`` arrives.
    That response is captured and presented to the upstream master for one
    clock cycle. While the response is being presented, the downstream strobe
    is suppressed so a combinational slave cannot accept the same request a
    second time. The downstream cycle is also released during that response
    cycle, matching the transaction boundary expected by the PSRAM bridge.

    This deliberately inserts one response cycle and one bubble between
    consecutive transfers. It is intended for timing-sensitive control-plane
    buses, where breaking a long slave-to-master response path matters more
    than single-cycle Wishbone throughput.
    """

    def __init__(self, *, addr_width=30, data_width=32, granularity=8,
                 features=frozenset({"cti", "bte", "err"})):
        self._features = frozenset(features)
        signature = wishbone.Signature(
            addr_width=addr_width,
            data_width=data_width,
            granularity=granularity,
            features=self._features,
        )
        super().__init__({
            "upstream": In(signature),
            "downstream": Out(signature),
        })

    def elaborate(self, platform):
        m = Module()

        response_valid = Signal()
        response_data = Signal.like(self.upstream.dat_r)
        if "err" in self._features:
            response_error = Signal()

        m.d.comb += [
            self.downstream.adr.eq(self.upstream.adr),
            self.downstream.dat_w.eq(self.upstream.dat_w),
            self.downstream.sel.eq(self.upstream.sel),
            self.downstream.cyc.eq(self.upstream.cyc & ~response_valid),
            self.downstream.stb.eq(self.upstream.stb & ~response_valid),
            self.downstream.we.eq(self.upstream.we),
            self.downstream.cti.eq(self.upstream.cti),
            self.downstream.bte.eq(self.upstream.bte),
            self.upstream.dat_r.eq(response_data),
        ]
        if "err" in self._features:
            m.d.comb += [
                self.upstream.ack.eq(response_valid & ~response_error),
                self.upstream.err.eq(response_valid & response_error),
            ]
            response_termination = self.downstream.ack | self.downstream.err
        else:
            m.d.comb += self.upstream.ack.eq(response_valid)
            response_termination = self.downstream.ack

        with m.If(response_valid):
            m.d.sync += response_valid.eq(0)
        with m.Elif(
            self.downstream.cyc & self.downstream.stb &
            response_termination
        ):
            m.d.sync += [
                response_valid.eq(1),
                response_data.eq(self.downstream.dat_r),
            ]
            if "err" in self._features:
                m.d.sync += response_error.eq(self.downstream.err)

        return m
