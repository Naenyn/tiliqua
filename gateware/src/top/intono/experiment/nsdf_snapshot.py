"""Two-pass, bounded ring snapshot with exact nearest-even mean removal.

No additional frame RAM: pass one computes mean/extrema, pass two streams
centered samples into the score engine. A live sequence guard invalidates a
snapshot before its oldest sample can be overwritten. Consumers must discard
partial frames on fault/cancel. Ring writes must publish sequence after data.
"""
from amaranth import Cat, Module, Mux, Signal, signed
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out


class NsdfSnapshot(wiring.Component):
    def __init__(self, capacity=674):
        if not 2<=capacity<1024:
            raise ValueError('frame must leave ring overwrite margin')
        self.capacity=capacity
        super().__init__({
            'start':In(1),'cancel':In(1),'length':In(range(capacity+1)),
            'channel':In(2),'head':In(10),'sequence':In(32),'filled':In(range(1025)),
            'read_request':Out(1),'read_address':Out(12),'read_ready':In(1),
            'read_valid':In(1),'read_sample':In(signed(16)),'read_clipped':In(1),
            'sample_valid':Out(1),'sample_ready':In(1),'sample':Out(signed(16)),
            'busy':Out(1),'done':Out(1),'fault':Out(1),
            'frame_sequence':Out(32),'mean':Out(signed(17)),'scaled':Out(1),'clipped':Out(1)})

    def elaborate(self,platform):
        m=Module();width=16+(self.capacity-1).bit_length()
        size=Signal(range(self.capacity+1));channel=Signal(2);oldest=Signal(10)
        index=Signal(range(self.capacity));offset=Signal(10);second=Signal()
        total=Signal(signed(width));lo=Signal(signed(16));hi=Signal(signed(16))
        numerator=Signal(width);quotient=Signal(width);negative=Signal()
        remainder=Signal(11);trial=Signal(12);count=Signal(range(width))
        rounded=Signal(width+1);difference=Signal(signed(17));age=Signal(32)
        fetched=Signal(signed(16));fetched_clipped=Signal()
        m.d.comb += [self.read_request.eq(0),offset.eq(oldest+index),
            self.read_address.eq(Cat(offset,channel)),age.eq(self.sequence-self.frame_sequence),
            trial.eq((remainder<<1)|numerator[-1]),
            rounded.eq(quotient+((2*remainder>size)|((2*remainder==size)&quotient[0]))),
            difference.eq(fetched-self.mean)]
        m.d.sync += self.done.eq(0)
        with m.FSM() as fsm:
            with m.State('IDLE'):
                with m.If(self.start):
                    m.d.sync += [self.fault.eq(0),self.sample_valid.eq(0),self.clipped.eq(0)]
                    with m.If((self.length<2)|(self.length>self.capacity)|(self.filled<self.length)):
                        m.d.sync += [self.fault.eq(1),self.done.eq(1)]
                    with m.Else():
                        m.d.sync += [self.busy.eq(1),size.eq(self.length),channel.eq(self.channel),
                            oldest.eq(self.head-self.length+1),self.frame_sequence.eq(self.sequence),
                            index.eq(0),second.eq(0),total.eq(0),lo.eq(32767),hi.eq(-32768)]
                        m.next='REQUEST'
            with m.State('REQUEST'):
                m.d.comb += self.read_request.eq(~self.cancel)
                with m.If(self.read_ready):m.next='RESPONSE'
            with m.State('RESPONSE'):
                with m.If(self.read_valid):
                    # Keep RAM output/multiplexing out of the arithmetic and
                    # extrema-compare path in the full-chip timing budget.
                    m.d.sync += [fetched.eq(self.read_sample),fetched_clipped.eq(self.read_clipped)]
                    m.next='PROCESS'
            with m.State('PROCESS'):
                    with m.If(second):
                        m.d.sync += [self.sample.eq(Mux(self.scaled,difference>>1,difference)),self.sample_valid.eq(1)]
                        m.next='OUTPUT'
                    with m.Else():
                        m.d.sync += self.clipped.eq(self.clipped|fetched_clipped)
                        m.d.sync += total.eq(total+fetched)
                        with m.If(fetched<lo):m.d.sync += lo.eq(fetched)
                        with m.If(fetched>hi):m.d.sync += hi.eq(fetched)
                        with m.If(index==size-1):m.next='DIV_START'
                        with m.Else():
                            m.d.sync += index.eq(index+1);m.next='REQUEST'
            with m.State('DIV_START'):
                m.d.sync += [numerator.eq(Mux(total<0,-total,total)),negative.eq(total<0),
                    quotient.eq(0),remainder.eq(0),count.eq(0)]
                m.next='DIVIDE'
            with m.State('DIVIDE'):
                m.d.sync += [numerator.eq(numerator<<1),
                    remainder.eq(Mux(trial>=size,trial-size,trial)),quotient.eq((quotient<<1)|(trial>=size))]
                with m.If(count==width-1):m.next='ROUND'
                with m.Else():m.d.sync += count.eq(count+1)
            with m.State('ROUND'):
                m.d.sync += self.mean.eq(Mux(negative,-rounded,rounded));m.next='PREPARE'
            with m.State('PREPARE'):
                m.d.sync += [self.scaled.eq(((hi-self.mean)>32767)|((lo-self.mean)<-32768)),index.eq(0),second.eq(1)]
                m.next='REQUEST'
            with m.State('OUTPUT'):
                with m.If(self.sample_ready):
                    m.d.sync += self.sample_valid.eq(0)
                    with m.If(index==size-1):
                        m.d.sync += [self.busy.eq(0),self.done.eq(1)];m.next='IDLE'
                    with m.Else():
                        m.d.sync += index.eq(index+1);m.next='REQUEST'
        # Reserve one unpublished four-channel batch: a channel's RAM write
        # can precede the common sequence publication by three clocks.
        with m.If(self.busy & (age>=1024-size)):
            m.d.sync += [self.fault.eq(1),self.busy.eq(0),self.done.eq(1),self.sample_valid.eq(0),
                fsm.state.eq(fsm.encoding['IDLE'])]
        with m.If(self.cancel):
            m.d.sync += [self.fault.eq(1),self.busy.eq(0),self.done.eq(1),self.sample_valid.eq(0),
                fsm.state.eq(fsm.encoding['IDLE'])]
        return m
