"""FFT/IFFT RTL round-trip for NSDF; surrounding arithmetic is a host model.

No Hann window: type-II NSDF needs linear autocorrelation. Zero padding prevents
wraparound. This measures numerical feasibility, not a complete hardware cost.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import numpy as np
from amaranth.sim import Simulator
from amaranth_future import fixed
from tiliqua.dsp.fft import FFT
from tiliqua.test import stream


def transform(x, inverse=False, fractional_bits=15):
    shape=fixed.SQ(1,fractional_bits)
    dut=FFT(sz=len(x),shape=shape,default_ifft=inverse)
    output=[];cycles=0
    async def driver(ctx):
        for k,v in enumerate(x):
            await stream.put(ctx,dut.i,{'first':int(k==0),'sample':{
                'real':fixed.Const(float(v.real),shape=shape),
                'imag':fixed.Const(float(v.imag),shape=shape)}})
            await ctx.tick()
    async def monitor(ctx):
        nonlocal cycles
        ctx.set(dut.o.ready,1)
        while len(output)<len(x):
            if ctx.get(dut.o.valid & dut.o.ready):
                output.append(ctx.get(dut.o.payload.sample.real).as_float()+
                              1j*ctx.get(dut.o.payload.sample.imag).as_float())
            await ctx.tick();cycles+=1
            assert cycles<len(x)*100
    sim=Simulator(dut);sim.add_clock(1/60e6)
    sim.add_process(driver);sim.add_testbench(monitor);sim.run()
    return np.asarray(output),cycles


def probe(samples,fs,low,high,nsdf_module,fractional_bits=15):
    raw=np.asarray(samples,dtype=np.int64)
    centered=raw-int(np.rint(np.mean(raw)))
    shift=max(0,int(np.floor(np.log2(16384/max(1,np.max(np.abs(centered)))))))
    x=centered*(1<<shift)/32768
    last=math.ceil(fs/low)+1
    n=1<<(len(x)+last-1).bit_length()
    padded=np.pad(x,(0,n-len(x)))
    spectrum,forward_cycles=transform(padded.astype(complex),fractional_bits=fractional_bits)
    # Power in exact Q30 units; power-of-two scale keeps sum <= 0.5 so the
    # unnormalized inverse stays in range. Quantization is explicitly Q15.
    power=np.abs(spectrum)**2
    scale=2**math.floor(math.log2(.5/max(1e-30,float(power.sum()))))
    unit=1<<fractional_bits
    quantized=np.rint(power*scale*unit)/unit
    correlation,inverse_cycles=transform(quantized.astype(complex),inverse=True,fractional_bits=fractional_bits)
    correlation=correlation.real[:last+1]*n/scale
    energy=np.concatenate(([0.],np.cumsum(x*x)))
    lag=np.arange(last+1)
    denominator=energy[len(x)-lag]+energy[-1]-energy[lag]
    values=np.divide(2*correlation,denominator,out=np.zeros(last+1),where=denominator>0)
    ideal=nsdf_module.nsdf(x,last)
    # Reuse the exact reference selector, replacing only its correlation values.
    original=nsdf_module.nsdf
    try:
        nsdf_module.nsdf=lambda *args,**kwargs:values
        measured=nsdf_module.estimate(x,fs,low,high)
    finally:
        nsdf_module.nsdf=original
    reference=nsdf_module.estimate(x,fs,low,high)
    return dict(fs=fs,frame=len(x),fft_size=n,min_hz=low,shift=shift,fractional_bits=fractional_bits,
        power_scale=scale,power_bins_retained=int(np.count_nonzero(quantized)),
        cycles=forward_cycles+inverse_cycles,max_nsdf_error=float(np.max(np.abs(values-ideal))),
        rtl_hz=measured.hz if measured else None,qualified=measured.qualified if measured else False,
        reference_hz=reference.hz if reference else None,
        additional_cents=1200*math.log2(measured.hz/reference.hz) if measured and reference else None)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nsdf-tests',type=Path,required=True)
    parser.add_argument('--fractional-bits',type=int,default=15)
    parser.add_argument('--compact',action='store_true',help='6-kHz low bank, allowing a 1024-point FFT')
    args=parser.parse_args();sys.path.insert(0,str(args.nsdf_tests.resolve()))
    import nsdf_reference
    low_fs,low_n=(6000,604) if args.compact else (12000,1204)
    for fs,n,low,high,f in [(low_fs,low_n,20,1500,20.37),
                           (low_fs,low_n,20,1500,440.3),
                           (192000,674,600,20000,7678.1),
                           (192000,674,600,20000,19953.)]:
        for gain in [12000,72]:
            x=np.rint(gain*np.sin(2*np.pi*(f*np.arange(n)/fs+.17)))
            print(json.dumps(dict(kind='sine',frequency=f,gain=gain,
                **probe(x,fs,low,high,nsdf_reference,args.fractional_bits))),flush=True)
    for name in ['tuner-local-parks-narrow-pulse-1001.json',
                 'tuner-local-parks-modulated-blade-attenuated.json']:
        d=json.loads((Path(__file__).parent/'fixtures'/name).read_text())
        print(json.dumps(dict(kind=name,**probe(d['samples'][:674],192000,600,20000,nsdf_reference,args.fractional_bits))),flush=True)
