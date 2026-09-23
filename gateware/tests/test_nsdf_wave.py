import json
import math
from pathlib import Path
import pytest
from analyze_nsdf_source import analyze_source
from analyze_nsdf_wave import analyze_wave,replay


def capture():
    samples=[round(10000*math.sin(i*2*math.pi*25/6000)) for i in range(604)]
    mean=round(sum(samples)/len(samples));samples=[x-mean for x in samples]
    scores=replay(samples,301)
    from nsdf_trace_analysis import select
    r=select(scores,6000,20,1500,fallback=True)
    energy=sum(x*x for x in samples)
    body=''.join(f'{x&0xffffffff:08x}\n' for x in scores)
    return (
        'NSDF SOURCE ch=2 low=true seq=100 end=3200 n=20480 sum=0 squares=1024000000000 status=9 frame_end=3200\n'
        f"NSDF CPU ch=2 low=true seq=100 mhz={int(r['hz']*1000)} raw={int(r['unrefined_hz']*1000)} ppm={int(r['clarity']*1000000)} ok=true cycles=100 reads=604 guard=true gc=100 policy=1\n"
        f'NSDF IO ch=2 low=true seq=100 cycles=100 reads=302 sum={sum(scores)&0xffffffff:08x}\n'
        f'NSDF BEGIN ch=2 low=true fs=6000 n=604 last=301 seq=100 energy={energy} scaled=0 clipped=0\n'
        +body+'NSDF END\nNSDF WAVE ch=2 low=true seq=100 n=604\n'
        +''.join(f'{x&0xffffffff:08x}\n' for x in samples)+'NSDF WAVE END\n')


def test_exact_waveform_replays_every_score_and_energy():
    reports=list(analyze_wave(capture()))
    assert len(reports)==1 and reports[0]['score_parity_checked']
    assert len(reports[0]['samples'])==604


@pytest.mark.parametrize('change',[
    lambda t:t.replace('NSDF WAVE ch=2','NSDF WAVE ch=1'),
    lambda t:t.replace('seq=100 n=604','seq=100 n=603'),
    lambda t:t.replace('NSDF WAVE END\n',''),
    lambda t:t.replace('NSDF WAVE ch=2 low=true seq=100 n=604\n','NSDF WAVE ch=2 low=true seq=100 n=604\nffffffff\n'),
    lambda t:t+t[t.index('NSDF WAVE ch='):],
])
def test_corrupt_or_mixed_waveform_is_rejected(change):
    with pytest.raises(ValueError):list(analyze_wave(change(capture())))


def test_physical_gen3_score_fixture_parity_without_frequency_truth():
    fixture=json.loads((Path(__file__).parent/'fixtures/nsdf-gen3-fundamental-25-scores.json').read_text())
    records=[]
    for source,cpu,io,frame in zip(fixture['source_reports'],fixture['cpu_reports'],fixture['io_reports'],fixture['frames']):
        records.append(''.join('NSDF '+name+' '+' '.join(f'{k}={v}' for k,v in data.items())+'\n'
                       for name,data in [('SOURCE',source),('CPU',cpu),('IO',io)])+frame)
    reports=list(analyze_source(''.join(records)))
    assert len(reports)==16
    assert all(r['qualified'] and r['device_guard'] and not r['clipped'] for r in reports)
    hz=[r['hz'] for r in reports]
    assert min(hz)==24.957 and max(hz)==25.031
    assert 5<1200*math.log2(max(hz)/min(hz))<5.2


def test_actual_firmware_wave_export_survives_uart_backpressure(tmp_path):
    import os,re,subprocess
    exe=tmp_path/'trace'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O',
                    str(Path(__file__).parent/'nsdf_trace_mock.rs'),'-o',str(exe)],
                   env=dict(os.environ,TILIQUA_TUNER_NSDF_TRACE='full'),check=True)
    text=subprocess.check_output([exe],text=True)
    frames=re.findall(r'NSDF BEGIN ([^\n]+)\n(?:[0-9a-f]{8}\n)+NSDF END\n'
                      r'NSDF WAVE ([^\n]+)\n((?:[0-9a-f]{8}\n)+)NSDF WAVE END\n',text)
    assert len(frames)>=4
    for header,wave,body in frames:
        score_meta=dict(v.split('=') for v in header.split())
        wave_meta=dict(v.split('=') for v in wave.split())
        assert all(score_meta[k]==wave_meta[k] for k in ('ch','low','seq','n'))
        assert len(body.splitlines())==int(wave_meta['n'])


