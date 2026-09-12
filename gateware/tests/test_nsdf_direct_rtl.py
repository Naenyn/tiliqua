import numpy as np
import pytest
from amaranth.sim import Simulator
from nsdf_direct_rtl import NsdfDirect


def run_frame(samples,last,stall=True,capacity=None):
    dut=NsdfDirect(*(capacity or (len(samples),last)));result=[];cycles=0
    async def bench(ctx):
        nonlocal cycles
        ctx.set(dut.length,len(samples));ctx.set(dut.limit,last)
        for sample in samples:
            assert ctx.get(dut.load_ready)
            ctx.set(dut.sample,int(sample));ctx.set(dut.load_valid,1);await ctx.tick()
        ctx.set(dut.load_valid,0);assert ctx.get(dut.full)
        ctx.set(dut.start,1);await ctx.tick();ctx.set(dut.start,0)
        while not ctx.get(dut.done):
            ready=not stall or cycles%7!=0;ctx.set(dut.ready,ready)
            if ctx.get(dut.valid) and ready:
                result.append((ctx.get(dut.lag),ctx.get(dut.score)))
            await ctx.tick();cycles+=1
            assert cycles<2_000_000
        # Verify clearing permits a fresh frame, not just a second start.
        ctx.set(dut.clear,1);await ctx.tick();ctx.set(dut.clear,0)
        assert not ctx.get(dut.full) and not ctx.get(dut.valid) and ctx.get(dut.load_ready)
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
    assert [k for k,_ in result]==list(range(last+1))
    return np.array([v for _,v in result]),cycles


@pytest.mark.parametrize('kind',['random','rails','zero','constant','sine'])
def test_exact_integer_scores(kind):
    n=64;last=31
    samples={'random':np.random.default_rng(27).integers(-32768,32768,n),
        'rails':np.tile([-32768,32767],n//2),'zero':np.zeros(n,dtype=int),
        'constant':np.full(n,32767),'sine':np.rint(30000*np.sin(np.arange(n)*.4)).astype(int)}[kind]
    actual,_=run_frame(samples,last)
    expected=[]
    for lag in range(last+1):
        a=samples[:n-lag].astype(np.int64);b=samples[lag:].astype(np.int64)
        corr=int(np.dot(a,b));energy=int(np.dot(a,a)+np.dot(b,b))
        expected.append(((-1 if corr<0 else 1)*((abs(corr)<<21)//energy)) if energy else 0)
    np.testing.assert_array_equal(actual,expected)


def test_configurable_capacity():
    samples=np.random.default_rng(42).integers(-32768,32768,64)
    actual,_=run_frame(samples,25,capacity=(96,47))
    expected,_=run_frame(samples,25)
    np.testing.assert_array_equal(actual,expected)


@pytest.mark.parametrize('cancel_cycle',[1,12,70,150])
def test_abort_and_reuse(cancel_cycle):
    dut=NsdfDirect(64,31)
    async def bench(ctx):
        ctx.set(dut.length,64);ctx.set(dut.limit,31)
        for attempt in range(2):
            for _ in range(64):
                ctx.set(dut.sample,32767);ctx.set(dut.load_valid,1);await ctx.tick()
            ctx.set(dut.load_valid,0);ctx.set(dut.start,1);await ctx.tick();ctx.set(dut.start,0)
            if attempt==0:
                for _ in range(cancel_cycle):await ctx.tick()
                ctx.set(dut.clear,1);await ctx.tick();ctx.set(dut.clear,0)
                assert not ctx.get(dut.busy) and not ctx.get(dut.valid)
            else:
                ctx.set(dut.ready,1);count=0
                for _ in range(10000):
                    if ctx.get(dut.valid):
                        assert ctx.get(dut.score)==1<<20
                        assert ctx.get(dut.lag)==count
                        count+=1
                    await ctx.tick()
                    if ctx.get(dut.done):break
                assert count==32
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
