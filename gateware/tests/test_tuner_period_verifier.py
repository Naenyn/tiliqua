"""Actual RTL checks for the bounded candidate verifier, including refusal paths."""
import math
import random
import json
from pathlib import Path
import pytest
from amaranth.sim import Simulator
from tiliqua.dsp.period_verifier import PeriodVerifier
from tiliqua.dsp.tuner import TunerPeripheral


def test_physical_alternating_cycle_capture_matches_software_scores():
    """Reproduce the observed ambiguity, not an assertion of desired musical pitch.

    The captured signal repeats markedly better after two crossing periods.
    Keep this fixture to evaluate future selection policies against real input.
    """
    from analyze_tuner_capture import score
    capture=json.loads((Path(__file__).parent/"fixtures/tuner-alternating-cycle-capture.json").read_text())
    samples=capture["samples"];lag=int(capture["header"]["lag"])
    expected_error,expected_span=score(samples,lag)
    assert 0.049 < expected_error/(256*expected_span) < 0.052
    assert score(samples,2*lag)[0]/(256*expected_span)<0.002
    dut=PeriodVerifier(decimation=8,adaptive=True)
    sim=Simulator(dut);sim.add_clock(1e-6)
    async def bench(ctx):
        ctx.set(dut.capture_mode,1);await ctx.tick().repeat(2)
        ctx.set(dut.accept,1)
        for sample in samples:
            ctx.set(dut.sample,sample);await ctx.tick()
        ctx.set(dut.accept,0);ctx.set(dut.lag_q8,lag)
        ctx.set(dut.request,1);await ctx.tick();ctx.set(dut.request,0)
        for _ in range(7300):
            if ctx.get(dut.done):break
            await ctx.tick()
        assert ctx.get(dut.done) and ctx.get(dut.factor)==2
        assert ctx.get(dut.first_error)==expected_error
        assert ctx.get(dut.first_span)==expected_span
    sim.add_testbench(bench);sim.run()


def test_armed_capture_freezes_on_disable_command_without_channel_switch():
    dut=TunerPeripheral(sample_rate=192000,min_pitch_window_s=0.02)
    sim=Simulator(dut);sim.add_clock(1e-6)
    async def write(ctx,address,value,count):
        for byte in range(count):
            ctx.set(dut.bus.addr,address+byte);ctx.set(dut.bus.w_data,(value>>(8*byte))&255)
            ctx.set(dut.bus.w_stb,1);await ctx.tick()
        ctx.set(dut.bus.w_stb,0);await ctx.tick().repeat(2)
    async def bench(ctx):
        await write(ctx,0x64,1,1)
        ctx.set(dut.i.valid,1)
        for n in range(2200):
            ctx.set(dut.i.payload[0].as_value(),round(19000*math.sin(math.tau*n/25)))
            await ctx.tick()
        ctx.set(dut.i.valid,0)
        await write(ctx,0x70,1<<11,2)
        assert not ctx.get(dut._capture_data.f.frozen.r_data)
        await write(ctx,0x5c,0,4)
        assert ctx.get(dut._capture_data.f.frozen.r_data)
        assert ctx.get(dut._capture_data.f.ready.r_data)
    sim.add_testbench(bench);sim.run()


