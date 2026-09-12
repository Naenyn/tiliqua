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
    ('tuner-local-parks-sine-1001.json',995,1005),
    ('tuner-local-parks-blade-1000.json',995,1005),
    ('tuner-local-parks-modulated-blade.json',495,505),
    ('tuner-local-parks-modulated-blade-attenuated.json',495,505),
    ('tuner-local-parks-square-1001.json',995,1005),
    ('tuner-local-parks-narrow-pulse-1001.json',995,1005),
    ('tuner-alternating-cycle-capture.json',7600,7750)])
def test_real_capture_repeatability_not_ground_truth(name,low,high):
    data=json.loads((Path(__file__).parent/'fixtures'/name).read_text())
    fs=int(data['header']['fs'])/int(data['header']['div'])
    result=estimate(data['samples'],fs,200,20000)
    assert result and result.qualified and low<result.hz<high


@pytest.mark.parametrize('padding',[1,4])
def test_short_narrow_pulse_windows(padding):
    data=json.loads((Path(__file__).parent/'fixtures'/'tuner-local-parks-narrow-pulse-1001.json').read_text())
    # Overlapping observations of one recording, not independent accuracy trials.
    results=[estimate(data['samples'][start:start+1024],192000,400,20000,padding=padding)
             for start in range(0,1025,64)]
    assert all(r and r.qualified and 995<r.hz<1005 for r in results)
    assert 1200*math.log2(max(r.hz for r in results)/min(r.hz for r in results))<1


@pytest.mark.parametrize('padding',[1,4])
@pytest.mark.xfail(strict=True,reason='Selected-peak coverage can qualify harmonics of an out-of-bank repetition rate')
def test_below_bank_modulated_blade_must_not_qualify(padding):
    data=json.loads((Path(__file__).parent/'fixtures'/'tuner-local-parks-modulated-blade-attenuated.json').read_text())
    # Longer-frame references find ~501 Hz repetition. This bank starts at 800 Hz;
    # an apparently strong in-bank spectral series is not sufficient evidence.
    results=[estimate(data['samples'][start:start+512],192000,800,20000,padding=padding)
             for start in range(0,1537,64)]
    assert all(r is None or not r.qualified for r in results)
