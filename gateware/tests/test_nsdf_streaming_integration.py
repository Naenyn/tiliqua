"""Real acquisition + shared snapshot + exact score RTL under live audio."""
import numpy as np
from amaranth import Elaboratable, Module
from amaranth.sim import Simulator
from nsdf_filter_budget import coefficients
from nsdf_direct_rtl import NsdfDirect
from top.tuner.experiment.nsdf_acquisition import NsdfAcquisition
from top.tuner.experiment.nsdf_snapshot import NsdfSnapshot


class StreamingProbe(Elaboratable):
    def __init__(self):
        self.acquisition=NsdfAcquisition(coefficients())
        self.snapshot=NsdfSnapshot()
        self.score=NsdfDirect(max_lag=621)

    def elaborate(self,platform):
        m=Module();a=self.acquisition;s=self.snapshot;d=self.score
        m.submodules.acquisition=a;m.submodules.snapshot=s;m.submodules.score=d
        m.d.comb += [a.raw_request.eq(s.read_request),a.raw_address.eq(s.read_address),
            s.read_ready.eq(a.raw_ready),s.read_valid.eq(a.raw_valid),s.read_sample.eq(a.raw_sample),
            s.head.eq(a.head),s.sequence.eq(a.sequence),s.filled.eq(a.filled),
            d.load_valid.eq(s.sample_valid),d.sample.eq(s.sample),s.sample_ready.eq(d.load_ready),
            d.clear.eq(s.start|s.fault),d.start.eq(s.done & ~s.fault)]
        return m


def test_native_snapshot_and_score_while_four_channel_filter_runs():
    dut=StreamingProbe();a=dut.acquisition;s=dut.snapshot;d=dut.score
    rng=np.random.default_rng(714);samples=rng.integers(-18000,18000,(2200,4))
    samples[:,2]=np.rint(15000*np.sin(np.arange(2200)*2*np.pi*7678.1/192000)+7000)
    got=[];window=[];cycles=[]
    async def bench(ctx):
        ctx.set(a.low_ready,1);ctx.set(s.length,674);ctx.set(s.channel,2)
        ctx.set(d.length,674);ctx.set(d.limit,621);ctx.set(d.ready,1)
        batch=0;started=False;start_cycle=0
        for cycle in range(660000):
            ctx.set(a.input_valid,0);ctx.set(s.start,0)
            if batch<len(samples) and cycle>=batch*625//2:
                assert ctx.get(a.input_ready)
                for ch in range(4):ctx.set(getattr(a,f'sample{ch}'),int(samples[batch,ch]))
                ctx.set(a.input_valid,1);batch+=1
            if not started and ctx.get(a.sequence)>=900:
                sequence=ctx.get(a.sequence);window.extend(samples[sequence-674:sequence,2])
                ctx.set(s.start,1);started=True;start_cycle=cycle
            if ctx.get(s.done):
                assert not ctx.get(s.fault)
                cycles.append(cycle-start_cycle)
            if ctx.get(d.valid):got.append((ctx.get(d.lag),ctx.get(d.score)))
            assert not ctx.get(a.overrun)
            if ctx.get(d.done):
                assert cycle-start_cycle<360000 # <6 ms; shared 10-ms slot.
                break
            await ctx.tick()
        else:raise AssertionError('streaming score deadline missed')
        assert ctx.get(a.sequence)>1400 # Acquisition continued during analysis.
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
    x=np.asarray(window,dtype=np.int64);x-=int(np.rint(x.mean()))
    expected=[]
    for lag in range(622):
        first=x[:len(x)-lag];second=x[lag:]
        corr=int(first@second);energy=int(first@first+second@second)
        q=(abs(corr)<<21)//energy
        expected.append((lag,-q if corr<0 else q))
    assert got==expected
    assert len(cycles)==1 and cycles[0]<12000
