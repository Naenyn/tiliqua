"""Build-time Q17 low-bank coefficients; experimental SciPy dependency only."""
import numpy as np
from scipy.signal import firwin


def coefficients():
    # Low-bank selection ends at 1500 Hz, with native preferred above 1 kHz.
    # The old 2250-Hz cutoff admitted undersampled upper tones: at ~2274 Hz
    # a later NSDF maximum looked like a confident ~754-Hz subharmonic.
    # Keep the existing length/latency, but attenuate >=2200 Hz below 2.2%
    # RMS. The 5% relative energy gate also rejects transition-band mixtures
    # with weak subharmonics. An even lower cutoff hurt narrow pulses near
    # the handoff, so retain >=0.85 gain through the 1500-Hz overlap limit.
    # Response stays flat through 1 kHz. No added RAM, taps, or MAC slots.
    return np.rint(firwin(769,1750,fs=192000,window=('kaiser',8.6))*(1<<17)).astype(np.int64)
