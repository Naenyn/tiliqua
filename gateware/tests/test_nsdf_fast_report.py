"""Synthetic summary envelopes around retained physical measurements."""
import json
from pathlib import Path
import pytest
from analyze_nsdf_fast import analyze_fast


def example(delta=0,low=True):
    f=json.loads((Path(__file__).parent/'fixtures/nsdf-cpu-endpoint-880.json').read_text())
    i=next(i for i,c in enumerate(f['cpu_reports']) if c['ch']=='0' and (c['low']=='true')==low)
    s=dict(f['source_reports'][i]);c=dict(f['cpu_reports'][i])
    frame=dict(p.split('=') for p in f['frames'][i].splitlines()[0].split()[2:])
    for k in ('end','frame_end'):s[k]=str((int(s[k])+delta*9600)&0xffffffff)
    for d in (s,c,frame):d['seq']=str((int(d['seq'])+delta*(300 if low else 9600))&0xffffffff)
    fast={k:frame[k] for k in ('ch','low','seq','energy','scaled','clipped')}
    fast.update(start_ms=2000+delta*50,end_ms=2040+delta*50)
    return ''.join('NSDF '+name+' '+' '.join(f'{k}={v}' for k,v in fields.items())+'\n'
                   for name,fields in [('SOURCE',s),('CPU',c),('FAST',fast)])


@pytest.mark.parametrize('low',[False,True])
def test_summary_timing_and_energy_without_claiming_score_parity(low):
    reports=list(analyze_fast(example(low=low)+example(1,low)))
    assert len(reports)==2 and all(r['guarded_qualified'] for r in reports)
    assert reports[1]['frame_interval_ms']==50
    assert all(not r['score_parity_checked'] for r in reports)


@pytest.mark.parametrize('change',[
    lambda t:t.replace('frame_end=','bad_end='),
    lambda t:t.replace('end_ms=2040','end_ms=1999'),
    lambda t:t.replace('scaled=0','scaled=3'),
    lambda t:t.replace('ch=0','ch=1'),
    lambda t:t.replace('ok=true','ok=maybe'),
    lambda t:t.replace('NSDF CPU','IGNORED CPU'),
    lambda t:'NSDF ERROR fault\n'+t,
])
def test_bad_summary_rejected(change):
    with pytest.raises(ValueError):list(analyze_fast(change(example())))


def test_connection_fragments_cadence_and_missing_interior_record():
    text=example();prefix=text[text.index('NSDF CPU '):]
    assert len(list(analyze_fast(prefix+text)))==1
    assert len(list(analyze_fast(text+example(1)[:20])))==1
    with pytest.raises(ValueError):list(analyze_fast(text+text))
    with pytest.raises(ValueError):list(analyze_fast(text.replace('NSDF FAST','IGNORED FAST')+example(1)))
    with pytest.raises(ValueError):list(analyze_fast(text+example(1).replace('start_ms=2050','start_ms=2049')))


def test_worst_case_fast_line_fits_existing_buffer():
    text=('NSDF FAST ch=3 low=false seq=4294967295 energy=723701989376 '
          'scaled=1 clipped=1 start_ms=18446744073709551615 end_ms=18446744073709551615\n')
    assert len(text)<192


@pytest.mark.parametrize('policy',['3','4'])
def test_current_native_summary_uses_extended_geometry(policy):
    import re
    text=example(low=False)
    def update(match):
        f=dict(p.split('=') for p in match.group(1).split())
        f.update(policy=policy,reads='1000')
        return 'NSDF CPU '+' '.join(f'{k}={v}' for k,v in f.items())
    current=re.sub(r'^NSDF CPU ([^\n]+)',update,text,flags=re.M)
    assert next(analyze_fast(current))['frame_samples']==674
    with pytest.raises(ValueError,match='invalid selector work'):
        list(analyze_fast(current.replace(f'policy={policy}','policy=2')))
