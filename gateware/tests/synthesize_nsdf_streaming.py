"""Combined live-acquisition/native-frame/score-engine resource check.

Still excludes low-bank RAM, scheduler, CSR handoff and firmware selector.
Route with --out-of-context --write, not --textcfg: these are internal buses.
"""
import argparse
from pathlib import Path
import subprocess
from amaranth.back import rtlil
from test_nsdf_streaming_integration import StreamingProbe
from amaranth import Value
from amaranth.lib import wiring
from top.intono.experiment.nsdf_frontend import NsdfFrontend
from nsdf_filter_budget import coefficients

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path);p.add_argument('--yosys',required=True)
    p.add_argument('--two-bank',action='store_true')
    a=p.parse_args();a.directory.mkdir(parents=True,exist_ok=True)
    dut=StreamingProbe();ports=[]
    for component,names in [
        (dut.acquisition,'input_valid input_ready sample0 sample1 sample2 sample3 low_valid low_ready low_channel low_sample low_sequence low_clipped overrun'),
        (dut.snapshot,'start cancel length channel busy done fault frame_sequence mean scaled'),
        (dut.score,'length limit ready valid lag score full busy done'),
    ]:
        ports.extend(getattr(component,name) for name in names.split())
    if a.two_bank:
        dut=NsdfFrontend(coefficients())
        ports=[Value.cast(member) for _,_,member in wiring.Signature.flatten(dut.signature,dut)]
    il=a.directory/'streaming.il';netlist=a.directory/'streaming.json'
    il.write_text(rtlil.convert(dut,ports=ports,name='nsdf_streaming'))
    subprocess.run([a.yosys,'-p',f'read_rtlil {il}; synth_ecp5 -noiopad -top nsdf_streaming -json {netlist}; stat'],check=True)
