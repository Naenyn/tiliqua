"""Small coherent DC-preserving snapshot; independent of tuner bank selection."""
from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out


class CVSnapshot(wiring.Component):
    def __init__(self, shift=6):
        self.shift = shift
        super().__init__({"sample": In(signed(16)), "accept": In(1),
                          "clear": In(1), "packed": Out(32)})

    def elaborate(self, platform):
        m = Module()
        total = Signal(signed(17 + self.shift))
        index = Signal(self.shift)
        value = Signal(signed(16))
        sequence = Signal(15)
        valid = Signal()
        summed = Signal.like(total)
        m.d.comb += [summed.eq(total + self.sample),
                     self.packed.eq(Cat(value, sequence, valid))]
        with m.If(self.accept):
            m.d.sync += [total.eq(summed), index.eq(index + 1)]
            with m.If(index == (1 << self.shift) - 1):
                m.d.sync += [value.eq(summed >> self.shift), total.eq(0),
                             sequence.eq(sequence + 1), valid.eq(1)]
        with m.If(self.clear):
            m.d.sync += [total.eq(0), index.eq(0), valid.eq(0)]
        return m
