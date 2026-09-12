"""Synthetic energy-guard transition limits, not device pitch accuracy evidence.

Use native samples and the actual quantized FIR. A source window is not an
instantaneous amplitude estimate: after attenuation it can temporarily veto
valid quiet audio. Keep that limitation visible before production integration.
"""
import numpy as np
import pytest
from scipy.signal import lfilter
from top.tuner.experiment.nsdf_coefficients import coefficients


def rms(x):
    x=np.asarray(x,dtype=np.float64)
    return np.sqrt(np.mean((x-x.mean())**2))


@pytest.mark.parametrize('frequency',[24,55,880,1400])
@pytest.mark.parametrize('dc', [0,12000])
def test_settled_quiet_low_bank_survives_guard(frequency,dc):
    n=50000;t=np.arange(n)/192000
    x=np.rint(140*np.sin(2*np.pi*frequency*t)+dc)
    filtered=np.floor((lfilter(coefficients(),[1],x)+65536)/131072)
    # /32 publication begins after FIR warmup at exclusive endpoint 800.
    ends=np.arange(800,n+1,32);low=filtered[ends-1]
    for index in range(650,len(ends),71):
        end=ends[index];source_end=end-end%512
        source=rms(x[source_end-20480:source_end])
        frame=rms(low[index-603:index+1])
        assert frame>max(2,.02*source)


def test_large_attenuation_transient_is_bounded_not_instantaneous():
    n=65000;change=30000;t=np.arange(n)/192000
    level=np.where(np.arange(n)<change,14000,100)
    x=np.rint(level*np.sin(2*np.pi*880*t))
    # Once the 674-sample frame is entirely quiet, the long source window
    # still contains loud audio. This intentional rejection must not be
    # mistaken for a detector fault or a permanent loss of quiet sensitivity.
    end=change+1000;source_end=end-end%512
    assert rms(x[end-674:end])<.1*rms(x[source_end-20480:source_end])
    # By 20480 + one publication block, no old amplitude remains.
    for end in range(change+20480+512,n,137):
        source_end=end-end%512
        assert rms(x[end-674:end])>max(2,.1*rms(x[source_end-20480:source_end]))
