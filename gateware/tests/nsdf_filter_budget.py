"""Candidate low-bank filter response and explicit planning budget (not RTL)."""
import json
import numpy as np
from scipy.signal import firwin, freqz
from top.tuner.experiment.nsdf_coefficients import coefficients


def report():
    c=coefficients();f,h=freqz(c/(1<<17),worN=262144,fs=192000)
    passband=20*np.log10(abs(h[f<=1000]));stop=20*np.log10(max(abs(h[f>=3000])))
    overlap_min=float(min(abs(h[f<=1500])))
    upper_max=float(max(abs(h[f>=2200])))
    assert min(passband)>-.01 and max(passband)<.01 and stop<-70
    assert overlap_min>.85 and upper_max<.022
    low_cycles=157493;high_cycles=187243
    return dict(filter_taps=len(c),coefficient_bits=18,
        passband_min_db=float(min(passband)),passband_max_db=float(max(passband)),
        flat_passband_hz=1000,overlap_min_gain=overlap_min,upper_2200hz_max_gain=upper_max,
        stopband_peak_db=float(stop),filter_group_delay_ms=(len(c)-1)/2/192,
        filter_four_channel_macs_per_second=len(c)*6000*4,
        nsdf_four_channel_20hz_cycles_per_second=(low_cycles+high_cycles)*4*20,
        nsdf_60mhz_duty_at_20hz=(low_cycles+high_cycles)*4*20/60e6,
        # Score-engine EBR measured; the other additions are conservative layout
        # allocations, NOT a synthesis report for an integrated design.
        ebr=dict(existing=33,score_engine=2,filter_coefficients=1,
            filter_histories=4,live_two_bank_histories=8,score_double_buffer=2),
        planned_ebr_total=50,device_ebr=56,
        dsp=dict(existing=10,score_engine=3,filter=1),
        planned_dsp_total=14,device_dsp=28,
        unmeasured=['filter RTL and routing','history snapshot/bus contention',
                    'CPU selection and interpolation','whole-bitstream timing',
                    'bank arbitration and continuous capture'])


if __name__=='__main__':print(json.dumps(report(),indent=2))
