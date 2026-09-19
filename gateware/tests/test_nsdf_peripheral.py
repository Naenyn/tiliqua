"""Exercise byte-wide CSR commands and frozen signed score readback."""
import numpy as np
from amaranth.sim import Simulator
from top.tuner.experiment.nsdf_peripheral import Peripheral


def test_diagnostic_csr_frame_handoff():
    dut=Peripheral();x=np.rint(9000*np.sin(np.arange(700)*2*np.pi*7678.1/192000)+4000).astype(np.int64)
    async def write32(ctx,address,value):
        for byte in range(4):
            ctx.set(dut.bus.addr,address+byte);ctx.set(dut.bus.w_data,(value>>(8*byte))&255)
            ctx.set(dut.bus.w_stb,1);await ctx.tick()
        ctx.set(dut.bus.w_stb,0);await ctx.tick().repeat(3)
    async def read32(ctx,address):
        result=0
        for byte in range(4):
            ctx.set(dut.bus.addr,address+byte);ctx.set(dut.bus.r_stb,1)
            await ctx.tick();result|=ctx.get(dut.bus.r_data)<<(8*byte)
        ctx.set(dut.bus.r_stb,0);await ctx.tick()
        return result
    observed=[]
    async def bench(ctx):
        assert await read32(ctx,32)==0x4e534405
        await write32(ctx,0,1);await ctx.tick().repeat(12)
        assert (await read32(ctx,4))&7==6 # Finished, faulted, not busy.
        for sample in x:
            ctx.set(dut.sample2,int(sample));ctx.set(dut.input_valid,1);await ctx.tick()
            ctx.set(dut.input_valid,0);await ctx.tick().repeat(312)
        await write32(ctx,0,1|(2<<3))
        for _ in range(210):
            await ctx.tick().repeat(1000)
            status=await read32(ctx,4)
            if status&2:break
        else:raise AssertionError('score frame never published')
        assert status&0x1f==2 and status>>16==322
        assert (status>>6)&3==2
        assert await read32(ctx,16)==700
        assert await read32(ctx,60)==700
        # Source window is frozen at request, not at the later score-read time.
        source=[await read32(ctx,address) for address in range(36,60,4)]
        assert source==[512,int(x[:512].sum())&0xffffffff,
                       int((x[:512]*x[:512]).sum())&0xffffffff,
                       int((x[:512]*x[:512]).sum())>>32,512,2<<2]
        for _ in range(400):
            ctx.set(dut.sample2,-5000);ctx.set(dut.input_valid,1);await ctx.tick()
            ctx.set(dut.input_valid,0);await ctx.tick().repeat(312)
        assert [await read32(ctx,address) for address in range(36,60,4)]==source
        assert await read32(ctx,60)==700
        for lag in range(322):
            await write32(ctx,8,lag)
            value=await read32(ctx,12)
            observed.append(value-(1<<32) if value&(1<<31) else value)
        assert await read32(ctx,4)==status
        frame=x[-674:];frame=frame-int(np.rint(frame.mean()))
        for index in range(674):
            await write32(ctx,8,1024|index)
            value=await read32(ctx,12)
            assert value==(int(frame[index])&0xffffffff)
        for index in (674,1023):
            await write32(ctx,8,1024|index)
            assert await read32(ctx,12)==0
        # Leaving the diagnostic address selected must not disturb a new job.
        await write32(ctx,0,1) # Different channel, new atomic source snapshot.
        assert await read32(ctx,12)==0
        assert await read32(ctx,36)==1024
        assert await read32(ctx,40)==0 and await read32(ctx,44)==0
        assert await read32(ctx,52)==1024 and await read32(ctx,56)==0
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
    frame=x[-674:];frame=frame-int(np.rint(frame.mean()));expected=[]
    for lag in range(322):
        a=frame[:674-lag];b=frame[lag:];corr=int(a@b);energy=int(a@a+b@b)
        q=(abs(corr)<<21)//energy;expected.append(-q if corr<0 else q)
    assert observed==expected


def test_extended_low_scores_do_not_alias_at_512_or_sample_address(monkeypatch):
    # Short FIR only accelerates history warm-up. Exercise the REAL CSR and
    # enlarged score RAM, including every high address and the inspect selector.
    monkeypatch.setattr('top.tuner.experiment.nsdf_peripheral.coefficients',lambda:[131071])
    dut=Peripheral()
    samples=np.random.default_rng(829).integers(-15000,15000,22000)
    async def write(ctx,address,value):
        for byte in range(4):
            ctx.set(dut.bus.addr,address+byte);ctx.set(dut.bus.w_data,(value>>(byte*8))&255)
            ctx.set(dut.bus.w_stb,1);await ctx.tick()
        ctx.set(dut.bus.w_stb,0);await ctx.tick().repeat(3)
    async def read(ctx,address):
        value=0
        for byte in range(4):
            ctx.set(dut.bus.addr,address+byte);ctx.set(dut.bus.r_stb,1);await ctx.tick()
            value|=ctx.get(dut.bus.r_data)<<(byte*8)
        ctx.set(dut.bus.r_stb,0);await ctx.tick()
        return value
    async def data(ctx,address):
        await write(ctx,8,address)
        value=await read(ctx,12)
        return value-(1<<32) if value&(1<<31) else value
    async def bench(ctx):
        for x in samples:
            ctx.set(dut.sample2,int(x));ctx.set(dut.input_valid,1);await ctx.tick()
            ctx.set(dut.input_valid,0);await ctx.tick().repeat(9)
        await ctx.tick().repeat(100)
        await write(ctx,0,1|4|(2<<3))
        for _ in range(360):
            await ctx.tick().repeat(1000)
            status=await read(ctx,4)
            if status&2:break
        else:raise AssertionError('extended low frame did not finish')
        assert status&0x1f==2 and status>>16==622
        frame=np.array([await data(ctx,1024|i) for i in range(674)],dtype=np.int64)
        observed=[await data(ctx,k) for k in range(622)]
        from analyze_nsdf_wave import replay
        assert observed==replay(frame.tolist(),621)
        assert observed[512:]!=observed[:110]
        for k in (622,1023,1024|674,2047):
            assert await data(ctx,k)==0
        assert await read(ctx,4)==status
    sim=Simulator(dut);sim.add_clock(1/60e6);sim.add_testbench(bench);sim.run()
