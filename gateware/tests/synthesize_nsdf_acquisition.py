"""Isolated implementation-cost check for shared four-channel acquisition."""
import argparse
from pathlib import Path
import subprocess
from amaranth import Value
from amaranth.back import rtlil
from amaranth.lib import wiring
from top.intono.experiment.nsdf_acquisition import NsdfAcquisition
from nsdf_filter_budget import coefficients

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--yosys',required=True)
    a=p.parse_args();a.directory.mkdir(parents=True,exist_ok=True)
    dut=NsdfAcquisition(coefficients())
    ports=[Value.cast(member) for _,_,member in wiring.Signature.flatten(dut.signature,dut)]
    il=a.directory/'acquisition.il';netlist=a.directory/'acquisition.json'
    il.write_text(rtlil.convert(dut,ports=ports,name='nsdf_acquisition'))
    # Internal bus interfaces are not physical package pins.
    subprocess.run([a.yosys,'-p',f'read_rtlil {il}; synth_ecp5 -noiopad -top nsdf_acquisition -json {netlist}; stat'],check=True)
