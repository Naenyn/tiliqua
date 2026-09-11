"""Bounded period-verification experiment; not part of the installed detector.

Compare a candidate period and its first four multiples against a short stored
waveform. This checks waveform repetition rather than counting more crossings.
"""
import math

DEPTH = 2048
PAIRS = 256
CAPTURE_RATE = 24_000


def verify(samples, crossing_hz):
    """Return residuals (per mille) for period multipliers 1..4.

    Integer Q8 linear interpolation; evenly spread comparison pairs. Ratios
    are normalized by the observed range so input DC does not affect the score.
    Missing history returns None for that candidate, never a passing score.
    """
    scores = []
    if round(CAPTURE_RATE * 256 / crossing_hz) < 6*256:
        return [None]*4
    for multiple in range(1, 5):
        lag_q8 = round(CAPTURE_RATE * 256 * multiple / crossing_hz)
        lag, fraction = divmod(lag_q8, 256)
        available = len(samples) - 32 - lag - 1
        if lag < 2 or available < PAIRS:
            scores.append(None)
            continue
        error = 0
        low, high = 32767, -32768
        for point in range(PAIRS):
            index = len(samples)-1 - point * (available-1)//PAIRS
            current = samples[index]
            delayed = (samples[index-lag]*(256-fraction)
                       + samples[index-lag-1]*fraction + 128) >> 8
            error += abs(current-delayed)
            low, high = min(low, current, delayed), max(high, current, delayed)
        scores.append(error * 1000 // (PAIRS * (high-low)) if high > low else None)
    return scores


def waveform(*, frequency=440, amplitude=4000, second_harmonic=0,
             initial_phase=0, offset=0, duty=0.5, kind="sine"):
    """Eight-sample box decimation mirrors a cheap possible capture path."""
    samples = []
    for n in range(DEPTH):
        total = 0
        for sub in range(8):
            phase = (initial_phase+(8*n+sub)*frequency/192_000) % 1
            value = {"sine": lambda: math.sin(math.tau*phase),
                     "pulse": lambda: 1 if phase < duty else -1}[kind]()
            value += second_harmonic*math.sin(2*math.tau*phase)
            total += max(-32768, min(32767, round(offset+amplitude*value)))
        samples.append(total >> 3)
    return samples


if __name__ == "__main__":
    for frequency in (32.7032, 110, 440, 880, 1760, 7040):
        for harmonic in (0, 0.25, 0.75, 1.5):
            crossing_hz = frequency * (2 if harmonic >= 0.75 else 1)
            print(frequency, harmonic,
                  verify(waveform(frequency=frequency, second_harmonic=harmonic), crossing_hz))
