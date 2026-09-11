"""Measure the existing reusable FFT core in isolation, not the whole design."""
import argparse
from pathlib import Path
import subprocess
from amaranth.back import rtlil
from amaranth import Value
from amaranth.lib import wiring
from tiliqua.dsp.fft import FFT


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--size',type=int,default=1024)
    p.add_argument('--yosys',default='yosys')
    a=p.parse_args();a.directory.mkdir(parents=True,exist_ok=True)
    dut=FFT(sz=a.size)
    ports=[Value.cast(member) for _,_,member in wiring.Signature.flatten(dut.signature,dut)]
    il=a.directory/'fft.il';netlist=a.directory/'fft.json'
    il.write_text(rtlil.convert(dut,ports=ports,name='fft_candidate'))
    subprocess.run([a.yosys,'-p',f'read_rtlil {il}; synth_ecp5 -top fft_candidate -json {netlist}; stat'],check=True)
