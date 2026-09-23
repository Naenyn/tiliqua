"""Actual existing FFT RTL: fixed-point error, spectral peak, and cycle counts.

No ideal quantized FFT is substituted for RTL. This is a forward-transform probe,
not a complete detector, inverse-transform precision test or integration proof.
"""
import json
import math
import numpy as np
from amaranth.sim import Simulator
from amaranth_future import fixed
from tiliqua.dsp.fft import FFT
from tiliqua.test import stream


def peak_hz(spectrum,fs):
    m=np.abs(spectrum[:len(spectrum)//2]);k=int(np.argmax(m[1:]))+1
    if k==len(m)-1:return k*fs/len(spectrum)
    a,b,c=np.log(np.maximum(m[k-1:k+2],1e-100))
    shift=np.clip(.5*(a-c)/(a-2*b+c),-.5,.5)
    return (k+shift)*fs/len(spectrum)


def probe(frequency,fs,gain,n=1024,normalize=False):
    shape=fixed.SQ(1,15);dut=FFT(sz=n,shape=shape)
    # ADC quantization followed by Hann window quantization.
    raw=np.rint(32768*gain*np.sin(2*np.pi*(frequency*np.arange(n)/fs+.17)))
    shift=max(0,int(np.floor(np.log2(16384/max(1,np.max(np.abs(raw))))))) if normalize else 0
    raw=raw*(1<<shift)
    x=np.rint(raw*np.hanning(n))/32768
    output=[];cycles=[0]
    async def driver(ctx):
        for k,v in enumerate(x):
            await stream.put(ctx,dut.i,{'first':int(k==0),'sample':{
                'real':fixed.Const(float(v),shape=shape),'imag':fixed.Const(0,shape=shape)}})
            await ctx.tick()
    async def monitor(ctx):
        # Exercise backpressure, not just continuously ready output.
        while len(output)<n:
            ctx.set(dut.o.ready,cycles[0]%7!=0)
            if ctx.get(dut.o.valid & dut.o.ready):
                output.append(ctx.get(dut.o.payload.sample.real).as_float()+
                              1j*ctx.get(dut.o.payload.sample.imag).as_float())
            await ctx.tick();cycles[0]+=1
            assert cycles[0]<n*100
    sim=Simulator(dut);sim.add_clock(1/60e6)
    sim.add_process(driver);sim.add_testbench(monitor);sim.run()
    output=np.asarray(output);ideal=np.fft.fft(x,norm='forward')
    # Bound quantization error in ADC/output LSBs, not a cents accuracy promise.
    error=float(np.max(np.abs(output-ideal))*32768)
    assert error<4
    actual=peak_hz(output,fs);reference=peak_hz(ideal,fs)
    return dict(frequency=frequency,sample_rate=fs,gain=gain,size=n,normalization_shift=shift,
        cycles=cycles[0],max_complex_error_lsb=error,rtl_hz=actual,
        float_peak_hz=reference,rtl_cents=1200*math.log2(actual/frequency),
        additional_fixed_point_cents=1200*math.log2(actual/reference))


if __name__=='__main__':
    for fs,f in [(6000,20.37),(6000,440.3),(192000,7678.1),(192000,19953)]:
        for gain in [.5,72/32768]:
            print(json.dumps(probe(f,fs,gain)),flush=True)
        print(json.dumps(probe(f,fs,72/32768,normalize=True)),flush=True)
