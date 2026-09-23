# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Coherent transfer of slowly changing configuration words."""

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out


class ConfigCDC(wiring.Component):
    """Transfer an entire configuration word without torn multi-bit updates.

    The source snapshots a changed word and holds it stable until the
    destination acknowledges a synchronized request toggle. The destination
    waits one additional clock after seeing that toggle before sampling the
    stable data bus, then returns the acknowledgement. Changes that occur while
    a transfer is pending are coalesced into the next snapshot.
    """

    def __init__(self, width, *, i_domain="sync", o_domain="dvi"):
        self.width = width
        self.i_domain = i_domain
        self.o_domain = o_domain
        super().__init__({
            "i": In(width),
            "o": Out(width),
        })

    def elaborate(self, platform):
        m = Module()

        held = Signal(self.width)
        request = Signal()
        acknowledge = Signal()
        acknowledge_src = Signal()
        request_dst = Signal()
        request_settled = Signal()

        m.submodules.ack_sync = FFSynchronizer(
            acknowledge, acknowledge_src, o_domain=self.i_domain)
        m.submodules.request_sync = FFSynchronizer(
            request, request_dst, o_domain=self.o_domain)

        # Do not modify the held bus until the previous snapshot was consumed.
        with m.If((request == acknowledge_src) & (self.i != held)):
            m.d[self.i_domain] += [
                held.eq(self.i),
                request.eq(~request),
            ]

        # The request synchronizer already gives the held bus time to settle;
        # this extra destination cycle makes that margin explicit.
        m.d[self.o_domain] += request_settled.eq(request_dst)
        with m.If(request_settled != acknowledge):
            m.d[self.o_domain] += [
                self.o.eq(held),
                acknowledge.eq(request_settled),
            ]

        return m
