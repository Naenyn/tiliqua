"""Experimental block-window source moments; not connected to pitch selection.

One shared square multiplier and a packed 32-bit ring retain sum and sum of
squares for four raw channels. Defaults cover 40*512 native samples (106.7 ms).
Outputs publish atomically only at block boundaries, with an exclusive sample
sequence. A future consumer must check the window's age/alignment; these are
not instantaneous RMS values and must not be substituted for filtered energy.
"""
from amaranth import Array, Module, Signal, signed
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from amaranth.lib.memory import Memory


class NsdfSourceEnergy(wiring.Component):
    def __init__(self,block_size=512,blocks=40):
        if not 1<=block_size<=512 or not 1<=blocks<=40:
            raise ValueError('expected block_size 1..512 and blocks 1..40')
        self.block_size=block_size;self.blocks=blocks
        super().__init__({
            'input_valid':In(1),'input_ready':Out(1),
            **{f'sample{i}':In(signed(16)) for i in range(4)},
            **{f'sum{i}':Out(signed(31)) for i in range(4)},
            **{f'squares{i}':Out(45) for i in range(4)},
            'sequence':Out(32),'samples':Out(range(20481)),
            'valid':Out(1),'updated':Out(1),'overrun':Out(1)})

    def elaborate(self,platform):
        m=Module()
        # Three words per channel/block: signed sum, square low32, square high8.
        # 40 * 4 * 3 = 480 words, avoiding a wide, shallow multi-EBR layout.
        m.submodules.history=history=Memory(shape=32,depth=self.blocks*12,init=[])
        read=history.read_port();write=history.write_port()
        batch=Array(Signal(signed(16)) for _ in range(4))
        sums=Array(Signal(signed(25)) for _ in range(4))
        squares=Array(Signal(40) for _ in range(4))
        totals=Array(Signal(signed(31)) for _ in range(4))
        energies=Array(Signal(45) for _ in range(4))
        channel=Signal(2);position=Signal(range(self.block_size))
        slot=Signal(range(self.blocks));filled=Signal(range(self.blocks+1))
        sequence=Signal(32);busy=Signal();product=Signal(32)
        new_sum=Signal(signed(25));new_squares=Signal(40)
        old_sum=Signal(signed(32));old_squares=Signal(40)
        base=Signal(range(self.blocks*12));word=Signal(2)
        m.d.comb += [self.input_ready.eq(~busy & ~self.overrun),
                    # Explicit shifts avoid allocating DSPs for ring addresses.
                    base.eq((slot<<3)+(slot<<2)+(channel<<1)+channel),read.addr.eq(base+word),
                    read.en.eq(0),write.en.eq(0),write.addr.eq(base+word),write.data.eq(0)]
        m.d.sync += self.updated.eq(0)
        with m.If(self.input_valid & ~self.input_ready):
            # Inputs are pulse-per-batch, not a backpressured ready/valid source.
            # Missing a batch invalidates all later sequence/window metadata.
            m.d.sync += [self.overrun.eq(1),self.valid.eq(0)]
        with m.FSM():
            with m.State('IDLE'):
                with m.If(self.input_valid & self.input_ready):
                    for ch in range(4):m.d.sync += batch[ch].eq(getattr(self,f'sample{ch}'))
                    m.d.sync += [busy.eq(1),channel.eq(0),sequence.eq(sequence+1)]
                    m.next='SQUARE'
            with m.State('SQUARE'):
                m.d.sync += product.eq(batch[channel]*batch[channel]);m.next='ACCUMULATE'
            with m.State('ACCUMULATE'):
                with m.If(position==self.block_size-1):
                    m.d.sync += [new_sum.eq(sums[channel]+batch[channel]),
                                 new_squares.eq(squares[channel]+product),
                                 sums[channel].eq(0),squares[channel].eq(0),word.eq(0)]
                    m.next='READ'
                with m.Else():
                    m.d.sync += [sums[channel].eq(sums[channel]+batch[channel]),
                                 squares[channel].eq(squares[channel]+product)]
                    m.next='NEXT'
            with m.State('READ'):
                m.d.comb += read.en.eq(1);m.next='RECEIVE'
            with m.State('RECEIVE'):
                with m.Switch(word):
                    with m.Case(0):m.d.sync += old_sum.eq(read.data.as_signed())
                    with m.Case(1):m.d.sync += old_squares[:32].eq(read.data)
                    with m.Case(2):m.d.sync += old_squares[32:].eq(read.data[:8])
                with m.If(word==2):m.d.sync += word.eq(0);m.next='UPDATE'
                with m.Else():m.d.sync += word.eq(word+1);m.next='READ'
            with m.State('UPDATE'):
                with m.If(filled==self.blocks):
                    m.d.sync += [totals[channel].eq(totals[channel]+new_sum-old_sum),
                                 energies[channel].eq(energies[channel]+new_squares-old_squares)]
                with m.Else():
                    m.d.sync += [totals[channel].eq(totals[channel]+new_sum),
                                 energies[channel].eq(energies[channel]+new_squares)]
                m.next='WRITE'
            with m.State('WRITE'):
                m.d.comb += write.en.eq(1)
                with m.Switch(word):
                    with m.Case(0):m.d.comb += write.data.eq(new_sum)
                    with m.Case(1):m.d.comb += write.data.eq(new_squares[:32])
                    with m.Case(2):m.d.comb += write.data.eq(new_squares[32:])
                with m.If(word==2):m.next='NEXT'
                with m.Else():m.d.sync += word.eq(word+1)
            with m.State('NEXT'):
                with m.If(channel!=3):m.d.sync += channel.eq(channel+1);m.next='SQUARE'
                with m.Elif(position!=self.block_size-1):
                    m.d.sync += [position.eq(position+1),busy.eq(0)];m.next='IDLE'
                with m.Else():m.next='PUBLISH'
            with m.State('PUBLISH'):
                for ch in range(4):
                    m.d.sync += [getattr(self,f'sum{ch}').eq(totals[ch]),
                                 getattr(self,f'squares{ch}').eq(energies[ch])]
                m.d.sync += [self.sequence.eq(sequence),self.updated.eq(1),
                             position.eq(0),busy.eq(0),slot.eq(slot+1)]
                with m.If(slot==self.blocks-1):m.d.sync += slot.eq(0)
                with m.If(filled<self.blocks):
                    m.d.sync += [filled.eq(filled+1),self.samples.eq((filled+1)*self.block_size)]
                m.d.sync += self.valid.eq((filled>=self.blocks-1)&~self.overrun)
                m.next='IDLE'
        # Error wins even if an unexpected input pulse overlaps publication.
        with m.If(self.input_valid & ~self.input_ready):m.d.sync += self.valid.eq(0)
        return m
