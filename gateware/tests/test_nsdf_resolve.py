from pathlib import Path
import random
import subprocess
import pytest
from analyze_nsdf_schedule import analyze_picks,analyze_schedule


def reference(n,na,nq,l,la,lq):
    nq=bool(nq) and na<=250 and 600000<=n<=20000000
    lq=bool(lq) and la<=250 and 20000<=l<=1500000
    if not nq and not lq:return (0,0)
    if not nq:return (l,1)
    if not lq:return (n,2)
    if abs(n-l)*50>min(n,l):return (0,3)
    return (l,1) if l<=1000000 else (n,2)


def test_actual_rust_resolver_bounds_disagreement_and_random_cases(tmp_path):
    cases=[]
    for n in (0,599999,600000,880000,1000000,1500000,20000000,20000001,0xffffffff):
        for l in (0,19999,20000,880000,1000000,1000001,1500000,1500001,0xffffffff):
            for age in (0,250,251,0xffffffff):
                for nq,lq in ((0,0),(0,1),(1,0),(1,1)):
                    cases.extend([(n,age,nq,l,0,lq),(n,0,nq,l,age,lq)])
    rng=random.Random(7)
    for _ in range(4000):
        cases.append((rng.randrange(20000001),rng.randrange(400),1,rng.randrange(1500001),rng.randrange(400),1))
    cases.extend([(880000,0,1,440000,0,1),(880000,0,1,897600,0,1),
                  (880000,0,1,897601,0,1),(880000,251,1,440000,0,1)])
    exe=tmp_path/'resolve';here=Path(__file__).parent
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O','-C','overflow-checks=yes',
                    str(here/'nsdf_resolve_fixture.rs'),'-o',str(exe)],check=True)
    output=subprocess.check_output([exe],input=''.join(' '.join(map(str,c))+'\n' for c in cases),text=True)
    actual=[tuple(map(int,line.split())) for line in output.splitlines()]
    assert actual==[reference(*c) for c in cases]
    assert reference(880000,0,1,440000,0,1)==(0,3)
    assert reference(880000,251,1,440000,0,1)==(440000,1)


def test_serial_resolver_reports_verified_not_trusted():
    line='NSDF PICK ch=0 ms=1000 n=880000 na=10 nq=true l=881000 la=25 lq=true mhz=881000 src=1\n'
    assert list(analyze_picks(line))[0]['src']==1
    for bad in (line.replace('mhz=881000','mhz=880000'),line.replace('src=1','src=2'),
                line.replace('nq=true','nq=maybe'),line.replace('la=25','la=251')):
        with pytest.raises(ValueError):list(analyze_picks(bad))


@pytest.mark.parametrize('overlap',[False,True])
def test_physical_four_input_resolution_and_schedule(overlap):
    name='nsdf-resolve-overlap-1200.txt' if overlap else 'nsdf-resolve-four-tones.txt'
    text=(Path(__file__).parent/'fixtures'/name).read_text()
    picks=list(analyze_picks(text));runs=list(analyze_schedule(text))
    assert len(picks)==(99 if overlap else 100) and len(runs)==200
    ranges=[(24900,25200),(775000,778000),(174000,177000),(138000,140000)]
    if overlap:ranges[0]=(1200000,1202000)
    for ch,(lo,hi) in enumerate(ranges):
        group=[p for p in picks if p['ch']==ch]
        # Capture stops on RUN 200; its trailing PICK may remain on the wire.
        assert len(group)==(24 if overlap and ch==3 else 25)
        source=2 if overlap and ch==0 else 1
        assert all(lo<p['mhz']<hi and p['src']==source for p in group)
        if overlap and ch==0:assert all(p['nq'] and p['lq'] for p in group)
        for low in (False,True):
            group=[r for r in runs if (r['ch'],r['low'])==(ch,low)]
            a,b=group[0],group[-1]
            assert 11.2<(b['count']-a['count'])*1000/(b['ms']-a['ms'])<11.5
    assert all(r['faults']==0 and r['age']<=90 for r in runs)
    assert all(p['nq'] for p in picks if p['ch']==1)
    # Selection checked for reported snapshots only, not every acquisition.
