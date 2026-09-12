"""Isolated exact type-II NSDF frame engine, not connected to TUNER.

Three pipelined products per pair: correlation and both overlap energies.
Serialized restoring divider emits signed Q20 NSDF. Input must already have
its frame mean removed without exceeding signed 16-bit range. No acquisition,
decimation filter, peak selection, or four-channel scheduling is included.
"""
from amaranth import Module, Signal, signed, Mux
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from amaranth.lib.memory import Memory


class NsdfDirect(wiring.Component):
    def __init__(self, frame=674, max_lag=321, shared_load_port=False):
        if not 1 <= max_lag < frame:
            raise ValueError('lag must fit frame')
        self.frame=frame;self.max_lag=max_lag
        self.shared_load_port=shared_load_port
        self.width=32+(frame-1).bit_length()
        super().__init__({
            'clear':In(1),'load_valid':In(1),'load_ready':Out(1),
            'sample':In(signed(16)),'start':In(1),'full':Out(1),
            'length':In(range(frame+1)),'limit':In(range(max_lag+1)),
            'busy':Out(1),'valid':Out(1),'ready':In(1),
            'lag':Out(range(max_lag+1)),'score':Out(signed(22)),
            'done':Out(1)})

    def elaborate(self,platform):
        m=Module();n=self.frame;w=self.width;bits=w+21
        m.submodules.history=mem=Memory(shape=signed(16),depth=n,init=[])
        wr=mem.write_port()
        # A is disabled while loading, so write-through behavior cannot affect
        # a score; allowing it gives the mapper a legal combined RAM port.
        a=mem.read_port(transparent_for=(wr,) if self.shared_load_port else ())
        b=mem.read_port()
        filled=Signal(range(n+1));index=Signal(range(n));retired=Signal(range(n))
        active_n=Signal(range(n+1));active_last=Signal(range(self.max_lag+1))
        config_valid=Signal()
        issue=Signal();rv=Signal();pv=Signal()
        product=Signal(signed(32));ea=Signal(32);eb=Signal(32)
        total=Signal(signed(w));energy=Signal(w+1)
        denominator=Signal(w+1);numerator=Signal(bits)
        remainder=Signal(w+2);quotient=Signal(bits);negative=Signal()
        count=Signal(range(bits));trial=Signal(w+3)
        m.d.comb += [config_valid.eq((self.length>=2) & (self.length<=n) &
                                    (self.limit<self.length) & (self.limit<=self.max_lag)),
            self.full.eq(config_valid & (filled==self.length)),
            self.load_ready.eq(config_valid & ~self.busy & (filled<self.length) & ~self.clear),
            wr.en.eq(self.load_valid & self.load_ready),
            wr.addr.eq(a.addr if self.shared_load_port else filled),wr.data.eq(self.sample),
            a.addr.eq(Mux(self.busy,index,filled) if self.shared_load_port else index),
            b.addr.eq(index+self.lag),a.en.eq(issue),b.en.eq(issue),issue.eq(0),
            trial.eq((remainder<<1)|numerator[-1])]
        m.d.sync += [self.done.eq(0),rv.eq(issue),pv.eq(rv)]
        with m.If(wr.en):m.d.sync += filled.eq(filled+1)
        with m.If(rv):
            m.d.sync += [product.eq(a.data*b.data),ea.eq(a.data*a.data),eb.eq(b.data*b.data)]
        with m.If(pv):
            m.d.sync += [total.eq(total+product),energy.eq(energy+ea+eb),retired.eq(retired+1)]
        with m.FSM() as fsm:
            with m.State('IDLE'):
                with m.If(self.start & self.full):
                    m.d.sync += [self.busy.eq(1),self.lag.eq(0),index.eq(0),retired.eq(0),total.eq(0),energy.eq(0),
                        active_n.eq(self.length),active_last.eq(self.limit)]
                    m.next='PAIRS'
            with m.State('PAIRS'):
                m.d.comb += issue.eq(~self.clear)
                with m.If(index==active_n-self.lag-1):m.next='DRAIN'
                with m.Else():m.d.sync += index.eq(index+1)
            with m.State('DRAIN'):
                with m.If(pv & (retired==active_n-self.lag-1)):m.next='DIV_START'
            with m.State('DIV_START'):
                m.d.sync += [negative.eq(total<0),numerator.eq(Mux(total<0,-total,total)<<21),
                    denominator.eq(energy),remainder.eq(0),quotient.eq(0),count.eq(0)]
                with m.If(energy==0):
                    m.d.sync += [self.score.eq(0),self.valid.eq(1)];m.next='EMIT'
                with m.Else():m.next='DIVIDE'
            with m.State('DIVIDE'):
                m.d.sync += [numerator.eq(numerator<<1),
                    remainder.eq(Mux(trial>=denominator,trial-denominator,trial)),
                    quotient.eq((quotient<<1)|(trial>=denominator))]
                with m.If(count==bits-1):m.next='SIGN'
                with m.Else():m.d.sync += count.eq(count+1)
            with m.State('SIGN'):
                m.d.sync += [self.score.eq(Mux(negative,-quotient,quotient)),self.valid.eq(1)]
                m.next='EMIT'
            with m.State('EMIT'):
                with m.If(self.ready):
                    m.d.sync += self.valid.eq(0)
                    with m.If(self.lag==active_last):
                        m.d.sync += [self.busy.eq(0),self.done.eq(1)];m.next='IDLE'
                    with m.Else():
                        m.d.sync += [self.lag.eq(self.lag+1),index.eq(0),retired.eq(0),total.eq(0),energy.eq(0)]
                        m.next='PAIRS'
        with m.If(self.clear):
            m.d.sync += [filled.eq(0),self.busy.eq(0),self.valid.eq(0),self.done.eq(0),
                self.score.eq(0),self.lag.eq(0),rv.eq(0),pv.eq(0),fsm.state.eq(fsm.encoding['IDLE'])]
        return m
