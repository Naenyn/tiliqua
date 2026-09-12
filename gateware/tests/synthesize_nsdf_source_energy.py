"""Isolated resource check; not a full-SoC timing or allocation claim."""
import argparse
from pathlib import Path
import subprocess
from amaranth import Value
from amaranth.back import rtlil
from amaranth.lib import wiring
from top.tuner.experiment.nsdf_source_energy import NsdfSourceEnergy


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path);p.add_argument('--yosys',required=True)
    args=p.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
    dut=NsdfSourceEnergy()
    ports=[Value.cast(member) for _,_,member in wiring.Signature.flatten(dut.signature,dut)]
    il=args.directory/'source_energy.il';netlist=args.directory/'source_energy.json'
    il.write_text(rtlil.convert(dut,ports=ports,name='nsdf_source_energy'))
    subprocess.run([args.yosys,'-p',f'read_rtlil {il}; synth_ecp5 -noiopad -top nsdf_source_energy -json {netlist}; stat'],check=True)
