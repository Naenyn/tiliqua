"""Experimental shared native history and four-channel /32 FIR acquisition.

Not wired to production. One history write port accepts four-sample batches;
one read port is shared by the FIR and a bounded external snapshot reader.
Raw head is published only after all four channel writes. Readers must finish
before their frozen head is overwritten; this block does not freeze live RAM.
"""
from amaranth import Array, Cat, Module, Mux, Signal, signed
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from amaranth.lib.memory import Memory


class NsdfAcquisition(wiring.Component):
    def __init__(self, coefficients):
        self.coefficients=tuple(int(c) for c in coefficients)
        if not 1<=len(self.coefficients)<=1024 or any(not -(1<<17)<=c<(1<<17) for c in self.coefficients):
            raise ValueError('expected up to 1024 signed Q17 taps')
        super().__init__({
            'input_valid':In(1),'input_ready':Out(1),
            **{f'sample{i}':In(signed(16)) for i in range(4)},
            'head':Out(10),'filled':Out(range(1025)),'sequence':Out(32),
            'raw_request':In(1),'raw_address':In(12),'raw_ready':Out(1),
            'raw_valid':Out(1),'raw_sample':Out(signed(16)),
            'low_valid':Out(1),'low_ready':In(1),'low_channel':Out(2),
            'low_sample':Out(signed(16)),'low_sequence':Out(32),
            'low_clipped':Out(1),'overrun':Out(1),'busy':Out(1)})

    def elaborate(self,platform):
        m=Module();taps=len(self.coefficients)
        m.submodules.history=history=Memory(shape=signed(16),depth=4096,init=[])
        write=history.write_port();read=history.read_port()
        m.submodules.coefficients=rom=Memory(shape=signed(18),depth=taps,init=self.coefficients)
        coefficient=rom.read_port()
        batch=Array(Signal(signed(16),name=f'batch{i}') for i in range(4))
        inputs=Array(getattr(self,f'sample{i}') for i in range(4))
        writing=Signal();write_channel=Signal(2);write_head=Signal(10);phase=Signal(5)
        fir_head=Signal(10);fir_sequence=Signal(32);channel=Signal(2)
        index=Signal(range(taps));retired=Signal(range(taps))
        issue=Signal();rv=Signal();pv=Signal();product=Signal(signed(34))
        total=Signal(signed(34+(taps-1).bit_length()))
        rounded=Signal(signed(len(total)+1));scaled=Signal(signed(len(total)+1))
        offset=Signal(10);raw_accepted=Signal()
        m.d.comb += [self.input_ready.eq(~writing),
            write.en.eq(writing),write.addr.eq(Cat(write_head,write_channel)),write.data.eq(batch[write_channel]),
            offset.eq(fir_head-index),issue.eq(0),
            self.raw_ready.eq(~issue),raw_accepted.eq(self.raw_request & self.raw_ready),
            read.addr.eq(Mux(issue,Cat(offset,channel),self.raw_address)),read.en.eq(issue|raw_accepted),
            coefficient.addr.eq(index),coefficient.en.eq(issue),
            self.raw_sample.eq(read.data),rounded.eq(total+(1<<16)),scaled.eq(rounded>>17)]
        m.d.sync += [rv.eq(issue),pv.eq(rv),self.raw_valid.eq(raw_accepted)]
        with m.If(rv):m.d.sync += product.eq(read.data*coefficient.data)
        with m.If(pv):m.d.sync += [total.eq(total+product),retired.eq(retired+1)]
        with m.If(self.input_valid & self.input_ready):
            for i in range(4):m.d.sync += batch[i].eq(inputs[i])
            m.d.sync += [writing.eq(1),write_channel.eq(0)]
        with m.If(writing):
            with m.If(write_channel==3):
                m.d.sync += [writing.eq(0),self.head.eq(write_head),write_head.eq(write_head+1),
                    self.sequence.eq(self.sequence+1),phase.eq(phase+1)]
                with m.If(self.filled<1024):m.d.sync += self.filled.eq(self.filled+1)
            with m.Else():m.d.sync += write_channel.eq(write_channel+1)
        trigger=Signal()
        m.d.comb += trigger.eq(writing & (write_channel==3) & (phase==31) & (self.filled>=taps-1))
        with m.If(trigger & self.busy):m.d.sync += self.overrun.eq(1)
        with m.FSM():
            with m.State('IDLE'):
                with m.If(trigger):
                    m.d.sync += [self.busy.eq(1),fir_head.eq(write_head),fir_sequence.eq(self.sequence+1),
                        channel.eq(0),index.eq(0),retired.eq(0),total.eq(0)]
                    m.next='ISSUE'
            with m.State('ISSUE'):
                m.d.comb += issue.eq(1)
                with m.If(index==taps-1):m.next='DRAIN'
                with m.Else():m.d.sync += index.eq(index+1)
            with m.State('DRAIN'):
                with m.If(pv & (retired==taps-1)):m.next='PUBLISH'
            with m.State('PUBLISH'):
                m.d.sync += [self.low_valid.eq(1),self.low_channel.eq(channel),self.low_sequence.eq(fir_sequence),
                    self.low_clipped.eq((scaled>32767)|(scaled < -32768)),
                    self.low_sample.eq(Mux(scaled>32767,32767,Mux(scaled < -32768,-32768,scaled)))]
                m.next='ACK'
            with m.State('ACK'):
                with m.If(self.low_ready):
                    m.d.sync += self.low_valid.eq(0)
                    with m.If(channel==3):
                        m.d.sync += self.busy.eq(0);m.next='IDLE'
                    with m.Else():
                        m.d.sync += [channel.eq(channel+1),index.eq(0),retired.eq(0),total.eq(0)]
                        m.next='ISSUE'
        return m
