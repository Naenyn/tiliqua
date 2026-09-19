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


def test_explicit_native_endpoint_and_serial_line_bound():
    assert next(analyze_source(example(frame_end=6951261)))['source_frame_offset_native']==128
    with pytest.raises(ValueError):list(analyze_source(example(frame_end=6951262)))
    # Firmware retains its 192-byte nonblocking line buffer, even at maxima.
    line=('NSDF SOURCE ch=3 low=false seq=4294967295 end=4294967295 '
          'n=20480 sum=-671088640 squares=21990232555520 status=15 '
          'frame_end=4294967295\n')
    assert len(line)<192
    line=('NSDF CPU ch=3 low=false seq=4294967295 mhz=20000000 '
          'raw=20000000 ppm=1100000 ok=false cycles=4294967295 reads=1307 '
          'guard=false gc=4294967295 policy=2\n')
    assert len(line)<192


def test_export_identifies_selector_policy_without_reinterpreting_archives():
    # This legacy score frame selected an in-range multiple of an out-of-band
    # peak. The new selector rejects it; historical CPU evidence stays intact.
    original=example()
    assert next(analyze_source(original))['qualified']
    with pytest.raises(ValueError,match='unexpected CPU candidate'):
        list(analyze_source(original.replace('NSDF CPU ','NSDF CPU policy=1 ')))
    import re
    def update(match):
        fields=dict(part.split('=') for part in match.group(1).split())
        fields.update(policy='1',mhz='0',raw='0',ppm='0',ok='false')
        return 'NSDF CPU '+' '.join(f'{k}={v}' for k,v in fields.items())
    current=re.sub(r'^NSDF CPU ([^\n]+)',update,original,flags=re.M)
    assert not next(analyze_source(current))['qualified']
    with pytest.raises(ValueError,match='unknown selector policy'):
        list(analyze_source(current.replace('policy=1','policy=3')))


@pytest.mark.parametrize('offset',[-512,-40,0,128,512])
def test_explicit_low_endpoint_diagnostic(offset):
    f=json.loads((Path(__file__).parent/'fixtures/nsdf-cpu-source-quiet075.json').read_text())
    index=next(k for k,c in enumerate(f['cpu_reports']) if c['ch']=='0' and c['low']=='true')
    s=dict(f['source_reports'][index]);s['frame_end']=(int(s['end'])+offset)&0xffffffff
    def text():
        return ''.join('NSDF '+name+' '+' '.join(f'{k}={v}' for k,v in fields.items())+'\n'
            for name,fields in [('SOURCE',s),('CPU',f['cpu_reports'][index]),('IO',f['io_reports'][index])])+f['frames'][index]
    r=next(analyze_source(text()))
    assert r['source_frame_offset_native']==offset and r['low_relative_energy_pass']
    assert r['native_relative_energy_pass'] is None
    s['end']=(1<<32)-256;s['frame_end']=128
    assert next(analyze_source(text()))['source_frame_offset_native']==384
    s['frame_end']=(int(s['end'])+513)&0xffffffff
    with pytest.raises(ValueError):list(analyze_source(text()))


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


def test_physical_endpoint_capture_preserves_quiet_low_edge():
    reports=physical_source_reports('nsdf-cpu-endpoint-lowedge.json')
    assert all(-512<=r['source_frame_offset_native']<=512 for r in reports)
    low=next(r for r in reports if r['channel']==0 and r['bank']=='low')
    assert low['qualified'] and 23<low['hz']<25
    assert low['low_relative_energy_pass']
    assert 85<low['rms_counts']<115 and 85<low['source_rms']<115
    native=next(r for r in reports if r['channel']==0 and r['bank']=='native')
    assert not native['qualified'] and native['hz']==0


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


def test_physical_endpoint_capture_aligns_both_quiet_sine_banks():
    reports=physical_source_reports('nsdf-cpu-endpoint-880.json')
    for report in reports:
        assert report['source_frame_offset_native'] is not None
        assert -512<=report['source_frame_offset_native']<=512
        if report['channel']==0:
            assert report['qualified'] and 878<report['hz']<882
            field=('low_relative_energy_pass' if report['bank']=='low'
                   else 'native_relative_energy_pass')
            assert report[field]
            assert 90<report['rms_counts']<110
    assert any(r['source_frame_offset_native']<0 for r in reports)


def test_physical_endpoint_capture_preserves_quiet_bass_and_rejects_lfo():
    reports=physical_source_reports('nsdf-cpu-endpoint-55.json')
    assert all(-512<=r['source_frame_offset_native']<=512 for r in reports)
    low=next(r for r in reports if r['channel']==0 and r['bank']=='low')
    assert low['qualified'] and 54<low['hz']<56
    assert low['low_relative_energy_pass']
    assert 90<low['rms_counts']<110 and 90<low['source_rms']<110
    lfo=next(r for r in reports if r['channel']==1 and r['bank']=='native')
    assert lfo['qualified'] and 15000<lfo['hz']<16000
    assert not lfo['native_relative_energy_pass']
