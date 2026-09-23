from pathlib import Path
import math
import pytest
from summarize_nsdf_schedule import summarize


def test_physical_session_summary_distinguishes_missing_input_and_repeatability():
    text=(Path(__file__).parent/'fixtures/nsdf-publication-in0-removed.txt').read_text()
    result=summarize(text)
    assert len(result['banks'])==8
    assert 0<result['observed_total_selector_cpu_percent']<100
    for r in result['banks']:
        assert r['reports']==25 and r['cumulative_faults']==0
        assert r['acquisitions_per_second']==12.5
        if r['channel']==0:
            assert r['qualified_reports']==0
            assert r['observed_span_cents'] is None and r['observed_mean_hz'] is None
        elif r['bank']=='low':
            assert r['qualified_reports']==25
            assert math.isclose(r['observed_span_cents'],1200*math.log2(r['observed_max_hz']/r['observed_min_hz']),abs_tol=1e-9)
    tail=summarize(text,2)
    assert all(0<=r['duration_seconds']<=2 for r in tail['banks'])
    assert all(r['reports']<=6 for r in tail['banks'])


@pytest.mark.parametrize('duration',[0,-1,float('nan'),float('inf')])
def test_invalid_tail_is_rejected(duration):
    text=(Path(__file__).parent/'fixtures/nsdf-publication-in0-removed.txt').read_text()
    with pytest.raises(ValueError):summarize(text,duration)


def test_bad_or_concatenated_sessions_are_not_silently_repaired():
    text=(Path(__file__).parent/'fixtures/nsdf-publication-in0-removed.txt').read_text()
    for broken in ('',text+text,text.replace('ok=true','ok=unknown',1)):
        with pytest.raises(ValueError):summarize(broken)


def test_single_report_has_no_cadence_or_cpu_claim():
    text=(Path(__file__).parent/'fixtures/nsdf-publication-in0-removed.txt').read_text()
    line=next(x for x in text.splitlines() if x.startswith('NSDF RUN '))+'\n'
    r=summarize(line)
    assert r['observed_total_selector_cpu_percent'] is None
    assert r['banks'][0]['acquisitions_per_second'] is None
