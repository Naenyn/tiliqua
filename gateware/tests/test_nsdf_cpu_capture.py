import json
from pathlib import Path
import pytest
import sys
from types import SimpleNamespace
import capture_nsdf_cpu
from capture_nsdf_cpu import complete_cycle


def blocks():
    f=json.loads((Path(__file__).parent/'fixtures/nsdf-cpu-native-div.json').read_text())
    return ['NSDF CPU '+' '.join(f'{k}={v}' for k,v in c.items())+'\n'+
            'NSDF IO '+' '.join(f'{k}={v}' for k,v in i.items())+'\n'+b
            for c,i,b in zip(f['cpu_reports'],f['io_reports'],f['frames'])]


def test_waits_for_all_banks_not_just_eight_records():
    records=blocks()
    assert not complete_cycle('00000000\nNSDF END\n')
    assert not complete_cycle(''.join(records[:-1])+records[0]*8)
    assert not complete_cycle(''.join(records)[:-10])
    assert complete_cycle('00000000\nNSDF END\n'+''.join(records))


def test_bad_reports_fail_instead_of_counting_as_coverage():
    with pytest.raises(ValueError):complete_cycle('NSDF ERROR timeout\n')
    with pytest.raises(ValueError):
        complete_cycle(''.join(blocks()).replace('mhz=15819849','mhz=1'))


@pytest.mark.parametrize('error',[False,True])
def test_capture_handles_split_reads_and_closes_port(monkeypatch,capsys,error):
    raw=('NSDF ERROR fault\n' if error else ''.join(blocks())).encode()
    chunks=iter(raw[i:i+13] for i in range(0,len(raw),13))
    class Port:
        closed=False
        def __enter__(self):return self
        def __exit__(self,*args):self.closed=True
        def readline(self):return next(chunks)
    port=Port()
    monkeypatch.setitem(sys.modules,'serial',SimpleNamespace(Serial=lambda *a,**kw:port))
    monkeypatch.setattr(sys,'argv',['capture_nsdf_cpu.py','fake-port'])
    if error:
        with pytest.raises(RuntimeError,match='NSDF ERROR'):capture_nsdf_cpu.main()
    else:
        capture_nsdf_cpu.main()
        assert capsys.readouterr().out==raw.decode()
    assert port.closed and port.dtr and not port.rts
