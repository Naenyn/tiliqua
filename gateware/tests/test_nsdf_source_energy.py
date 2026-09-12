import numpy as np
import pytest
from amaranth.sim import Simulator
from top.tuner.experiment.nsdf_source_energy import NsdfSourceEnergy


@pytest.mark.parametrize('block_size,blocks,count',[(1,1,9),(8,3,83),(512,40,21504)])
def test_exact_source_moments_and_atomic_publication(block_size,blocks,count):
    dut=NsdfSourceEnergy(block_size,blocks)
    rng=np.random.default_rng(831)
    data=rng.integers(-32768,32768,(count,4),dtype=np.int64)
    data[:,0]=-32768;data[:,1]=32767
    data[:,2]=np.where(np.arange(count)%2,32767,-32768)
    max_cycles=0
    async def bench(ctx):
        nonlocal max_cycles
        published=(0,0,0,0,0,0,0,0,0,0)
        def snapshot():
            return tuple(ctx.get(getattr(dut,n)) for n in
                         ['sequence','samples']+[f'sum{i}' for i in range(4)]+[f'squares{i}' for i in range(4)])
        for index,row in enumerate(data):
            assert ctx.get(dut.input_ready)
            for ch in range(4):ctx.set(getattr(dut,f'sample{ch}'),int(row[ch]))
            ctx.set(dut.input_valid,1);await ctx.tick();ctx.set(dut.input_valid,0)
            cycles=1
            while not ctx.get(dut.input_ready):
                assert snapshot()==published
                await ctx.tick();cycles+=1
                assert cycles<100
            max_cycles=max(max_cycles,cycles)
            if (index+1)%block_size==0:
                x=data[max(0,index+1-block_size*blocks):index+1]
                assert ctx.get(dut.updated)
                assert ctx.get(dut.sequence)==index+1
                assert ctx.get(dut.samples)==len(x)
                assert ctx.get(dut.valid)==(len(x)==block_size*blocks)
                for ch in range(4):
                    assert ctx.get(getattr(dut,f'sum{ch}'))==int(x[:,ch].sum())
                    assert ctx.get(getattr(dut,f'squares{ch}'))==int((x[:,ch]*x[:,ch]).sum())
                published=snapshot()
            else:assert snapshot()==published
            assert not ctx.get(dut.overrun)
        # Even block rollover must fit comfortably before the next 192-kHz
        # input group at 60 MHz (312.5 cycles). No sample-sized history required.
        assert max_cycles<100
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()


def test_overrun_invalidates_and_requires_reset():
    dut=NsdfSourceEnergy(1,1)
    async def bench(ctx):
        ctx.set(dut.input_valid,1);await ctx.tick();ctx.set(dut.input_valid,0)
        while not ctx.get(dut.input_ready):await ctx.tick()
        assert ctx.get(dut.valid)
        ctx.set(dut.input_valid,1);await ctx.tick();await ctx.tick()
        ctx.set(dut.input_valid,0);await ctx.tick().repeat(100)
        assert ctx.get(dut.overrun) and not ctx.get(dut.valid) and not ctx.get(dut.input_ready)
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
