"""Small TRS MIDI receive FIFO for the INTONO SoC.

This is deliberately separate from USB hosting. Reading a 32-bit word pops
one decoded three-byte MIDI message; zero means that the FIFO is empty.
"""

from amaranth import Module, unsigned
from amaranth.lib import wiring, stream
from amaranth.lib.wiring import In, connect
from amaranth_soc import csr
from amaranth.lib.fifo import SyncFIFOBuffered

from tiliqua import midi


class Peripheral(wiring.Component):
    class MidiRead(csr.Register, access="r"):
        msg: csr.Field(csr.action.R, unsigned(32))

    def __init__(self):
        regs = csr.Builder(addr_width=2, data_width=8)
        self._read = regs.add("midi_read", self.MidiRead(), offset=0)
        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__({
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
            "i_midi": In(stream.Signature(midi.MidiMessage)),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        connect(m, wiring.flipped(self.bus), self._bridge.bus)

        m.submodules.fifo = fifo = SyncFIFOBuffered(width=24, depth=8)
        m.d.comb += [
            # Do not stall the UART decoder forever if the foreground is busy.
            # A full FIFO drops new events; it never changes an active route.
            self.i_midi.ready.eq(1),
            fifo.w_data.eq(self.i_midi.payload),
            fifo.w_en.eq(self.i_midi.valid),
            fifo.r_en.eq(self._read.element.r_stb),
        ]
        with m.If(fifo.r_rdy):
            m.d.comb += self._read.f.msg.r_data.eq(fifo.r_data)
        with m.Else():
            m.d.comb += self._read.f.msg.r_data.eq(0)
        return m
