"""Offline spectral harmonic-fit candidate; NOT deployed FPGA firmware.

Engineering experiment informed by J.O. Smith's Spectral Audio Signal Processing
sections on quadratic peak interpolation and harmonic frequency estimation.
Not a reproduction of his peak-spacing histogram algorithm. Hann window,
zero padding, log-magnitude parabolic peaks, bounded harmonic candidates and
weighted through-origin frequency fitting. Confidence is a heuristic, not truth.
"""
from dataclasses import dataclass
from functools import reduce
from math import gcd
import numpy as np


@dataclass(frozen=True)
class Estimate:
    hz: float
    qualified: bool
    coverage: float
    peaks: int
    fft_size: int


def estimate(samples, sample_rate, min_hz=20, max_hz=20000, padding=4):
    x = np.asarray(samples, dtype=float)
    if x.ndim != 1 or not np.all(np.isfinite(x)):
        raise ValueError('expected finite mono samples')
    if not 0 < min_hz < max_hz < sample_rate/2 or padding < 1:
        raise ValueError('invalid search range or padding')
    if len(x) < 32 or np.ptp(x) == 0:
        return None
    x = x-np.mean(x)
    window = np.hanning(len(x))
    size = 1 << (int(len(x)*padding)-1).bit_length()
    spectrum = np.abs(np.fft.rfft(x*window,size))
    step = sample_rate/size
    local = np.flatnonzero((spectrum[1:-1] > spectrum[:-2]) &
                           (spectrum[1:-1] >= spectrum[2:]))+1
    # Keep frequencies above the requested low bound, including harmonics above
    # the pitch search's high bound. Thresholds are fixed before comparisons.
    floor = max(float(np.max(spectrum))*.01, float(np.median(spectrum))*10)
    local = local[(spectrum[local] > floor) & (local*step >= min_hz*.8)]
    local = sorted(local, key=lambda k:spectrum[k], reverse=True)[:24]
    if not local:
        return None
    frequencies=[]; amplitudes=[]
    for k in local:
        a,b,c=np.log(np.maximum(spectrum[k-1:k+2],1e-100))
        shift=np.clip(.5*(a-c)/(a-2*b+c),-.5,.5)
        frequencies.append((k+shift)*step)
        amplitudes.append(spectrum[k])
    freq=np.asarray(frequencies); weights=np.asarray(amplitudes)**2
    candidates=[]
    for peak in freq:
        for divisor in range(1,9):
            f=peak/divisor
            if not min_hz*(1-1e-4)<=f<=max_hz*(1+1e-4):
                continue
            harmonics=np.rint(freq/f).astype(int)
            # One percent or a quarter unpadded bin, whichever is greater.
            tolerance=np.maximum(.01*freq, .25*sample_rate/len(x))
            matched=(harmonics>=1)&(harmonics<=64)&(np.abs(freq-harmonics*f)<tolerance)
            if not np.any(matched):continue
            h=harmonics[matched]; w=weights[matched]; y=freq[matched]
            # Do not invent an absent subharmonic from a set of all-even etc.
            if reduce(gcd,h.tolist()) != 1:continue
            refined=float(np.sum(w*h*y)/np.sum(w*h*h))
            coverage=float(np.sum(w)/np.sum(weights))
            if min_hz*(1-1e-4)<=refined<=max_hz*(1+1e-4):
                candidates.append((refined,coverage,len(h)))
    if not candidates:return None
    best=max(c[1] for c in candidates)
    # Prefer the highest fundamental explaining essentially the same peaks.
    f,coverage,count=max((c for c in candidates if c[1]>=best*.98),key=lambda c:c[0])
    # A single clean spectral line is valid; pure noise is excluded by peak floor.
    return Estimate(f,coverage>=.9,coverage,count,size)
