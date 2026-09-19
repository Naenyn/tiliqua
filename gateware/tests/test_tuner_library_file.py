from pathlib import Path
import struct
import subprocess
import sys
import zlib
import pytest
from tuner_library_file import decode,scala_text
from tuner_scale_import import encode,parse_scl


def profile(version=2,count=129):
    body=bytearray(36)
    body[:12]=b'TUCP'+bytes([version,1,2,60,8,count,3 if version==2 else 0,0])
    body[12:20]=b'Generate'
    for i in range(count):
        uv=(-5_000_000+i*10_000_000//(count-1)) if version==2 else i*2_000_000//(count-1)
        body+=struct.pack('<ii',uv,6_000_000+uv*6//5)
    return bytes(body)+struct.pack('<I',zlib.crc32(body))


def reseal(body):return bytes(body[:-4])+struct.pack('<I',zlib.crc32(body[:-4]))


def test_full_refined_profile_and_legacy_inspection():
    for version,count in [(1,32),(2,121),(2,129)]:
        data=profile(version,count);r=decode(data)
        assert (r['kind'],r['name'],r['zero_note'])==('oscillator_profile','Generate','C4')
        assert len(r['points'])==count
        assert r['limited_low']==r['limited_high']==(version==2)
        assert r['input']==1 and r['output']==2
        with pytest.raises(ValueError):scala_text(r)


@pytest.mark.parametrize('degrees,period',[
    ([0],1),([0],1_200_000),([0,190_195,701_955],1_901_955),
    ([i*50_000 for i in range(24)],1_200_000),
    ([i*10_000 for i in range(128)],1_280_000),([0,1_000_000_000],2_147_483_647),
])
def test_scale_export_roundtrips_exactly_including_non_octave_periods(degrees,period):
    data=encode(degrees,period);r=decode(data)
    description,restored,repeat=parse_scl(scala_text(r,'Round trip'))
    assert description=='Round trip' and encode(restored,repeat)==data


def test_offline_rejection_matches_actual_firmware_codecs(tmp_path):
    here=Path(__file__).parent;exe=tmp_path/'library'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O',
                    '-C','overflow-checks=yes',str(here/'tuner_library_fixture.rs'),'-o',str(exe)],check=True)
    originals=[profile(),profile(1,32),encode([0,190_195,701_955],1_901_955),encode([0],1)]
    cases=[]
    for original in originals:
        cases.extend([original,original+b'\0'])
        cases.extend(original[:n] for n in range(len(original)))
        for i in range(len(original)):
            broken=bytearray(original);broken[i]^=1
            cases.append(bytes(broken))
            cases.append(reseal(broken)) # semantic corruption with a valid CRC
    lines=subprocess.check_output([exe],input=''.join(data.hex()+'\n' for data in cases),text=True).splitlines()
    assert len(lines)==len(cases)
    for data,line in zip(cases,lines):
        try:decode(data);accepted=True
        except ValueError:accepted=False
        assert accepted==(line=='true'),data.hex()


def cli(*args):
    return subprocess.run([sys.executable,str(Path(__file__).with_name('tuner_library_file.py')),*map(str,args)],capture_output=True,text=True)


def test_cli_never_overwrites_source_destination_or_symlink(tmp_path):
    source=tmp_path/'scale.tscale';payload=encode([0,700_000],1_200_000);source.write_bytes(payload)
    output=tmp_path/'scale.scl'
    assert cli(source,'--export-scala',output).returncode==0
    assert encode(*parse_scl(output.read_text())[1:])==payload
    before=output.read_bytes()
    assert cli(source,'--export-scala',source).returncode!=0 and source.read_bytes()==payload
    assert cli(source,'--export-scala',output).returncode!=0 and output.read_bytes()==before
    link=tmp_path/'link.scl';link.symlink_to(output)
    assert cli(source,'--export-scala',link).returncode!=0 and output.read_bytes()==before


@pytest.mark.parametrize('description',['','   ','! comment','ok\n999','é','x'*241])
def test_invalid_export_description_creates_nothing(tmp_path,description):
    source=tmp_path/'scale';source.write_bytes(encode([0],1_200_000));output=tmp_path/'new.scl'
    assert cli(source,'--export-scala',output,'--description',description).returncode!=0
    assert not output.exists()


def test_profile_or_corrupt_or_oversized_file_cannot_be_exported_as_scale(tmp_path):
    source=tmp_path/'input';output=tmp_path/'new.scl'
    for payload in (profile(),b'TSC1'+bytes(2000),encode([0],1_200_000)[:-1]):
        source.write_bytes(payload)
        assert cli(source,'--export-scala',output).returncode!=0
        assert not output.exists() and source.read_bytes()==payload