def test_physical_gen3_waveforms_replay_and_support_longer_lag_probe():
    from nsdf_trace_analysis import select
    fixture=json.loads((Path(__file__).parent/'fixtures/nsdf-gen3-fundamental-25-wave.json').read_text())
    text=''
    for source,cpu,io,frame,wave in zip(fixture['source_reports'],fixture['cpu_reports'],
                                      fixture['io_reports'],fixture['frames'],fixture['waveforms']):
        text+=''.join('NSDF '+name+' '+' '.join(f'{k}={v}' for k,v in data.items())+'\n'
                      for name,data in [('SOURCE',source),('CPU',cpu),('IO',io)])+frame+wave
    reports=list(analyze_wave(text))
    assert len(reports)==6
    old=[r['hz'] for r in reports]
    new=[select(replay(r['samples'],501),6000,20,1500,fallback=True)['hz'] for r in reports]
    span=lambda values:1200*math.log2(max(values)/min(values))
    assert 4.4<span(old)<4.6
    assert span(new)<.5
    # This proves repeatability improvement on identical measured samples,
    # NOT absolute accuracy, production timing, or performance at 20 Hz.


def test_blindly_extending_lags_can_regress_alternating_cycle_signal():
    import numpy as np
    from nsdf_refinement_probe import scores_for
    from nsdf_trace_analysis import select
    errors=[[],[]]
    for phase in np.linspace(0,2,32,endpoint=False):
        for i,(n,last) in enumerate(((604,301),(674,621))):
            p=np.arange(n)*50/6000+phase
            x=np.rint(14000*(np.sin(2*np.pi*p)+.0076*np.sin(np.pi*p+.7)+.0091*np.sin(3*np.pi*p+.4)))
            result=select(scores_for(x,last),6000,20,1500,fallback=True)
            assert result is not None and result['qualified']
            errors[i].append(abs(1200*math.log2(result['hz']/50)))
    assert max(errors[0])<.05
    assert max(errors[1])>.5
    # The longest accepted multiple may be odd and retain alternating-cycle
    # bias. Do not deploy a larger lag range alone as a universal correction.


def run_selector(tmp_path, cases):
    import subprocess
    exe=tmp_path/'selector'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O',
                    '-C','overflow-checks=yes',str(Path(__file__).parent/'nsdf_selector_fixture.rs'),
                    '-o',str(exe)],check=True)
    payload=''.join('low '+' '.join(map(str,s))+'\n' for s in cases)
    return [line.split() for line in subprocess.check_output([exe],input=payload,text=True).splitlines()]


@pytest.mark.parametrize('frequency,last,count,old_min,old_max,new_max',[
    (25,501,6,4.4,4.6,.5),(21,601,7,7.2,7.4,.6),
])
def test_firmware_strongest_repeat_on_physical_waveforms(tmp_path,frequency,last,count,old_min,old_max,new_max):
    fixture=json.loads((Path(__file__).parent/f'fixtures/nsdf-gen3-fundamental-{frequency}-wave.json').read_text())
    text=''
    for source,cpu,io,frame,wave in zip(fixture['source_reports'],fixture['cpu_reports'],
                                      fixture['io_reports'],fixture['frames'],fixture['waveforms']):
        text+=''.join('NSDF '+name+' '+' '.join(f'{k}={v}' for k,v in data.items())+'\n'
                     for name,data in [('SOURCE',source),('CPU',cpu),('IO',io)])+frame+wave
    reports=list(analyze_wave(text))
    assert len(reports)==count
    # Recalculate only lags supported by these exact captured samples. Never
    # extend/tile a waveform or present historical captures as new hardware.
    lines=run_selector(tmp_path,[replay(r['samples'],last) for r in reports])
    assert all(line[2]=='true' for line in lines)
    span=lambda values:1200*math.log2(max(values)/min(values))
    assert old_min<span([r['hz'] for r in reports])<old_max
    assert span([float(line[0]) for line in lines])<new_max


def test_current_firmware_alternating_cycle_accuracy_grid(tmp_path):
    import numpy as np
    from nsdf_refinement_probe import scores_for
    cases=[];truth=[]
    for hz in (20.2,21,25,40,50,70,100):
        for amplitude in (72,14000):
            for phase in np.linspace(0,2,32,endpoint=False):
                p=np.arange(674)*hz/6000+phase
                x=np.rint(amplitude*(np.sin(2*np.pi*p)+.0076*np.sin(np.pi*p+.7)+.0091*np.sin(3*np.pi*p+.4)))
                cases.append(scores_for(x,621));truth.append((hz,amplitude))
    lines=run_selector(tmp_path,cases)
    assert len(lines)==len(truth)
    for line,(hz,amplitude) in zip(lines,truth):
        assert line[2]=='true'
        assert abs(1200*math.log2(float(line[0])/hz))<(.5 if amplitude==72 else .05)
