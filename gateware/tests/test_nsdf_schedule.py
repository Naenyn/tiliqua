"""Actual firmware scheduler under UART backpressure; no physical-rate claims."""
import os
from pathlib import Path
import subprocess
import pytest
from analyze_nsdf_schedule import analyze_schedule,analyze_picks,analyze_comparisons
import sys
from types import SimpleNamespace
import capture_nsdf_cpu


@pytest.mark.parametrize('focus',range(4))
@pytest.mark.parametrize('scenario',[5,6])
def test_operation_sampling_and_passive_tuner_restore(tmp_path,scenario,focus):
    """Exercise actual request writes, in-flight changes and published input identity."""
    here=Path(__file__).parent
    exe=tmp_path/'focused-scheduler'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O',
                    '--cfg','tuner_nsdf_continuous','--cfg','tuner_nsdf_telemetry',
                    str(here/'nsdf_trace_mock.rs'),
                    '-o',str(exe)],env=dict(os.environ,TILIQUA_INTONO_NSDF_TRACE='continuous'),check=True)
    text=subprocess.check_output([exe,str(scenario),str(focus)],text=True)
    starts=[dict(part.split('=') for part in line.split()[2:])
            for line in text.splitlines() if line.startswith('SAMPLE START ')]
    starts=[(int(p['ms']),int(p['slot'])) for p in starts]
    assert len(starts)>900
    assert all(b[0]-a[0]>=10 for a,b in zip(starts,starts[1:]))
    if scenario==5:
        for lo,hi,input_number in [(2000,4001,focus),(4001,7001,(focus+1)%4)]:
            group=[slot for ms,slot in starts if lo<=ms<hi]
            assert set(group)=={2*input_number,2*input_number+1}
            assert all(a!=b for a,b in zip(group,group[1:]))
        restored=[slot for ms,slot in starts if ms>=7001]
        assert set(restored)==set(range(8))
        assert all(b==(a+1)%8 for a,b in zip(restored,restored[1:]))
        # One bank now receives 50 nominal requests/s in this ideal CSR mock.
        # This is request throughput, not independent-window or hardware speed.
        for slot in (focus*2,focus*2+1):
            assert len([1 for ms,s in starts if 2000<=ms<4000 and s==slot])==100
    else:
        focused=[(ms,slot) for ms,slot in starts if slot>>1==focus]
        assert all(a[1]!=b[1] for a,b in zip(focused,focused[1:]))
        assert len(focused)>2*len(starts)//3-2
        for slot in range(8):
            group=[ms for ms,s in starts if s==slot]
            assert len(group)>40
            assert max(b-a for a,b in zip(group,group[1:]))<=180
        # Native/low readings from other inputs remain live when TUNER is
        # displayed; the Rust mock also checks actual per-input frequencies.
        reports=list(analyze_schedule(text))
        assert all(r['ok'] for r in reports if r['count']>0 and r['ms']>11000)


