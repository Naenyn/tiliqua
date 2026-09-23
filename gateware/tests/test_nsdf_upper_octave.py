"""Characterize the captured ambiguity; do not silently redefine ground truth."""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from analyze_nsdf_wave import replay
from nsdf_refinement_probe import scores_for
from nsdf_trace_analysis import select


def test_generate3_small_phase_adjustment_crosses_octave_boundary():
    fixture=json.loads((Path(__file__).parent/'fixtures/generate3-phase-boundary.json').read_text())
    results={}
    for frame in fixture['captures']:
        assert frame['score_parity_checked'] and not frame['clipped']
        assert sum(x*x for x in frame['samples'])==frame['energy']
        scores=replay(frame['samples'],621)
        result=select(scores,192000,600,20000,fallback=True,refine_quality=True)
        assert result['qualified']
        assert abs(1200*math.log2(result['hz']/frame['hz']))<.005
        results[frame['setting'],frame['channel']]=result['hz']
    # The same physical FUND output changes selection after a phase adjustment;
    # CORE remains near 7.9 kHz. This is not universal intended-pitch ground truth.
    assert abs(1200*math.log2(results['before',1]/results['before',2]))<1
    assert abs(1200*math.log2(results['after',1]/results['after',2]/2))<1
    assert abs(1200*math.log2(results['after',2]/results['before',2]))<10


def test_generate3_capture_documents_cutoff_tradeoff():
    fixture=json.loads((Path(__file__).parent/'fixtures/generate3-upper-octave-capture.json').read_text())
    for frame in fixture['captures']:
        samples=frame['samples']
        assert not frame['clipped'] and frame['score_parity_checked']
        assert sum(x*x for x in samples)==frame['energy']
        scores=replay(samples,621)
        original=select(scores,192000,600,20000,fallback=True,refine_quality=True)
        alternative=select(scores,192000,600,20000,fallback=True,refine_quality=True,relative_cutoff=.85)
        assert original['qualified'] and alternative['qualified']
        assert abs(1200*math.log2(original['hz']/frame['hz']))<.005
        ratio=2 if frame['channel']==2 else 1
        assert abs(1200*math.log2(alternative['hz']/original['hz']/ratio))<.1
        # This is evidence of a selection-policy ambiguity, not proof that
        # the weaker subharmonic originated in the oscillator rather than ADC.


@pytest.mark.parametrize('ratio,expected_90,expected_85',[
    (.15,18000,18000),(.20,18000,18000),(.23,9000,18000),
    (.25,9000,18000),(.28,9000,18000),(.30,9000,9000),
])
def test_relaxing_cutoff_moves_rather_than_removes_octave_boundary(ratio,expected_90,expected_85):
    # The identical signal can be described as an imperfect 18-kHz sine with
    # a 9-kHz subharmonic OR a 9-kHz fundamental with a dominant second harmonic.
    # This characterizes policy, not universal intended-pitch ground truth.
    t=np.arange(674)/192000
    for phase in np.linspace(0,1,16,endpoint=False):
        samples=np.rint(12000*(np.sin(2*np.pi*18000*t+phase*2*np.pi)
                              +ratio*np.sin(2*np.pi*9000*t+.4)))
        scores=scores_for(samples,621)
        for cutoff,expected in ((.9,expected_90),(.85,expected_85)):
            result=select(scores,192000,600,20000,fallback=True,
                          refine_quality=True,relative_cutoff=cutoff)
            assert result and result['qualified']
            assert abs(1200*math.log2(result['hz']/expected))<2
