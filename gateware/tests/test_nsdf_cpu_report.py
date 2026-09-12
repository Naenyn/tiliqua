import json
from pathlib import Path
import pytest
from analyze_nsdf_cpu import analyze,validate


def records(name='nsdf-cpu-integer-screen.json'):
    return json.loads((Path(__file__).parent/'fixtures'/name).read_text())


@pytest.mark.parametrize('name',['nsdf-cpu-integer-screen.json','nsdf-cpu-fixedpoint.json','nsdf-cpu-native-div.json'])
def test_complete_records_and_boundary_fragments(name):
    f=records(name);parts=[]
    for cpu,io,block in zip(f['cpu_reports'],f['io_reports'],f['frames']):
        parts.extend(['NSDF CPU '+' '.join(f'{k}={v}' for k,v in cpu.items())+'\n',
                      'NSDF IO '+' '.join(f'{k}={v}' for k,v in io.items())+'\n',block])
    reports=list(analyze('00100000\nNSDF END\n'+''.join(parts)+'NSDF CPU ch='))
    assert len(reports)==len(f['frames'])
    assert {r['channel'] for r in reports}=={0,1,2,3}
    assert any(r['gated'] for r in reports)


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
