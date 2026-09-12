"""Read a synthesized TUNER netlist; no board or project mutations."""
import argparse
from collections import Counter
import json
from pathlib import Path


def group(name):
    for fragment,label in [('.mainram.','cpu_working_ram'),('.cpu.','cpu'),
        ('.fb.','framebuffer_fifo'),('.palette_periph.','palette'),
        ('tuner_display.','display'),('.period_verifier.','legacy_verifier'),
        ('tuner_periph.lane','measurement_lanes'),('.pmod0.','codec_calibration')]:
        if fragment in name:return label
    return 'other'


def audit(path):
    design=json.loads(path.read_text());memory=Counter();dsps=Counter()
    for module in design['modules'].values():
        for name,cell in module.get('cells',{}).items():
            if cell['type']=='DP16KD':memory[group(name)]+=1
            if cell['type']=='MULT18X18D':dsps[group(name)]+=1
    return dict(netlist=str(path.resolve()),ebr=dict(memory),dsp=dict(dsps),
                ebr_total=sum(memory.values()),dsp_total=sum(dsps.values()))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('netlist',type=Path)
    print(json.dumps(audit(p.parse_args().netlist),indent=2))
