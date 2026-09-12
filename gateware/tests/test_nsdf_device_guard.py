import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import pytest
from analyze_nsdf_fast import analyze_fast
from nsdf_trace_analysis import decode


@pytest.mark.parametrize('fields',['guard=false gc=100','guard=true gc=0',
                                 'guard=maybe gc=100','guard=true','gc=100'])
def test_host_rejects_wrong_or_incomplete_device_guard(fields):
    fixture=Path(__file__).parent/'fixtures/nsdf-fast-low-buffered-steady.txt'
    text=re.sub(r'(^NSDF CPU .*?)$',r'\1 '+fields,fixture.read_text(),flags=re.M)
    with pytest.raises(ValueError):list(analyze_fast(text))


def test_host_accepts_matching_device_guard():
    fixture=Path(__file__).parent/'fixtures/nsdf-fast-low-buffered-steady.txt'
    text=re.sub(r'(^NSDF CPU .*?)$',r'\1 guard=true gc=100',fixture.read_text(),flags=re.M)
    reports=list(analyze_fast(text))
    assert all(r['device_guard'] and r['guarded_qualified'] and r['guard_ms']>0 for r in reports)


def test_physical_device_guard_quiet_low_and_measured_cost():
    text=(Path(__file__).parent/'fixtures/nsdf-fast-low-device-guard.txt').read_text()
    reports=list(analyze_fast(text))
    assert len(reports)==3
    assert all(r['device_guard'] and r['guarded_qualified'] for r in reports)
    assert all(0<r['guard_ms']<0.05 and r['select_ms']+r['guard_ms']<0.9 for r in reports)
    assert all(50<=r['frame_interval_ms']<=50.2 for r in reports[1:])


def reference(v):
    low,ch,seq,frame,end,n,total,q,status,energy,scaled,clipped=v
    offset=((frame-end+(1<<31))&0xffffffff)-(1<<31)
    samples=604 if low else 674
    if ch>3 or n!=20480 or status!=(1|(ch<<2)):return False
    if not (-512<=offset<=512 if low else frame==seq and 0<=offset<=512):return False
    if abs(total)>n*32768 or q>n*(1<<30) or total*total>q*n:return False
    if clipped or energy>samples*(1<<30):return False
    power=(q*n-total*total+n*n-1)//(n*n)
    unscaled=energy*(4 if scaled else 1)
    result=unscaled>4*samples and unscaled*(2500 if low else 100)>power*samples
    # Conservative rounding must NEVER accept what the exact rational gate rejects.
    if result:assert unscaled*n*n*(2500 if low else 100)>(q*n-total*total)*samples
    return result


def test_actual_rust_guard_physical_and_arithmetic_boundaries(tmp_path):
    here=Path(__file__).parent;cases=[]
    for fixture in (here/'fixtures').glob('nsdf-cpu-*.json'):
        data=json.loads(fixture.read_text())
        for s,b in zip(data.get('source_reports',[]),data['frames']):
            if 'frame_end' not in s:continue
            f=next(decode(b.splitlines()))
            cases.append([int(s['low']=='true'),int(s['ch']),int(s['seq']),int(s['frame_end']),
                          int(s['end']),int(s['n']),int(s['sum']),int(s['squares']),int(s['status']),
                          f['energy'],f['scaled'],f['clipped']])
    for fixture in (here/'fixtures').glob('nsdf-fast-*.txt'):
        text=fixture.read_text();reports=list(analyze_fast(text))
        sources={int(s['seq']):s for line in re.findall(r'^NSDF SOURCE .*$',text,re.M)
                 if (s:=dict(p.split('=') for p in line.split()[2:]))}
        for r in reports:
            s=sources[r['sequence']]
            cases.append([int(r['bank']=='low'),r['channel'],r['sequence'],int(s['frame_end']),
                          int(s['end']),int(s['n']),int(s['sum']),int(s['squares']),int(s['status']),
                          r['energy'],r['scaled'],r['clipped']])
    assert len(cases)>40
    rng=random.Random(104)
    for low in (0,1):
        samples=604 if low else 674
        for _ in range(2000):
            total=rng.randint(-20480*32768,20480*32768)
            q=rng.randint((total*total+20479)//20480,20480*(1<<30))
            energy=rng.randrange(samples*(1<<30)+1)
            v=[low,0,10000,10000,10000,20480,total,q,1,energy,rng.randrange(2),0]
            cases.append(v)
        base=[low,0,10000,10000,10000,20480,0,20480*10000,1,samples*100,0,0]
        for field,values in [(1,[1,3,4]),(3,[9487,9488,10000,10512,10513]),
                             (5,[0,19968,20480,20481]),(6,[-2147483648,2147483647]),
                             (7,[0,20480*(1<<30),20480*(1<<30)+1]),
                             (8,[0,2,3,5,17]),(9,[0,4*samples,4*samples+1,samples*(1<<30)+1]),
                             (10,[1]),(11,[1])]:
            for value in values:
                v=base.copy();v[field]=value;cases.append(v)
        for ch in range(4):
            v=base.copy();v[1]=ch;v[8]=1|(ch<<2);cases.append(v)
        # Endpoint counter wrap is legitimate, not stale/future by itself.
        v=base.copy();v[2]=v[3]=128;v[4]=(1<<32)-128;cases.append(v)
        for source_power in [4,100,10000,1<<30]:
            for delta in [-1,0,1]:
                v=base.copy();v[7]=source_power*20480
                v[9]=max(0,source_power*samples//(2500 if low else 100)+delta)
                cases.append(v)
    exe=tmp_path/'guard';rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc')
    subprocess.run([rustc,'--edition=2021','-O','-C','overflow-checks=on',str(here/'nsdf_guard_fixture.rs'),'-o',str(exe)],check=True)
    output=subprocess.run([str(exe)],input=''.join(' '.join(str(int(x)) for x in v)+'\n' for v in cases),
                          capture_output=True,text=True,check=True).stdout.splitlines()
    assert len(output)==len(cases)
    for v,result in zip(cases,output):assert (result=='true')==reference(v),v
