import json
from pathlib import Path
import pytest
from analyze_nsdf_cpu import analyze,validate


def records():
    return json.loads((Path(__file__).parent/'fixtures/nsdf-cpu-integer-screen.json').read_text())


def test_complete_records_and_boundary_fragments():
    f=records();parts=[]
    for cpu,io,block in zip(f['cpu_reports'],f['io_reports'],f['frames']):
        parts.extend(['NSDF CPU '+' '.join(f'{k}={v}' for k,v in cpu.items())+'\n',
                      'NSDF IO '+' '.join(f'{k}={v}' for k,v in io.items())+'\n',block])
    reports=list(analyze('00100000\nNSDF END\n'+''.join(parts)+'NSDF CPU ch='))
    assert len(reports)==len(f['frames'])
    assert {r['channel'] for r in reports}=={0,1,2,3}
    assert any(r['gated'] for r in reports)


@pytest.mark.parametrize('field,value',[('seq','0'),('sum','ffffffff'),('reads','1')])
def test_reject_corrupt_io(field,value):
    f=records();io=dict(f['io_reports'][0]);io[field]=value
    with pytest.raises(ValueError):validate(f['cpu_reports'][0],io,f['frames'][0])


def test_reject_wrong_cpu_pitch_and_acquisition_error():
    f=records();cpu=dict(f['cpu_reports'][0]);cpu['mhz']='9999999'
    with pytest.raises(ValueError):validate(cpu,f['io_reports'][0],f['frames'][0])
    with pytest.raises(ValueError):list(analyze('NSDF ERROR fault\n'))