@pytest.mark.parametrize('scenario',[0,1,2,3,4])
def test_real_scheduler_keeps_acquiring_during_uart_stall(tmp_path,scenario):
    here=Path(__file__).parent
    exe=tmp_path/'scheduler'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O',
                    '--cfg','tuner_nsdf_continuous','--cfg','tuner_nsdf_telemetry',
                    str(here/'nsdf_trace_mock.rs'),
                    '-o',str(exe)],env=dict(os.environ,TILIQUA_INTONO_NSDF_TRACE='continuous'),check=True)
    text=subprocess.check_output([exe,str(scenario)],text=True)
    if scenario==3:
        status='VERIFY MOCK immutable status report\n'*28
        assert text.count(status)>=7
        # A competing multi-line report survives partial UART writes/stalls
        # intact. It cannot splice into RUN/PICK/COMP or vice versa.
        assert 'VERIFY' not in text.replace(status,'')
        assert all(line.startswith(('NSDF RUN ','NSDF PICK ','NSDF COMP ','VERIFY MOCK '))
                   for line in text.splitlines())
    checked=list(analyze_schedule(text))
    picks=list(analyze_picks(text))
    comparisons=list(analyze_comparisons(text))
    assert len(comparisons)>40
    # COMP follows the display's short-window preference; PICK retains the
    # strict two-bank comparison as a diagnostic, not a live-display veto.
    assert all(c['src']==2 for c in comparisons[-4:])
    assert len(picks)>40
    assert {p['ch'] for p in picks}=={0,1,2,3}
    assert all(p['src']==1 for p in picks[-4:])
    assert all(not r['score_parity_checked'] for r in checked)
    if scenario==0:
        assert all(12<=r['updates_per_second']<=13 for r in checked
                   if r['updates_per_second'] is not None and r['count']>20)
    lines=[x for x in text.splitlines(keepends=True) if x.startswith('NSDF RUN ') and x.endswith('\n')]
    assert len(lines)>100
    reports=[dict(p.split('=') for p in x.split()[2:]) for x in lines]
    assert {(int(r['ch']),r['low']) for r in reports}=={(ch,low) for ch in range(4) for low in ('false','true')}
    for ch in range(4):
        for low in ('false','true'):
            group=[r for r in reports if (int(r['ch']),r['low'])==(ch,low) and int(r['count'])>0]
            assert len(group)>10
            assert group[-1]['ok']=='true'
            if scenario==0:
                assert all(r['ok']=='true' and r['faults']=='0' for r in group)
                assert all(int(b['count'])>int(a['count']) for a,b in zip(group,group[1:]))
            else:
                assert all(int(b['count'])>=int(a['count']) for a,b in zip(group,group[1:]))
    if scenario==1:
        assert any(int(r['faults'])>0 and r['ok']=='false' for r in reports)
    if scenario==2:
        assert any(int(r['count'])>0 and int(r['age'])>500 and r['ok']=='false' for r in reports)
    assert 'NSDF SOURCE' not in text


def record(ch=0,low=False,count=1,seq=1000,ms=2000,**changes):
    r=dict(ch=ch,low=str(low).lower(),count=count,seq=seq,mhz=880000,
           raw='true',guard='true',ok='true',age=10,dt=2,cycles=200,work=200*count,faults=0,ms=ms)
    r.update(changes)
    return 'NSDF RUN '+' '.join(f'{k}={v}' for k,v in r.items())+'\n'


@pytest.mark.parametrize('changes',[dict(age=501),dict(ch=4),dict(ok='maybe'),
    dict(mhz=21000000),dict(count=0),dict(guard='false'),dict(ms=-1)])
def test_bad_scheduler_record(changes):
    with pytest.raises(ValueError):list(analyze_schedule(record(**changes)))


def test_scheduler_rejects_skip_and_handles_partial_connection():
    assert len(list(analyze_schedule('partial record\n'+record()+record(0,True)[:-1])))==1
    with pytest.raises(ValueError):list(analyze_schedule(record()+record(1,False)))


def test_scheduler_wrapping_counters():
    text=''
    for cycle in range(2):
        for slot in range(8):
            text+=record(slot//2,bool(slot&1),count=10+cycle,
                         seq=(0xfffffff0+cycle*100)&0xffffffff,
                         ms=(0xffffff00+cycle*400+slot*50)&0xffffffff,
                         work=(0xffffff80+cycle*200)&0xffffffff)
    reports=list(analyze_schedule(text))
    assert all(r['updates_per_second']==2.5 for r in reports[8:])
    assert all(r['measured_cpu_fraction']==200/(60000*400) for r in reports[8:])


def test_summary_worst_case_capacity():
    line=('NSDF RUN ch=3 low=false count=4294967295 seq=4294967295 mhz=20000000 '
          'raw=false guard=false ok=false age=4294967295 dt=4294967295 '
          'cycles=4294967295 work=4294967295 faults=4294967295 ms=4294967295\n')
    assert len(line)<=224
    pick=('NSDF PICK ch=3 ms=4294967295 n=20000000 na=4294967295 nq=false '
          'l=1500000 la=4294967295 lq=false mhz=20000000 src=3\n')
    assert len(line+pick)<=384
    comp=('NSDF COMP ch=3 ms=4294967295 mhz=20000000 src=3 gen=4294967295 '
          'age=4294967295 win=4294967295 base=4294967295 bq=false bage=4294967295\n')
    assert len(line+pick+comp)<=512


