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


def test_source_mode_requires_a_complete_validated_source_cycle():
    records=blocks();with_source=[]
    for block in records:
        c=dict(p.split('=') for p in block.splitlines()[0].split()[2:])
        # Synthetic constant-source moments, only testing protocol completion.
        source=dict(ch=c['ch'],low=c['low'],seq=c['seq'],end=int(c['seq'])-100,
                    n=20480,sum=0,squares=0,status=1|(int(c['ch'])<<2))
        with_source.append('NSDF SOURCE '+' '.join(f'{k}={v}' for k,v in source.items())+'\n'+block)
    assert not complete_cycle(''.join(records),require_source=True)
    assert complete_cycle(records[0]+''.join(with_source),require_source=True)
    with pytest.raises(ValueError):
        complete_cycle(''.join(with_source).replace('n=20480','n=20479'),require_source=True)


def test_wave_capture_ignores_connection_mid_frame(monkeypatch,capsys):
    records=[]
    for ch in range(4):
        for low in (False,True):
            # Mock only cycle completion here, requiring a SOURCE boundary
            # before parsing. Exact waveform replay has separate tests.
            records.append(f'NSDF SOURCE ch={ch} low={str(low).lower()}\nNSDF WAVE END\n')
    raw=('00000000\nNSDF WAVE END\n'+''.join(records)).encode()
    chunks=iter(raw[i:i+13] for i in range(0,len(raw),13))
    class Port:
        closed=False
        def __enter__(self):return self
        def __exit__(self,*args):self.closed=True
        def readline(self):return next(chunks)
    port=Port();calls=[]
    def analyze(text):
        assert 'NSDF SOURCE ' in text
        calls.append(text)
        import re
        return [dict(channel=int(ch),bank='low' if low=='true' else 'native')
                for ch,low in re.findall(r'^NSDF SOURCE ch=(\d) low=(true|false)$',text,re.M)]
    import analyze_nsdf_wave
    monkeypatch.setattr(analyze_nsdf_wave,'analyze_wave',analyze)
    monkeypatch.setitem(sys.modules,'serial',SimpleNamespace(Serial=lambda *a,**kw:port))
    monkeypatch.setattr(sys,'argv',['capture_nsdf_cpu.py','fake-port','--wave'])
    capture_nsdf_cpu.main()
    assert len(calls)==8 and port.closed
    assert capsys.readouterr().out==raw.decode()


@pytest.mark.parametrize('error',[False,True])
@pytest.mark.parametrize('fast',[False,True])
def test_capture_handles_split_reads_and_closes_port(monkeypatch,capsys,error,fast):
    from test_nsdf_fast_report import example
    raw=('NSDF ERROR fault\n' if error else (example()+example(1) if fast else ''.join(blocks()))).encode()
    chunks=iter(raw[i:i+13] for i in range(0,len(raw),13))
    class Port:
        closed=False
        def __enter__(self):return self
        def __exit__(self,*args):self.closed=True
        def readline(self):return next(chunks)
    port=Port()
    monkeypatch.setitem(sys.modules,'serial',SimpleNamespace(Serial=lambda *a,**kw:port))
    monkeypatch.setattr(sys,'argv',['capture_nsdf_cpu.py','fake-port']+(['--fast','--fast-frames','2'] if fast else []))
    if error:
        with pytest.raises(RuntimeError,match='NSDF ERROR'):capture_nsdf_cpu.main()
    else:
        capture_nsdf_cpu.main()
        assert capsys.readouterr().out==raw.decode()
    assert port.closed and port.dtr and not port.rts


@pytest.mark.parametrize('count,accepted',[(6000,True),(6001,False),(1,False)])
def test_long_fast_capture_count_is_bounded(monkeypatch,count,accepted):
    opened=[]
    def connect(*args,**kwargs):
        opened.append(True)
        raise RuntimeError('accepted arguments')
    monkeypatch.setitem(sys.modules,'serial',SimpleNamespace(Serial=connect))
    monkeypatch.setattr(sys,'argv',['capture_nsdf_cpu.py','fake-port','--fast',
                                 '--fast-frames',str(count),'--timeout','360'])
    with pytest.raises(RuntimeError if accepted else SystemExit):capture_nsdf_cpu.main()
    assert bool(opened)==accepted


@pytest.mark.parametrize('fast',[False,True])
def test_capture_byte_limit_closes_port(monkeypatch,fast):
    limit=(4 if fast else 1)*1048576
    class Port:
        closed=False
        def __enter__(self):return self
        def __exit__(self,*args):self.closed=True
        def readline(self):return b'x'*(limit+1)
    port=Port()
    monkeypatch.setitem(sys.modules,'serial',SimpleNamespace(Serial=lambda *a,**kw:port))
    monkeypatch.setattr(sys,'argv',['capture_nsdf_cpu.py','fake-port']+(['--fast'] if fast else []))
    with pytest.raises(RuntimeError,match='MiB bound'):capture_nsdf_cpu.main()
    assert port.closed