def test_diagnostic_freezes_pre_clear_history_and_releases_without_stale_matches():
    dut=PeriodVerifier(decimation=8,adaptive=True)
    sim=Simulator(dut);sim.add_clock(1e-6)
    async def bench(ctx):
        ctx.set(dut.capture_mode,1);await ctx.tick().repeat(2)
        ctx.set(dut.accept,1)
        for n in range(2085):
            ctx.set(dut.sample,n-1100);await ctx.tick()
        ctx.set(dut.accept,0);ctx.set(dut.capture_arm,1)
        await ctx.tick().repeat(2)
        assert not ctx.get(dut.capture_frozen)  # Arming does not stop capture.
        ctx.set(dut.clear,1);await ctx.tick();ctx.set(dut.clear,0)
        assert ctx.get(dut.capture_frozen) and ctx.get(dut.capture_ready)
        ctx.set(dut.accept,1);ctx.set(dut.sample,30000)
        for index in range(2048):
            ctx.set(dut.capture_address,index);await ctx.tick().repeat(3)
            assert ctx.get(dut.capture_sample)==37+index-1100
        # Subsequent stop/channel clears must not destroy the held history.
        ctx.set(dut.clear,1);await ctx.tick();ctx.set(dut.clear,0)
        ctx.set(dut.capture_address,0);await ctx.tick().repeat(3)
        assert ctx.get(dut.capture_sample)==-1063
        ctx.set(dut.accept,0);ctx.set(dut.capture_arm,0);await ctx.tick().repeat(3)
        assert not ctx.get(dut.capture_frozen) and not ctx.get(dut.capture_ready)
        ctx.set(dut.lag_q8,25*256);ctx.set(dut.request,1);await ctx.tick()
        assert ctx.get(dut.done) and ctx.get(dut.factor)==0
    sim.add_testbench(bench);sim.run()


@pytest.mark.parametrize("noise,expected", [(0.193,1),(0.4,0)])
def test_near_threshold_noise_cannot_choose_an_octave(noise,expected):
    """A reproducible threshold-cliff case, not a model of the actual ADC noise."""
    dut=PeriodVerifier(decimation=8,adaptive=True)
    sim=Simulator(dut);sim.add_clock(1e-6)
    async def bench(ctx):
        ctx.set(dut.capture_mode,1);await ctx.tick().repeat(2)
        rng=random.Random(19);ctx.set(dut.accept,1)
        for n in range(2048):
            sample=round(19000*(math.sin(math.tau*(n*7674.02/192000+.17))
                              +noise*rng.uniform(-1,1)))
            ctx.set(dut.sample,sample);await ctx.tick()
        ctx.set(dut.accept,0);ctx.set(dut.lag_q8,round(192000*256/7674.02))
        ctx.set(dut.request,1);await ctx.tick();ctx.set(dut.request,0)
        for _ in range(7300):
            if ctx.get(dut.done):break
            await ctx.tick()
        assert ctx.get(dut.done)
        assert ctx.get(dut.first_error)*20>ctx.get(dut.first_span)*256
        assert ctx.get(dut.factor)==expected
    sim.add_testbench(bench);sim.run()


