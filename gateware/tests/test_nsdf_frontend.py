import numpy as np
import pytest
from amaranth.sim import Simulator
from top.tuner.experiment.nsdf_frontend import NsdfFrontend


@pytest.mark.parametrize('tap_count',[5,37])
def test_low_bank_signed_history_and_scores(tap_count):
    # Short FIR accelerates warm-up only. Full 769-tap / 192-kHz execution is
    # covered by acquisition and streaming-integration tests separately.
    taps=[65536,32768,16384,-8192,4096]+[0]*(tap_count-5)
    warmup_offset=((tap_count+31)//32-1)*32
    dut=NsdfFrontend(taps);rng=np.random.default_rng(6)
    samples=rng.integers(-15000,15000,(23000,4));observed=[];frames=[]
    async def bench(ctx):
        ctx.set(dut.channel,1);ctx.set(dut.low_bank,1);ctx.set(dut.score_ready,1)
        batch=0;next_sample=0;started=False
        for cycle in range(450000):
            ctx.set(dut.start,0);ctx.set(dut.input_valid,0)
            if cycle>=next_sample:
                assert ctx.get(dut.input_ready)
                for ch in range(4):ctx.set(getattr(dut,f'sample{ch}'),int(samples[batch,ch]))
                ctx.set(dut.input_valid,1);batch+=1;next_sample=cycle+(313 if started else 10)
            if not started and ctx.get(dut.low_filled)>=610:
                ctx.set(dut.start,1);started=True
            assert not ctx.get(dut.overrun)
            if ctx.get(dut.score_valid):observed.append((ctx.get(dut.lag),ctx.get(dut.score)))
            if ctx.get(dut.done):
                assert not ctx.get(dut.fault)
                assert ctx.get(dut.frame_channel)==1 and ctx.get(dut.frame_low_bank)
                assert not ctx.get(dut.frame_clipped)
                frames.append((ctx.get(dut.frame_sequence),ctx.get(dut.frame_energy)))
                assert ctx.get(dut.frame_native_end)==ctx.get(dut.frame_sequence)*32+warmup_offset
                break
            await ctx.tick()
        else:raise AssertionError('frontend did not finish')
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
    sequence,energy=frames[0]
    low=[]
    for seq in range((sequence-604)*32+32+warmup_offset,sequence*32+1+warmup_offset,32):
        total=sum(int(samples[seq-1-k,1])*c for k,c in enumerate(taps))
        low.append((total+65536)>>17)
    x=np.asarray(low,dtype=np.int64);x-=int(np.rint(x.mean()))
    assert energy==int(x@x)
    expected=[]
    for lag in range(302):
        first=x[:len(x)-lag];second=x[lag:]
        corr=int(first@second);denom=int(first@first+second@second)
        score=(abs(corr)<<21)//denom
        expected.append((lag,-score if corr<0 else score))
    assert observed==expected


def test_empty_history_fails_without_hanging_and_can_retry():
    dut=NsdfFrontend([131071])
    async def bench(ctx):
        for bank in (0,1,0):
            ctx.set(dut.low_bank,bank);ctx.set(dut.start,1)
            await ctx.tick();ctx.set(dut.start,0)
            for _ in range(10):
                await ctx.tick()
                if ctx.get(dut.done):break
            else:raise AssertionError('unfilled frame request hung')
            assert ctx.get(dut.fault) and ctx.get(dut.ready)
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
