# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Pure filterbank constants shared by the REZO family."""

import math


class RezoCoreConstants:
    """Common numeric contract; contains no signals or elaborated hardware."""

    N_BANDS = 10
    INPUT_UNITY = 32768
    INPUT_MAX = 65535
    INPUT_UNITY_POS = 52428
    PARAM_SLEW_STEP = 64

    # Proven input conditioner from the last hardware-clean DSP path. It is
    # independent of the user-facing feedback safety controls.
    INPUT_LIMIT_KNEE = 12288
    INPUT_LIMIT_SHIFT = 3  # 8:1 above the knee

    CV_TARGET_FEEDBACK = 0
    CV_TARGET_RESONANCE = 1
    CV_TARGET_DRIVE = 2
    CV_TARGET_GROUP_BASE = 3
    N_GROUPS = 4

    DRIVE_FLOOR = 8192       # 0.25x resonator excitation
    DRIVE_DEFAULT = 8192     # + floor = established 0.5x excitation
    DRIVE_MAX = 24575        # + floor = just below 1.0x

    # The original REZO prototype used the nominal centers of the filterbank
    # that inspired it. LEGACY remains available while OCTAVE is the neutral
    # factory layout for new configurations.
    LEGACY_FREQS_HZ = (29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000)
    OCTAVE_FREQS_HZ = (31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
    PERCEPT_FREQS_HZ = (50, 150, 300, 500, 770, 1150, 1700, 2700, 5300, 12000)

    # Manual editing inserts three logarithmic subdivisions between adjacent
    # factory centers. The low five save bits identify the coarse union and two
    # formerly padded bits persist the fine position.
    COARSE_FREQUENCIES_HZ = tuple(sorted(set((
        *LEGACY_FREQS_HZ, *OCTAVE_FREQS_HZ, *PERCEPT_FREQS_HZ,
    ))))
    FREQ_COARSE_WIDTH = 5
    FREQ_FINE_WIDTH = 2
    FREQ_SUBDIVISIONS = 1 << FREQ_FINE_WIDTH

    frequencies = []
    for index, frequency in enumerate(COARSE_FREQUENCIES_HZ):
        if index + 1 < len(COARSE_FREQUENCIES_HZ):
            next_frequency = COARSE_FREQUENCIES_HZ[index + 1]
        else:
            next_frequency = round(
                frequency * frequency / COARSE_FREQUENCIES_HZ[index - 1])
        for subdivision in range(FREQ_SUBDIVISIONS):
            interpolated = round(
                frequency * (next_frequency / frequency) **
                (subdivision / FREQ_SUBDIVISIONS))
            if index + 1 < len(COARSE_FREQUENCIES_HZ):
                interpolated = min(interpolated, next_frequency - 1)
            frequencies.append(max(frequency, interpolated))
    FREQUENCIES_HZ = tuple(frequencies)
    del frequencies, index, frequency, next_frequency, subdivision, interpolated
    FREQ_INDEX_WIDTH = (len(FREQUENCIES_HZ) - 1).bit_length()

    LAYOUT_LEGACY = 0
    LAYOUT_OCTAVE = 1
    LAYOUT_PERCEPT = 2
    LAYOUT_USER = 3

    @classmethod
    def frequency_index(cls, frequency):
        return cls.FREQUENCIES_HZ.index(frequency)

    @staticmethod
    def cutoff_coeff(freq_hz, fs):
        # Chamberlin SVF coefficient, kept below 1.0 for fixed-point headroom.
        return min(0.98, 2.0 * math.sin(math.pi * freq_hz / (2.0 * fs)))
