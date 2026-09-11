"""Continuous four-lane acquisition; CSR selection must never reset a lane."""
import math
from amaranth.sim import Simulator
from amaranth.hdl import Fragment
from tiliqua.dsp.tuner import TunerPeripheral


def test_four_lanes_cover_audio_band_at_192khz():
    fs = 192000
    frequencies = [20, 997, 7040, 20000]
    dut = TunerPeripheral(sample_rate=fs, multichannel=True,
                          min_pitch_window_s=0.02, with_reference=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.i.valid, 1)
        for n in range(round(fs*0.22)):
            for ch, frequency in enumerate(frequencies):
                ctx.set(dut.i.payload[ch].as_value(),
                        round(4000*math.sin(math.tau*(n*frequency/fs+0.13))))
            await ctx.tick()
        ctx.set(dut.i.valid, 0)
        for ch, frequency in enumerate(frequencies):
            ctx.set(dut.bus.addr, 0)
            ctx.set(dut.bus.w_data, ch)
            ctx.set(dut.bus.w_stb, 1)
            await ctx.tick()
            ctx.set(dut.bus.w_stb, 0)
            await ctx.tick().repeat(2)
            samples = ctx.get(dut._period_samples.f.samples.r_data)
            cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
            assert samples > 0 and cycles > 0
            assert abs(1200*math.log2(fs*cycles/samples/frequency)) < 2

    sim.add_testbench(bench)
    sim.run()


def test_reference_free_tuner_cannot_enable_tone_through_legacy_registers():
    dut=TunerPeripheral(sample_rate=48000,multichannel=True,with_reference=False)
    fragment=Fragment.get(dut,None)
    assert "reference_oscillator" not in [name for _,name,*_ in fragment.subfragments]
    sim=Simulator(fragment);sim.add_clock(1e-6)
    async def bench(ctx):
        ctx.set(dut.reference_advance,1)
        for address,value in [(0x30,1),(0x34,255),(0x35,255),(0x36,255),(0x37,127)]:
            ctx.set(dut.bus.addr,address);ctx.set(dut.bus.w_data,value);ctx.set(dut.bus.w_stb,1)
            await ctx.tick();ctx.set(dut.bus.w_stb,0);await ctx.tick()
        for _ in range(32):
            await ctx.tick()
            assert ctx.get(dut.reference_enabled)==0
            assert ctx.get(dut.reference.as_value())==0
            assert ctx.get(dut.cal_active)==0
    sim.add_testbench(bench);sim.run()


def test_four_inputs_keep_independent_pitch_levels_and_silence_age():
    dut = TunerPeripheral(sample_rate=3200,multichannel=True,
                          min_pitch_window_s=0.02,level_window_log2=5,dc_filter_shift=20)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    periods = [8,16,32,64]
    amplitudes = [200,400,800,1600]

    async def select(ctx, address, channel):
        ctx.set(dut.bus.addr,address)
        ctx.set(dut.bus.w_data,channel)
        ctx.set(dut.bus.w_stb,1)
        await ctx.tick()
        ctx.set(dut.bus.w_stb,0)
        await ctx.tick().repeat(2)

    async def feed(ctx, first, count, silent=None):
        ctx.set(dut.i.valid,1)
        for n in range(first,first+count):
            for channel,(period,amplitude) in enumerate(zip(periods,amplitudes)):
                value = amplitude if n%period >= period//2 else -amplitude
                ctx.set(dut.i.payload[channel].as_value(),0 if channel==silent else value)
            await ctx.tick()
        ctx.set(dut.i.valid,0)

    async def bench(ctx):
        await feed(ctx,0,512)
        sequences = []
        for channel in range(4):
            await select(ctx,0,channel)
            samples = ctx.get(dut._period_samples.f.samples.r_data)
            cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
            assert cycles > 0 and samples == cycles*periods[channel]
            assert ctx.get(dut._mean_square.f.value.r_data)==amplitudes[channel]**2
            sequences.append(ctx.get(dut._pitch_sequence.f.sequence.r_data))
        # Selecting another verifier input resets only its shared capture.
        for channel in range(4):
            await select(ctx,0x48,channel)
            await select(ctx,0,channel)
            assert ctx.get(dut._pitch_sequence.f.sequence.r_data)==sequences[channel]
        await feed(ctx,512,2048,silent=2)
        for channel in range(4):
            await select(ctx,0,channel)
            cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
            samples = ctx.get(dut._period_samples.f.samples.r_data)
            if channel==2:
                assert cycles==0 and samples==0
                assert ctx.get(dut._mean_square.f.value.r_data)==0
            else:
                assert cycles>0 and samples==cycles*periods[channel]
                assert ctx.get(dut._pitch_sequence.f.sequence.r_data)!=sequences[channel]

    sim.add_testbench(bench)
    sim.run()


def test_calibration_command_ack_clears_only_routed_lane_and_preserves_clock():
    dut=TunerPeripheral(sample_rate=3200,multichannel=True,min_pitch_window_s=0.02,
                        level_window_log2=5,dc_filter_shift=20)
    sim=Simulator(dut); sim.add_clock(1e-6)
    async def write(ctx,address,value,size=1):
        for offset in range(size):
            ctx.set(dut.bus.addr,address+offset); ctx.set(dut.bus.w_data,(value>>(8*offset))&255)
            ctx.set(dut.bus.w_stb,1); await ctx.tick()
            ctx.set(dut.bus.w_stb,0); await ctx.tick()
        await ctx.tick().repeat(2)
    async def bench(ctx):
        ctx.set(dut.i.valid,1)
        for n in range(160):
            for ch in range(4): ctx.set(dut.i.payload[ch].as_value(),400 if n%16>=8 else -400)
            await ctx.tick()
        ctx.set(dut.i.valid,0)
        clock=ctx.get(dut._sample_clock.f.value.r_data)
        assert clock==160
        # Byte-wide CSR transaction must not acknowledge until DAC accepts.
        command=4000|(3<<16)|(1<<18)|(2<<19)|(17<<21)
        await write(ctx,0x5c,command,4)
        assert ctx.get(dut.cal_active)==0
        ctx.set(dut.reference_advance,1); await ctx.tick().repeat(3)
        assert ctx.get(dut.cal_value)==4000 and ctx.get(dut.cal_channel)==3
        assert ctx.get(dut._cal_status.f.value.r_data)==(256|17)
        assert ctx.get(dut._sample_clock.f.value.r_data)==clock
        for ch in range(4):
            await write(ctx,0,ch)
            if ch==2:
                assert ctx.get(dut._period_cycles.f.cycles.r_data)==0
                assert ctx.get(dut._mean_square.f.value.r_data)==0
            else:
                assert ctx.get(dut._period_cycles.f.cycles.r_data)>0
                assert ctx.get(dut._mean_square.f.value.r_data)>0
                assert ctx.get(dut._pitch_end.f.value.r_data)<=clock
                assert ctx.get(dut._level_end.f.value.r_data)<clock
    sim.add_testbench(bench); sim.run()