@pytest.mark.parametrize('high',[0,10,19,25])
def test_physical_continuous_four_tone_rates_and_results(high):
    fixture=f'nsdf-continuous-mixed-{high}k.txt' if high else 'nsdf-continuous-four-tones.txt'
    if high==25:fixture='nsdf-continuous-mixed-25hz.txt'
    reports=list(analyze_schedule((Path(__file__).parent/'fixtures'/fixture).read_text()))
    assert len(reports)==200
    total_cpu=0
    ranges=[(880,884),(775,779),(174,177),(138,140)]
    if high:ranges[0]=(10000,10010)
    if high==19:ranges[0]=(18450,18465)
    if high==25:ranges[0]=(24.9,25.1)
    for ch in range(4):
        for low in (False,True):
            group=[r for r in reports if (r['ch'],r['low'])==(ch,low)]
            assert len(group)==25
            a,b=group[0],group[-1]
            elapsed=(b['ms']-a['ms'])&0xffffffff
            rate=(b['count']-a['count'])*1000/elapsed
            assert 11<rate<11.3
            total_cpu+=((b['work']-a['work'])&0xffffffff)/(elapsed*60000)
            expected=low or ch<2
            if high and ch==0:expected=not low
            if high==25 and ch==0:expected=low
            assert all(r['ok']==expected and r['faults']==0 for r in group)
            if expected:
                lo,hi=ranges[ch]
                assert all(lo<r['hz']<hi for r in group)
    assert (.06 if high==25 else .065)<total_cpu<.08
    assert all(r['age']<95 and r['dt']<=4 and r['cycles']/60000<(2 if high else 1.6) for r in reports)
    # Latest-value telemetry observes only some completed acquisitions.
    # Do not claim these reports prove qualification on every acquisition.
    assert all(not r['score_parity_checked'] for r in reports)


@pytest.mark.parametrize('wrong_mode',[False,True])
def test_continuous_capture_split_reads_and_disconnect(monkeypatch,capsys,wrong_mode):
    raw=('NSDF SOURCE incompatible\n' if wrong_mode else ''.join(
        record((i//2)%4,bool(i&1),count=1+i//8,seq=1000+i*100,ms=2000+i*50)
        for i in range(16))).encode()
    chunks=iter(raw[i:i+13] for i in range(0,len(raw),13))
    class Port:
        closed=False
        def __enter__(self):return self
        def __exit__(self,*args):self.closed=True
        def readline(self):return next(chunks)
    port=Port()
    monkeypatch.setitem(sys.modules,'serial',SimpleNamespace(Serial=lambda *a,**kw:port))
    monkeypatch.setattr(sys,'argv',['capture_nsdf_cpu.py','fake','--continuous','--fast-frames','16'])
    if wrong_mode:
        with pytest.raises(RuntimeError,match='expected continuous'):capture_nsdf_cpu.main()
    else:
        capture_nsdf_cpu.main()
        assert capsys.readouterr().out==raw.decode()
    assert port.closed and port.dtr and not port.rts


@pytest.mark.parametrize('scenario', [0, 1, 2, 4])
def test_quiet_production_scheduler_has_no_uart_output(tmp_path, scenario):
    """Keep acquiring and publishing pitch without diagnostic UART traffic.

    The CSR mock checks request cadence, freshness, per-channel frequency, and
    acquisition through stalls; stdout must stay empty with telemetry disabled.
    """
    here = Path(__file__).parent
    exe = tmp_path / 'quiet-scheduler'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'), '--edition=2021', '-O',
                    '--cfg', 'tuner_nsdf_continuous', str(here/'nsdf_trace_mock.rs'),
                    '-o', str(exe)],
                   env=dict(os.environ, TILIQUA_INTONO_NSDF_TRACE='continuous-quiet'),
                   check=True)
    assert subprocess.check_output([exe, str(scenario)], text=True) == ''
