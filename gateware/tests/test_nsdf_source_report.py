import json
from pathlib import Path
import pytest
from analyze_nsdf_source import analyze_source


def example(**changes):
    # Synthetic source moments paired with retained CPU scores to exercise the
    # protocol/math, NOT measured evidence of the proposed guard fixing the LFO.
    f=json.loads((Path(__file__).parent/'fixtures/nsdf-cpu-native-div.json').read_text())
    c=f['cpu_reports'][0];i=f['io_reports'][0];b=f['frames'][0]
    source=dict(ch=c['ch'],low=c['low'],seq=c['seq'],end=int(c['seq'])-128,
                n=20480,sum=0,squares=204800000,status=5)
    source.update(changes)
    return '\n'.join(['NSDF SOURCE '+' '.join(f'{k}={v}' for k,v in source.items()),
                      'NSDF CPU '+' '.join(f'{k}={v}' for k,v in c.items()),
                      'NSDF IO '+' '.join(f'{k}={v}' for k,v in i.items()),b])


def test_aligned_native_relative_energy_diagnostic():
    r=next(analyze_source(example()))
    assert r['source_rms']==100 and r['source_age_native']==128
    assert r['qualified'] and not r['native_relative_energy_pass']
    assert next(analyze_source(example(squares=204800)))['native_relative_energy_pass']
    # DC is removed from moments; DC alone must not force a higher audio floor.
    r=next(analyze_source(example(sum=2048000,squares=204800000)))
    assert r['source_rms']==0 and r['native_relative_energy_pass']


@pytest.mark.parametrize('change',[dict(status=1),dict(status=7),dict(end=0),
    dict(sum=999999999),dict(n=20479),dict(squares=-1),dict(seq=0),dict(status=4)])
def test_reject_inconsistent_source_metadata(change):
    with pytest.raises(ValueError):list(analyze_source(example(**change)))


def test_native_sequence_wrap_and_low_bank_units():
    text=example(end=(1<<32)-128).replace('seq=6951261','seq=128')
    assert next(analyze_source(text))['source_age_native']==256
    # Metadata cannot invent native alignment for the decimated sequence.
    text=example().replace('low=false','low=true')
    # Changing score-bank metadata alone is invalid even if source agrees.
    with pytest.raises(ValueError):list(analyze_source(text))


def test_connection_prefix_without_source_is_excluded_not_stitched():
    text=example()
    prefix=text[text.index('NSDF CPU '):]
    assert len(list(analyze_source(prefix+text)))==1
    with pytest.raises(ValueError):list(analyze_source('NSDF ERROR fault\n'+text))
    with pytest.raises(ValueError):list(analyze_source(text+prefix.replace('seq=6951261','seq=123')))


def physical_source_reports(name):
    from capture_nsdf_cpu import complete_cycle
    f=json.loads((Path(__file__).parent/'fixtures'/name).read_text())
    parts=[]
    for s,c,i,b in zip(f['source_reports'],f['cpu_reports'],f['io_reports'],f['frames']):
        for name,fields in [('SOURCE',s),('CPU',c),('IO',i)]:
            parts.append('NSDF '+name+' '+' '.join(f'{k}={v}' for k,v in fields.items())+'\n')
        parts.append(b)
    text=''.join(parts)
    assert complete_cycle(text,require_source=True)
    reports=list(analyze_source(text))
    assert len(reports)==8 and all(r['source_ready'] for r in reports)
    return reports


def test_physical_source_capture_rejects_lfo_false_candidate_on_host():
    reports=physical_source_reports('nsdf-cpu-source-low.json')
    lfo=next(r for r in reports if r['channel']==1 and r['bank']=='native')
    assert lfo['qualified'] and 15000<lfo['hz']<16000
    assert not lfo['native_relative_energy_pass']
    assert 8<lfo['rms_counts']<10 and 140<lfo['source_rms']<150
    sine=next(r for r in reports if r['channel']==0 and r['bank']=='low')
    assert sine['qualified'] and 23<sine['hz']<25
    assert sine['native_relative_energy_pass'] is None # No invented low-bank alignment.


def test_physical_source_capture_preserves_previously_attenuated_native_sine():
    reports=physical_source_reports('nsdf-cpu-source-880.json')
    native=next(r for r in reports if r['channel']==0 and r['bank']=='native')
    low=next(r for r in reports if r['channel']==0 and r['bank']=='low')
    assert native['qualified'] and 880<native['hz']<882
    assert native['native_relative_energy_pass']
    assert .99<native['rms_counts']/native['source_rms']<1.01
    assert low['qualified'] and 880<low['hz']<882
    assert low['native_relative_energy_pass'] is None


def test_physical_source_capture_preserves_quiet_native_sine():
    reports=physical_source_reports('nsdf-cpu-source-quiet075.json')
    native=next(r for r in reports if r['channel']==0 and r['bank']=='native')
    assert native['qualified'] and 879<native['hz']<883
    assert native['native_relative_energy_pass']
    assert 90<native['rms_counts']<110
    assert 90<native['source_rms']<110
    assert .95<native['rms_counts']/native['source_rms']<1.05
    low=next(r for r in reports if r['channel']==0 and r['bank']=='low')
    assert low['qualified'] and 879<low['hz']<883
    assert low['native_relative_energy_pass'] is None
    lfo=next(r for r in reports if r['channel']==1 and r['bank']=='native')
    assert lfo['qualified'] and 15000<lfo['hz']<16000
    assert not lfo['native_relative_energy_pass']
