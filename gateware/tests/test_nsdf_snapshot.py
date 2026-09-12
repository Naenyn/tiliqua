import numpy as np
import pytest
from amaranth.sim import Simulator
from top.tuner.experiment.nsdf_snapshot import NsdfSnapshot


@pytest.mark.parametrize('samples', [
    [0,1], [1,2], [-1,0], [-2,-1], [-32768,32767], [32767]*674,
    [-32768]*604, [-32768]+[32767]*673,
    list(np.random.default_rng(71).integers(-32768,32768,674)),
])
def test_centered_snapshot(samples):
    dut=NsdfSnapshot();samples=np.array(samples,dtype=np.int64);got=[]
    mean=int(np.rint(samples.mean()));expected=samples-mean
    scaled=bool(np.any((expected>32767)|(expected<-32768)))
    if scaled:expected=expected>>1
    async def bench(ctx):
        head=17;oldest=(head-len(samples)+1)%1024
        ctx.set(dut.length,len(samples));ctx.set(dut.head,head)
        ctx.set(dut.channel,3);ctx.set(dut.sequence,1300);ctx.set(dut.filled,1024)
        ctx.set(dut.start,1);await ctx.tick();ctx.set(dut.start,0)
        pending=None
        for cycle in range(20000):
            ctx.set(dut.read_valid,pending is not None)
            if pending is not None:ctx.set(dut.read_sample,pending)
            ctx.set(dut.read_ready,cycle%5!=0);ctx.set(dut.sample_ready,cycle%7!=0)
            pending=None
            if ctx.get(dut.read_request) and ctx.get(dut.read_ready):
                address=ctx.get(dut.read_address);assert address>>10==3
                index=((address&1023)-oldest)%1024;assert index<len(samples)
                pending=int(samples[index])
            if ctx.get(dut.sample_valid) and ctx.get(dut.sample_ready):got.append(ctx.get(dut.sample))
            if ctx.get(dut.done):
                assert not ctx.get(dut.fault);assert ctx.get(dut.mean)==mean
                assert ctx.get(dut.scaled)==scaled
                break
            await ctx.tick()
        else:pytest.fail('snapshot did not complete')
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
    assert got==list(expected)


def test_overwrite_guard_and_reuse():
    dut=NsdfSnapshot()
    async def bench(ctx):
        ctx.set(dut.length,674);ctx.set(dut.filled,1024);ctx.set(dut.sequence,0xffffffff)
        ctx.set(dut.start,1);await ctx.tick();ctx.set(dut.start,0)
        ctx.set(dut.sequence,350);await ctx.tick() # 351 samples later, including wrap.
        assert ctx.get(dut.fault) and ctx.get(dut.done) and not ctx.get(dut.busy)
        ctx.set(dut.start,1);await ctx.tick();ctx.set(dut.start,0)
        assert ctx.get(dut.busy) and not ctx.get(dut.fault)
        ctx.set(dut.cancel,1);await ctx.tick()
        assert ctx.get(dut.fault) and not ctx.get(dut.busy)
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
