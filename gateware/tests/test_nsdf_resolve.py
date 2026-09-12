from pathlib import Path
import random
import subprocess
import pytest
from analyze_nsdf_schedule import analyze_picks


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
