import numpy as np
import pytest
from amaranth.sim import Simulator
from top.intono.experiment.nsdf_acquisition import NsdfAcquisition
from nsdf_filter_budget import coefficients


@pytest.mark.parametrize('full_filter', [False, True])
def test_filter_and_shared_raw_port(full_filter):
    # Asymmetric taps expose reversed coefficient/sample ordering.
    taps=list(coefficients()) if full_filter else [32768,16384,-8192,4096,2048]
    dut=NsdfAcquisition(taps);rng=np.random.default_rng(19)
    samples=rng.integers(-30000,30000,(1152,4));observed=[]
    async def bench(ctx):
        ctx.set(dut.low_ready,1);next_batch=0;cycle=0;outstanding=None
        ctx.set(dut.raw_request,1)
        while next_batch<len(samples) or ctx.get(dut.busy) or cycle<len(samples)*313+100:
            ctx.set(dut.input_valid,0)
            if next_batch<len(samples) and cycle>=next_batch*313:
                assert ctx.get(dut.input_ready)
                for ch in range(4):ctx.set(getattr(dut,f'sample{ch}'),int(samples[next_batch,ch]))
                ctx.set(dut.input_valid,1);next_batch+=1
            if ctx.get(dut.raw_valid):
                assert outstanding is not None
                seq,ch=outstanding
                assert ctx.get(dut.raw_sample)==samples[seq,ch]
            seq=ctx.get(dut.sequence)
            # Read only a completed batch, away from wraparound overwrite.
            valid=seq>4;requested=seq-3;ch=cycle%4
            ctx.set(dut.raw_request,valid)
            ctx.set(dut.raw_address,((requested%1024)|(ch<<10)) if valid else 0)
            outstanding=(requested,ch) if valid and ctx.get(dut.raw_ready) else None
            if ctx.get(dut.low_valid):
                observed.append((ctx.get(dut.low_sequence),ctx.get(dut.low_channel),ctx.get(dut.low_sample),ctx.get(dut.low_clipped)))
            await ctx.tick();cycle+=1
        assert not ctx.get(dut.overrun)
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
    expected=[]
    for seq in range(32,len(samples)+1,32):
        if seq<len(taps):continue
        for ch in range(4):
            total=sum(int(samples[seq-1-k,ch])*c for k,c in enumerate(taps))
            scaled=(total+(1<<16))>>17
            expected.append((seq,ch,int(np.clip(scaled,-32768,32767)),int(not -32768<=scaled<=32767)))
    assert observed==expected


def test_saturation_and_stalled_consumer():
    dut=NsdfAcquisition([131071]*5)
    async def bench(ctx):
        ctx.set(dut.low_ready,0)
        for seq in range(96):
            assert ctx.get(dut.input_ready)
            for ch in range(4):ctx.set(getattr(dut,f'sample{ch}'),32767)
            ctx.set(dut.input_valid,1)
            await ctx.tick()
            ctx.set(dut.input_valid,0)
            await ctx.tick().repeat(312)
        assert ctx.get(dut.sequence)==96
        assert ctx.get(dut.low_valid)
        assert ctx.get(dut.low_sample)==32767
        assert ctx.get(dut.low_clipped)
        assert ctx.get(dut.overrun)
        # Backpressure preserves the pending result, not a silently newer frame.
        assert ctx.get(dut.low_sequence)==32
        assert ctx.get(dut.low_channel)==0
        ctx.set(dut.low_ready,1)
        await ctx.tick().repeat(100)
        assert not ctx.get(dut.busy)
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
