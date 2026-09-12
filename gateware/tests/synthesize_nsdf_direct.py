"""Synthesize the score engine, excluding filter/history banks/host selection."""
import argparse
from pathlib import Path
import subprocess
from amaranth import Value
from amaranth.back import rtlil
from amaranth.lib import wiring
from nsdf_direct_rtl import NsdfDirect

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--yosys',required=True)
    a=p.parse_args();a.directory.mkdir(parents=True,exist_ok=True)
    dut=NsdfDirect()
    ports=[Value.cast(member) for _,_,member in wiring.Signature.flatten(dut.signature,dut)]
    il=a.directory/'nsdf.il';netlist=a.directory/'nsdf.json'
    il.write_text(rtlil.convert(dut,ports=ports,name='nsdf_candidate'))
    subprocess.run([a.yosys,'-p',f'read_rtlil {il}; synth_ecp5 -top nsdf_candidate -json {netlist}; stat'],check=True)
