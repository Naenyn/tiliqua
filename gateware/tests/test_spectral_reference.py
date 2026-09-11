import math
import json
from pathlib import Path
import numpy as np
import pytest
from spectral_reference import estimate


@pytest.mark.parametrize('f',[55.3,440.3,7678.1,19950])
def test_sine(f):
    x=np.sin(2*np.pi*f*np.arange(19204)/192000)
    result=estimate(x,192000)
    assert result and result.qualified
    assert abs(1200*math.log2(result.hz/f))<2


@pytest.mark.parametrize('missing',[False,True])
def test_harmonics(missing):
    t=np.arange(19204)/192000; f=440.3
    x=1.5*np.sin(4*np.pi*f*t)+.7*np.sin(6*np.pi*f*t)
    if not missing:x+=np.sin(2*np.pi*f*t)
    result=estimate(x,192000)
    assert result and result.qualified
    assert abs(1200*math.log2(result.hz/f))<1


def test_dc_gain_and_silence():
    x=np.sin(2*np.pi*440.3*np.arange(19204)/192000)
    assert estimate(x,192000).hz==pytest.approx(estimate(72*x+12000,192000).hz)
    assert estimate(np.ones(19204),192000) is None
    assert estimate(np.ones(10),192000) is None
    assert estimate(np.random.default_rng(1).normal(size=19204),192000) is None


def test_invalid():
    with pytest.raises(ValueError):estimate([1,float('nan')],192000)
    with pytest.raises(ValueError):estimate(np.ones(100),192000,max_hz=100000)


@pytest.mark.xfail(strict=True,reason='100-ms Hann spectrum is biased near 20 Hz')
def test_low_sine_accuracy_limit():
    f=20.1
    x=np.rint(12000*np.sin(2*np.pi*(f*np.arange(19204)/192000+.03)))
    result=estimate(x,192000)
    assert result and result.qualified and abs(1200*math.log2(result.hz/f))<1


@pytest.mark.xfail(strict=True,reason='Directly sampled discontinuity aliases into a false harmonic series')
def test_aliasing_limit():
    f=19953
    x=np.rint(12000*(2*((np.arange(19204)*f/192000+.17)%1)-1))
    result=estimate(x,192000)
    assert result and result.qualified and abs(1200*math.log2(result.hz/f))<50


@pytest.mark.parametrize('name,low,high',[
    ('tuner-live-sine-1064.json',1060,1068),
    ('tuner-live-saw-1064.json',1060,1068),
    ('tuner-live-pulse-pair-sine-1063.json',1060,1068),
    ('tuner-live-narrow-pulse-1063.json',1060,1068),
    ('tuner-alternating-cycle-capture.json',7600,7750)])
def test_real_capture_repeatability_not_ground_truth(name,low,high):
    data=json.loads((Path(__file__).parent/'fixtures'/name).read_text())
    fs=int(data['header']['fs'])/int(data['header']['div'])
    result=estimate(data['samples'],fs,200,20000)
    assert result and result.qualified and low<result.hz<high