@pytest.mark.parametrize("phase", [0,0.17,0.49,0.81])
def test_reported_frequency_with_live_capture_and_measured_lag(phase):
    dut=PeriodVerifier(decimation=8,adaptive=True)
    sim=Simulator(dut);sim.add_clock(1e-6)
    async def bench(ctx):
        ctx.set(dut.capture_mode,1);await ctx.tick().repeat(2)
        frequency=7678.01
        def sample(n):
            return round(19590*math.sin(math.tau*(n*frequency/192000+phase)))
        ctx.set(dut.accept,1)
        for n in range(4096):
            ctx.set(dut.sample,sample(n));await ctx.tick()
        ctx.set(dut.accept,0)
        # Approximate the finite crossing window, rather than an ideal period.
        cycles=154;samples=round(cycles*192000/frequency)
        ctx.set(dut.lag_q8,round(samples*256/cycles))
        ctx.set(dut.request,1);await ctx.tick();ctx.set(dut.request,0)
        for clock in range(7300):
            ctx.set(dut.accept,clock%312==0)
            ctx.set(dut.sample,sample(4096+clock//312))
            await ctx.tick()
            if ctx.get(dut.done):break
        assert ctx.get(dut.done)
        assert ctx.get(dut.factor)==1,(phase,ctx.get(dut.factor))
        assert ctx.get(dut.first_span)>0
        assert ctx.get(dut.first_error)*20 <= ctx.get(dut.first_span)*256
    sim.add_testbench(bench);sim.run()


@pytest.mark.parametrize("frequency", [7600,7678.01,7900,8000,8050,8100,8200,8500,16000,20000])
@pytest.mark.parametrize("amplitude", [4000,20000])
def test_full_rate_high_level_sine_is_never_octave_divided(frequency,amplitude):
    dut=PeriodVerifier(decimation=8,adaptive=True)
    sim=Simulator(dut);sim.add_clock(1e-6)
    async def bench(ctx):
        ctx.set(dut.capture_mode,1);await ctx.tick().repeat(2)
        ctx.set(dut.accept,1)
        for n in range(4096):
            ctx.set(dut.sample,round(amplitude*math.sin(math.tau*(n*frequency/192000+0.17))))
            await ctx.tick()
        ctx.set(dut.accept,0);ctx.set(dut.lag_q8,round(192000*256/frequency))
        ctx.set(dut.request,1);await ctx.tick();ctx.set(dut.request,0)
        for _ in range(7300):
            if ctx.get(dut.done):break
            await ctx.tick()
        assert ctx.get(dut.done)
        assert ctx.get(dut.factor)==1,(frequency,amplitude,ctx.get(dut.factor))
    sim.add_testbench(bench);sim.run()


@pytest.mark.parametrize("sample_rate,mode,frequency", [
    (48000,3,2.5), (48000,3,10), (48000,2,47),
    (48000,1,4000), (48000,1,6000), (48000,1,7900),
    (192000,3,2.5), (192000,3,20), (192000,1,8000),
    (192000,1,16000), (192000,1,19753), (192000,1,20000), (192000,1,24000),
])
def test_adaptive_capture_qualifies_low_and_high_sines_and_retires_old_history(sample_rate,mode,frequency):
    base=sample_rate//24000
    divisor=[base,1,base*4,base*16][mode]
    dut=PeriodVerifier(decimation=base,adaptive=True)
    sim=Simulator(dut);sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.capture_mode,mode)
        await ctx.tick().repeat(2)
        assert ctx.get(dut.capture_divisor)==divisor
        ctx.set(dut.accept,1)
        for n in range(dut.DEPTH*divisor):
            ctx.set(dut.sample,round(4000*math.sin(math.tau*n*frequency/sample_rate)))
            await ctx.tick()
        ctx.set(dut.accept,0)
        ctx.set(dut.lag_q8,round(sample_rate/divisor*256/frequency))
        ctx.set(dut.request,1);await ctx.tick();ctx.set(dut.request,0)
        for _ in range(7300):
            if ctx.get(dut.done):break
            await ctx.tick()
        assert ctx.get(dut.done) and ctx.get(dut.factor)==1
        ctx.set(dut.capture_mode,(mode+1)%4);await ctx.tick()
        assert not ctx.get(dut.done) and not ctx.get(dut.busy)
        assert ctx.get(dut.factor)==0
        ctx.set(dut.request,1);await ctx.tick();ctx.set(dut.request,0)
        assert ctx.get(dut.done) and ctx.get(dut.factor)==0

    sim.add_testbench(bench);sim.run()


@pytest.mark.parametrize("frequency,harmonic,expected", [
    (32.7032,0,1), (110,0,1), (440,0,1), (880,0,1),
    (1760,0,1), (440,0.25,1), (440,0.75,2), (440,1.5,2),
    (1760,1.5,2), (17.142857,1.5,2), (7040,0,0),
])
def test_waveform_repetition(frequency, harmonic, expected):
    dut = PeriodVerifier()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.accept,1)
        for n in range(dut.DEPTH*8):
            angle = math.tau*n*frequency/192000
            ctx.set(dut.sample,round(4000*(math.sin(angle)+harmonic*math.sin(2*angle))))
            await ctx.tick()
        ctx.set(dut.accept,0)
        crossing_hz = frequency*(2 if harmonic >= 0.75 else 1)
        lag = round(24000*256/crossing_hz)
        ctx.set(dut.lag_q8,lag)
        ctx.set(dut.request,1)
        await ctx.tick()
        ctx.set(dut.request,0)
        for cycles in range(7300):
            if ctx.get(dut.done):
                break
            await ctx.tick()
        else:
            pytest.fail("unbounded verification")
        assert ctx.get(dut.factor) == expected
        if expected==1:
            assert ctx.get(dut.first_error)*20<=ctx.get(dut.first_span)*256
        elif expected>1:
            # Retain the rejected FIRST candidate score, not the winning score.
            assert ctx.get(dut.first_error)*20>ctx.get(dut.first_span)*256
        assert not ctx.get(dut.busy)
        assert ctx.get(dut.result_lag_q8) == lag

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("frequency,harmonic,amplitude,expected", [
    (440,0.75,4000,2), (440,1.5,4000,2), (880,0,4000,1),
    (110,0,72,1), (7040,0,4000,0),
])
@pytest.mark.parametrize("sample_rate", [48000,192000])
def test_csr_request_uses_measured_candidate_and_channel_change_retires_result(
        frequency, harmonic, amplitude, expected, sample_rate):
    dut = TunerPeripheral(sample_rate=sample_rate,min_pitch_window_s=0.02)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def write(ctx, address, value, count):
        for byte in range(count):
            ctx.set(dut.bus.addr,address+byte)
            ctx.set(dut.bus.w_data,(value >> (8*byte)) & 255)
            ctx.set(dut.bus.w_stb,1)
            await ctx.tick()
        ctx.set(dut.bus.w_stb,0)
        await ctx.tick().repeat(2)

    async def bench(ctx):
        ctx.set(dut.i.valid,1)
        for n in range(sample_rate//8):
            angle = math.tau*n*frequency/sample_rate
            ctx.set(dut.i.payload[0].as_value(),
                    round(amplitude*(math.sin(angle)+harmonic*math.sin(2*angle))))
            await ctx.tick()
        ctx.set(dut.i.valid,0)
        samples = ctx.get(dut._period_samples.f.samples.r_data)
        cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
        assert cycles > 0
        decimation = ctx.get(dut._verify_info.f.decimation.r_data)
        assert decimation == sample_rate//24000
        lag = round(samples*256/(cycles*decimation))
        await write(ctx,0x38,lag,4)
        for _ in range(7300):
            if ctx.get(dut._verify_status.f.done.r_data):
                break
            await ctx.tick()
        else:
            pytest.fail("CSR request did not complete")
        factor = ctx.get(dut._verify_status.f.factor.r_data)
        assert factor == expected
        assert ctx.get(dut._verify_lag.f.lag_q8.r_data)==lag
        corrected = sample_rate*cycles/samples/(factor or 1)
        assert abs(1200*math.log2(corrected/frequency)) < 2
        await write(ctx,0,1,1)
        assert not ctx.get(dut._verify_status.f.done.r_data)
        assert not ctx.get(dut._verify_status.f.busy.r_data)
        assert ctx.get(dut._verify_status.f.factor.r_data)==0
        await write(ctx,0x38,lag,4)
        assert ctx.get(dut._verify_status.f.done.r_data)
        assert ctx.get(dut._verify_status.f.factor.r_data)==0

    sim.add_testbench(bench)
    sim.run()


def test_unfilled_silent_overwritten_and_cleared_history_cannot_verify():
    dut = PeriodVerifier()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def request(ctx):
        ctx.set(dut.lag_q8,24*256)
        ctx.set(dut.request,1)
        await ctx.tick()
        ctx.set(dut.request,0)

    async def finish(ctx):
        for _ in range(7300):
            if ctx.get(dut.done):
                break
            await ctx.tick()
        else:
            pytest.fail("unbounded verification")
        assert ctx.get(dut.factor)==0

    async def bench(ctx):
        await request(ctx)
        await finish(ctx)
        ctx.set(dut.accept,1)
        ctx.set(dut.sample,5000)  # Constant DC is not a verified period.
        await ctx.tick().repeat(dut.DEPTH*8)
        ctx.set(dut.accept,0)
        await request(ctx)
        await finish(ctx)
        await request(ctx)
        ctx.set(dut.accept,1)  # Deliberately unrealistic rate: overwrite guard.
        await ctx.tick().repeat(dut.GUARD*8+1)
        assert ctx.get(dut.done) and not ctx.get(dut.busy)
        assert ctx.get(dut.factor)==0
        ctx.set(dut.accept,0)
        await request(ctx)
        assert ctx.get(dut.busy)
        ctx.set(dut.clear,1)
        await ctx.tick()
        ctx.set(dut.clear,0)
        assert not ctx.get(dut.busy) and not ctx.get(dut.done)
        await request(ctx)
        await finish(ctx)

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("sample_rate,frequency,mode,divisor", [
    (48000,6000,1,1),(48000,10,3,32),
    (192000,20,3,128),(192000,20000,1,1),
])
def test_capture_rate_csr_reports_actual_scale_and_qualifies_extended_range(sample_rate,frequency,mode,divisor):
    dut=TunerPeripheral(sample_rate=sample_rate,min_pitch_window_s=0.02)
    sim=Simulator(dut);sim.add_clock(1e-6)

    async def write(ctx,address,value,count):
        for byte in range(count):
            ctx.set(dut.bus.addr,address+byte);ctx.set(dut.bus.w_data,(value>>(8*byte))&255)
            ctx.set(dut.bus.w_stb,1);await ctx.tick()
        ctx.set(dut.bus.w_stb,0);await ctx.tick().repeat(2)

    async def bench(ctx):
        await write(ctx,0x64,mode,1)
        assert ctx.get(dut._verify_info.f.decimation.r_data)==divisor
        ctx.set(dut.i.valid,1)
        for n in range(max(sample_rate//8,2048*divisor+1000)):
            ctx.set(dut.i.payload[0].as_value(),round(4000*math.sin(math.tau*n*frequency/sample_rate)))
            await ctx.tick()
        ctx.set(dut.i.valid,0)
        samples=ctx.get(dut._period_samples.f.samples.r_data)
        cycles=ctx.get(dut._period_cycles.f.cycles.r_data)
        assert cycles>0
        lag=round(samples*256/(cycles*divisor))
        await write(ctx,0x38,lag,4)
        for _ in range(7300):
            if ctx.get(dut._verify_status.f.done.r_data):break
            await ctx.tick()
        assert ctx.get(dut._verify_status.f.done.r_data)
        assert ctx.get(dut._verify_status.f.factor.r_data)==1
        assert ctx.get(dut._verify_span.f.value.r_data)>0
        assert (ctx.get(dut._verify_error.f.value.r_data)*20
                <= ctx.get(dut._verify_span.f.value.r_data)*256)
        await write(ctx,0x64,0,1)
        assert ctx.get(dut._verify_status.f.factor.r_data)==0
        assert not ctx.get(dut._verify_status.f.done.r_data)
        assert ctx.get(dut._verify_error.f.value.r_data)==0
        assert ctx.get(dut._verify_span.f.value.r_data)==0

    sim.add_testbench(bench);sim.run()


@pytest.mark.parametrize("order", [2,3,4])
def test_continued_capture_and_busy_request_cannot_change_candidate(order):
    dut = PeriodVerifier()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def sample(n):
        angle = math.tau*n*440/192000
        return round(4000*(math.sin(angle)+1.5*math.sin(order*angle)))

    async def bench(ctx):
        ctx.set(dut.accept,1)
        n = dut.DEPTH*8
        for i in range(n):
            ctx.set(dut.sample,sample(i))
            await ctx.tick()
        ctx.set(dut.accept,0)
        lag = round(24000*256/(440*order))
        ctx.set(dut.lag_q8,lag)
        ctx.set(dut.request,1)
        await ctx.tick()
        ctx.set(dut.request,0)
        for cycles in range(7300):
            if ctx.get(dut.done):
                break
            # Faster than production sample arrivals, still below overwrite
            # limit. The writer must continue independently of verification.
            ctx.set(dut.accept,cycles%32==0)
            if cycles%32==0:
                ctx.set(dut.sample,sample(n))
                n += 1
            if cycles==100:
                ctx.set(dut.request,1)
                ctx.set(dut.lag_q8,0)  # Must be ignored while busy.
            if cycles==101:
                ctx.set(dut.request,0)
            await ctx.tick()
        else:
            pytest.fail("unbounded verification")
        assert ctx.get(dut.factor)==order
        assert ctx.get(dut.result_lag_q8)==lag

    sim.add_testbench(bench)
    sim.run()
