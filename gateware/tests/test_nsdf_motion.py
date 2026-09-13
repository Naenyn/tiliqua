"""Display policy replay and a synthetic low-window motion limitation probe."""
from pathlib import Path
import subprocess
import numpy as np
from analyze_nsdf_schedule import analyze_picks,analyze_comparisons
from nsdf_refinement_probe import scores_for

HERE=Path(__file__).parent

def test_physical_motion_display_does_not_blank_on_bank_disagreement():
    text=(HERE/'fixtures/nsdf-motion-after-in0.txt').read_text()
    picks=list(analyze_picks(text));display=list(analyze_comparisons(text))
    assert len(picks)==len(display)==75
    conflicts=absent=0
    for p,d in zip(picks,display):
        assert p['ms']==d['ms']
        if p['src']==3:
            conflicts+=1
            assert d['src']==2 and d['mhz']==p['n']
        if d['src']==0:
            absent+=1
            assert p['src']==0 and not d['bq']
    assert conflicts==7 and absent==5
    # Decimated hardware snapshots; not a measurement of every UI frame.

def compile_fixture(tmp_path,name):
    exe=tmp_path/name
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O',
                    '-C','overflow-checks=yes',str(HERE/(name+'.rs')),'-o',str(exe)],check=True)
    return exe

def test_actual_display_policy_on_recorded_modulation(tmp_path):
    records=list(analyze_picks((HERE/'fixtures/nsdf-lfo-in0-picks.txt').read_text()))
    assert len(records)==75
    exe=compile_fixture(tmp_path,'nsdf_resolve_fixture')
    payload=''.join(f'{r["n"]} {r["na"]} {int(r["nq"])} {r["l"]} {r["la"]} {int(r["lq"])}\n' for r in records)
    output=subprocess.check_output([exe,'display'],input=payload,text=True).splitlines()
    recovered=0
    for r,line in zip(records,output):
        hz,source=map(int,line.split())
        if r['src']==3:
            assert (hz,source)==(r['n'],2)
            recovered+=1
        elif r['src']==0:
            assert (hz,source)==(0,0) # Never manufacture the five missing pitches.
        else:assert source in (1,2)
    assert recovered==8
    # Replay of decimated snapshots is not a hardware dropout-rate guarantee.

def test_low_window_chirp_confidence_is_not_stationary_accuracy(tmp_path):
    exe=compile_fixture(tmp_path,'nsdf_selector_fixture')
    cases=[]
    for center,slope in [(50,0),(50,100),(50,300),(100,0),(100,300),(100,600)]:
        t=(np.arange(604)-301.5)/6000
        assert min(center+slope*t)>20
        samples=np.rint(10000*np.sin(2*np.pi*(center*t+.5*slope*t*t)+.4))
        cases.append(scores_for(samples,301))
    payload=''.join('low '+' '.join(map(str,s))+'\n' for s in cases)
    lines=subprocess.check_output([exe],input=payload,text=True).splitlines()
    assert [l.split()[2] for l in lines]==['true','true','false','true','true','false']
    # Synthetic counterexample: a clean sine that varies within the ~100-ms
    # window can lose periodicity qualification. This does not identify the
    # user's exact low-end waveform or justify lowering the confidence gate.
