import json
from pathlib import Path
import pytest
from analyze_nsdf_cpu import analyze,validate


def records(name='nsdf-cpu-integer-screen.json'):
    return json.loads((Path(__file__).parent/'fixtures'/name).read_text())


def test_policy_three_does_not_reinterpret_policy_two_scores():
    import numpy as np
    from nsdf_refinement_probe import scores_for
    from nsdf_trace_analysis import select
    x=np.rint(14000*np.sin(2*np.pi*(np.arange(674)*1703/6000+.17))).astype(np.int64)
    scores=scores_for(x,621);words=[v&0xffffffff for v in scores]
    block=(f'NSDF BEGIN ch=2 low=true fs=6000 n=674 last=621 seq=100 energy={int(x@x)} scaled=0 clipped=0\n'
           +''.join(f'{v:08x}\n' for v in words)+'NSDF END\n')
    io=dict(ch='2',low='true',seq='100',reads='622',cycles='100',sum=f'{sum(words)&0xffffffff:08x}')
    r=select(scores,6000,20,1500,fallback=True,refine_quality=True)
    assert r['qualified'] and 850<r['hz']<856
    cpu=dict(ch='2',low='true',seq='100',policy='2',reads='700',cycles='100',
             mhz=str(int(r['hz']*1000)),raw=str(int(r['unrefined_hz']*1000)),
             ppm=str(int(r['clarity']*1000000)),ok='true')
    assert validate(cpu,io,block)['qualified']
    with pytest.raises(ValueError,match='unexpected CPU candidate'):
        validate(dict(cpu,policy='3'),io,block)
    assert not validate(dict(cpu,policy='3',mhz='0',raw='0',ppm='0',ok='false'),io,block)['qualified']


@pytest.mark.parametrize('name',['nsdf-cpu-integer-screen.json','nsdf-cpu-fixedpoint.json','nsdf-cpu-native-div.json','nsdf-cpu-sine55.json','nsdf-cpu-sine10k.json','nsdf-cpu-sine18500.json','nsdf-cpu-sine-lowedge.json'])
def test_complete_records_and_boundary_fragments(name):
    f=records(name);parts=[]
    for cpu,io,block in zip(f['cpu_reports'],f['io_reports'],f['frames']):
        parts.extend(['NSDF CPU '+' '.join(f'{k}={v}' for k,v in cpu.items())+'\n',
                      'NSDF IO '+' '.join(f'{k}={v}' for k,v in io.items())+'\n',block])
    reports=list(analyze('00100000\nNSDF END\n'+''.join(parts)+'NSDF CPU ch='))
    assert len(reports)==len(f['frames'])
    assert {r['channel'] for r in reports}=={0,1,2,3}
    assert any(r['gated'] for r in reports)


@pytest.mark.parametrize('name,minimum,maximum',[
    ('nsdf-cpu-sine55.json',54,56),('nsdf-cpu-sine-lowedge.json',22,25)])
def test_physical_low_sine_is_only_qualified_in_low_bank(name,minimum,maximum):
    f=records(name)
    reports=[validate(c,i,b) for c,i,b in zip(f['cpu_reports'],f['io_reports'],f['frames'])]
    native=next(r for r in reports if r['channel']==0 and r['bank']=='native')
    low=next(r for r in reports if r['channel']==0 and r['bank']=='low')
    assert not native['qualified'] and native['hz']==0
    assert low['qualified'] and minimum<low['hz']<maximum
    # User setting was approximate; this is not a calibrated frequency reference.


@pytest.mark.parametrize('name,minimum,maximum',[
    ('nsdf-cpu-sine10k.json',9900,10100),
    ('nsdf-cpu-sine18500.json',18000,19000)])
def test_physical_high_sine_is_only_qualified_in_native_bank(name,minimum,maximum):
    f=records(name)
    reports=[validate(c,i,b) for c,i,b in zip(f['cpu_reports'],f['io_reports'],f['frames'])]
    native=next(r for r in reports if r['channel']==0 and r['bank']=='native')
    low=next(r for r in reports if r['channel']==0 and r['bank']=='low')
    assert native['qualified'] and minimum<native['hz']<maximum
    assert not low['qualified']
    # Approximate user setting, not independent frequency accuracy evidence.


def test_native_div_capture_preserves_known_lfo_false_candidate():
    # Algorithm parity does not mean this is a correct physical pitch. Retain
    # this counterexample until aligned source-energy arbitration can reject it.
    f=records('nsdf-cpu-native-div.json')
    reports=[validate(c,i,b) for c,i,b in zip(f['cpu_reports'],f['io_reports'],f['frames'])]
    native=next(r for r in reports if r['channel']==1 and r['bank']=='native')
    low=next(r for r in reports if r['channel']==1 and r['bank']=='low')
    assert native['qualified'] and native['hz']>15000 and native['rms_counts']<8
    assert not low['qualified']
    # These banks were acquired at different times; their RMS ratio must not
    # be treated as the aligned source-energy measurement required by a guard.


@pytest.mark.parametrize('field,value',[('seq','0'),('sum','ffffffff'),('reads','1')])
def test_reject_corrupt_io(field,value):
    f=records();io=dict(f['io_reports'][0]);io[field]=value
    with pytest.raises(ValueError):validate(f['cpu_reports'][0],io,f['frames'][0])


def test_reject_wrong_cpu_pitch_and_acquisition_error():
    f=records();cpu=dict(f['cpu_reports'][0]);cpu['mhz']='9999999'
    with pytest.raises(ValueError):validate(cpu,f['io_reports'][0],f['frames'][0])
    with pytest.raises(ValueError):list(analyze('NSDF ERROR fault\n'))
