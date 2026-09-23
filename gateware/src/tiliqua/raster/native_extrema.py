"""Lossless native-sample extrema windows for CPU snapshots."""

from amaranth import Module, Signal, Shape, Value, Mux
from amaranth.lib import data, wiring
from amaranth.lib.wiring import In, Out


class NativeExtrema(wiring.Component):
    """Accumulate every input frame, independently of display/CPU cadence.

    A snapshot freezes all channels together and starts an empty next window.
    A sample arriving on the snapshot clock belongs to the completed window,
    exactly once. An empty snapshot clears valid, not the last output values.
    """

    def __init__(self, *, shape, n_channels=4):
        self.shape = shape
        self.n_channels = n_channels
        raw_shape = Shape(shape.width, signed=shape.signed)
        super().__init__({
            "sample": In(data.ArrayLayout(shape, n_channels)),
            "tick": In(1),
            "snapshot": In(1),
            "valid": Out(1),
            "low": Out(raw_shape).array(n_channels),
            "high": Out(raw_shape).array(n_channels),
        })

    def elaborate(self, platform):
        m = Module()
        occupied = Signal()
        raw_shape = Shape(self.shape.width, signed=self.shape.signed)
        for ch in range(self.n_channels):
            low = Signal(raw_shape, name=f"low{ch}")
            high = Signal(raw_shape, name=f"high{ch}")
            sample = Value.cast(self.sample[ch])
            next_low = Mux(~occupied | (sample < low), sample, low)
            next_high = Mux(~occupied | (sample > high), sample, high)
            with m.If(self.tick):
                m.d.sync += [low.eq(next_low), high.eq(next_high)]
            with m.If(self.snapshot & (occupied | self.tick)):
                m.d.sync += [
                    self.low[ch].eq(Mux(self.tick, next_low, low)),
                    self.high[ch].eq(Mux(self.tick, next_high, high)),
                ]
        with m.If(self.snapshot):
            m.d.sync += [self.valid.eq(occupied | self.tick), occupied.eq(0)]
        with m.Elif(self.tick):
            m.d.sync += occupied.eq(1)
        return m
