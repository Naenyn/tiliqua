"""Experimental two-bank, four-channel NSDF frontend.

Acquisition runs independently of requested analysis. One frame at a time is
centered into the shared score engine. Requests choose a channel and bank;
score backpressure does not stop audio. No CSR or pitch selector is provided.
"""
from amaranth import Cat, Module, Mux, Signal, signed
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from amaranth.lib.memory import Memory
from .nsdf_acquisition import NsdfAcquisition
from .nsdf_snapshot import NsdfSnapshot
from .nsdf_direct import NsdfDirect


class NsdfFrontend(wiring.Component):
    def __init__(self,coefficients):
        self.coefficients=tuple(coefficients)
        super().__init__({
            'input_valid':In(1),'input_ready':Out(1),
            **{f'sample{i}':In(signed(16)) for i in range(4)},
            'start':In(1),'cancel':In(1),'channel':In(2),'low_bank':In(1),
            'ready':Out(1),'busy':Out(1),'done':Out(1),'fault':Out(1),
            'native_filled':Out(range(1025)),'low_filled':Out(range(1025)),
            'score_valid':Out(1),'score_ready':In(1),'lag':Out(range(322)),
            'score':Out(signed(22)),'frame_energy':Out(42),
            'inspect':In(1),'inspect_address':In(10),'inspect_sample':Out(signed(16)),
            'frame_sequence':Out(32),'frame_native_end':Out(32),'frame_channel':Out(2),'frame_low_bank':Out(1),
            'frame_scaled':Out(1),'frame_clipped':Out(1),'overrun':Out(1)})

    def elaborate(self,platform):
        m=Module();m.submodules.acquisition=a=NsdfAcquisition(self.coefficients)
        m.submodules.snapshot=s=NsdfSnapshot();m.submodules.score=d=NsdfDirect()
        m.submodules.low_history=history=Memory(shape=17,depth=4096,init=[])
        write=history.write_port();read=history.read_port()
        write_head=Signal(10);low_head=Signal(10);low_sequence=Signal(32);low_valid=Signal()
        low_native_end=Signal(32)
        accepting=Signal();launch=Signal();snapshot_started=Signal()
        m.d.comb += [a.input_valid.eq(self.input_valid),self.input_ready.eq(a.input_ready),
            a.low_ready.eq(1),write.en.eq(a.low_valid),
            write.addr.eq(Cat(write_head,a.low_channel)),write.data.eq(Cat(a.low_sample,a.low_clipped)),
            self.native_filled.eq(a.filled),self.overrun.eq(a.overrun),
            self.ready.eq(~self.busy & ~a.overrun),accepting.eq(self.start & self.ready & ~self.cancel),
            s.start.eq(launch),s.cancel.eq(self.cancel),s.channel.eq(self.frame_channel),
            s.length.eq(Mux(self.frame_low_bank,604,674)),
            s.head.eq(Mux(self.frame_low_bank,low_head,a.head)),
            s.sequence.eq(Mux(self.frame_low_bank,low_sequence,a.sequence)),
            s.filled.eq(Mux(self.frame_low_bank,self.low_filled,a.filled)),
            a.raw_request.eq(s.read_request & ~self.frame_low_bank),a.raw_address.eq(s.read_address),
            read.addr.eq(s.read_address),read.en.eq(s.read_request & self.frame_low_bank),
            s.read_ready.eq(Mux(self.frame_low_bank,1,a.raw_ready)),
            s.read_valid.eq(Mux(self.frame_low_bank,low_valid,a.raw_valid)),
            s.read_sample.eq(Mux(self.frame_low_bank,read.data[:16].as_signed(),a.raw_sample)),
            s.read_clipped.eq(Mux(self.frame_low_bank,read.data[16],
                (a.raw_sample==32767)|(a.raw_sample==-32768))),
            d.length.eq(s.length),d.limit.eq(Mux(self.frame_low_bank,301,321)),
            d.clear.eq(accepting|self.cancel|s.fault|a.overrun),
            d.load_valid.eq(s.sample_valid),d.sample.eq(s.sample),s.sample_ready.eq(d.load_ready),
            d.start.eq(s.done & ~s.fault),d.ready.eq(self.score_ready),
            d.inspect.eq(self.inspect & ~self.busy & ~accepting & ~self.cancel & ~self.fault),
            d.inspect_address.eq(self.inspect_address),self.inspect_sample.eq(d.inspect_sample),
            self.score_valid.eq(d.valid & ~self.fault),self.score.eq(d.score),self.lag.eq(d.lag),
            self.frame_energy.eq(d.frame_energy),self.frame_scaled.eq(s.scaled),
            self.frame_sequence.eq(s.frame_sequence),self.frame_clipped.eq(s.clipped)]
        for ch in range(4):m.d.comb += getattr(a,f'sample{ch}').eq(getattr(self,f'sample{ch}'))
        m.d.sync += [self.done.eq(0),launch.eq(accepting),low_valid.eq(read.en)]
        with m.If(a.low_valid & (a.low_channel==3)):
            m.d.sync += [low_head.eq(write_head),write_head.eq(write_head+1),low_sequence.eq(low_sequence+1),
                low_native_end.eq(a.low_sequence)]
            with m.If(self.low_filled<1024):m.d.sync += self.low_filled.eq(self.low_filled+1)
        with m.If(accepting):
            m.d.sync += [self.busy.eq(1),self.fault.eq(0),self.frame_channel.eq(self.channel),
                self.frame_low_bank.eq(self.low_bank),snapshot_started.eq(0)]
        # Same edge and published head as NsdfSnapshot freezes. The low-bank
        # count cannot be multiplied by 32: FIR warm-up changes its origin.
        with m.If(launch):m.d.sync += [snapshot_started.eq(1),
            self.frame_native_end.eq(Mux(self.frame_low_bank,low_native_end,a.sequence))]
        with m.If(self.busy & snapshot_started & s.done & s.fault):
            m.d.sync += [self.busy.eq(0),self.fault.eq(1),self.done.eq(1)]
        with m.If(d.done):m.d.sync += [self.busy.eq(0),self.done.eq(1)]
        with m.If(self.cancel | (self.busy & a.overrun)):
            m.d.sync += [self.busy.eq(0),self.fault.eq(1),self.done.eq(1),launch.eq(0)]
        return m
