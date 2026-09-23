import importlib
import math
import os
import numpy as np
import pytest
from nsdf_banked_probe import estimate
from nsdf_filter_budget import report


@pytest.fixture
def reference(monkeypatch):
    path=os.environ.get('TUNER_NSDF_TESTS')
    if not path:pytest.skip('set TUNER_NSDF_TESTS to the independent NSDF branch tests')
    monkeypatch.syspath_prepend(path)
    return importlib.import_module('nsdf_reference')


def test_filter_response_budget():
    assert report()['planned_ebr_total']<report()['device_ebr']


@pytest.mark.parametrize('frequency',[20.37,55.3,599.7,600.3,997.1,7678.1,16003.7,19953])
@pytest.mark.parametrize('gain',[72,12000])
def test_refined_sines_and_bank_boundary(reference,frequency,gain):
    x=np.rint(12000+gain*np.sin(2*np.pi*(frequency*np.arange(23000)/192000+.17))).astype(np.int16)
    before=x.copy();r=estimate(x,reference,refine=True)['result']
    np.testing.assert_array_equal(x,before)
    assert r and r['qualified']
    assert abs(1200*math.log2(r['hz']/frequency))<1


@pytest.mark.parametrize('kind',['silence','noise'])
def test_rejection(reference,kind):
    x=np.zeros(23000,dtype=np.int16) if kind=='silence' else np.random.default_rng(1).integers(-12000,12001,23000)
    assert estimate(x,reference,refine=True)['result'] is None


@pytest.mark.xfail(strict=True,reason='Aliased thin pulse yields a qualified low-bank subharmonic')
def test_aliased_thin_pulse_not_false_low_pitch(reference):
    f=7678.1;p=np.arange(23000)*f/192000+.17
    x=np.where(p%1<.01,12000,-12000)
    r=estimate(x,reference,refine=True)['result']
    assert r is None or abs(1200*math.log2(r['hz']/f))<50
