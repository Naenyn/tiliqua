"""Build-time Q17 low-bank coefficients; experimental SciPy dependency only."""
import numpy as np
from scipy.signal import firwin


def coefficients():
    return np.rint(firwin(769,2250,fs=192000,window=('kaiser',8.6))*(1<<17)).astype(np.int64)
