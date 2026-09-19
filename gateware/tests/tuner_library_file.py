"""Offline inspection of TUNER profile/scale files and lossless Scala export.

No USB, serial, device storage or route access. Recognizes content, not suffixes.
Oscillator curves and relative scale intervals are deliberately separate types.
"""
import argparse
import json
from pathlib import Path
import struct
import zlib

MAX_PROFILE_POINTS=129  # 121 scan anchors plus eight bounded refinements
MAX_FILE_BYTES=40+8*MAX_PROFILE_POINTS


def checked_body(data):
    if len(data)<8 or zlib.crc32(data[:-4])!=struct.unpack('<I',data[-4:])[0]:
        raise ValueError('Checksum mismatch or truncated record')
    return data[:-4]


def decode(data):
    if not 20<=len(data)<=MAX_FILE_BYTES:
        raise ValueError('Invalid library record length')
    body=checked_body(data)
    if body[:4]==b'TSC1':
        count,reserved,period=struct.unpack_from('<HHi',body,4)
        if not 1<=count<=128 or reserved or len(data)!=16+4*count or period<=0:
            raise ValueError('Invalid scale header')
        degrees=list(struct.unpack_from('<'+'i'*count,body,12))
        if degrees[0]!=0 or any(not 0<=x<period for x in degrees) or any(a>=b for a,b in zip(degrees,degrees[1:])):
            raise ValueError('Invalid scale degrees')
        return dict(kind='scale',version=1,period_millicents=period,degrees_millicents=degrees)
    if body[:4]!=b'TUCP' or len(data)<56:
        raise ValueError('Unknown library record type')
    version,channel_in,channel_out,zero,name_len,count,flags,reserved=body[4:12]
    if version not in (1,2):raise ValueError('Unsupported profile version')
    maximum=32 if version==1 else MAX_PROFILE_POINTS
    if not (2<=count<=maximum and len(data)==40+8*count and 1<=name_len<=24
            and channel_in<4 and channel_out<4 and 12<=zero<=108
            and flags<=(0 if version==1 else 3) and reserved==0
            and not any(body[12+name_len:36])):
        raise ValueError('Invalid profile header')
    name=body[12:12+name_len]
    if any(not 32<=c<=126 for c in name) or not name.strip():
        raise ValueError('Invalid profile name')
    points=[struct.unpack_from('<ii',body,36+8*i) for i in range(count)]
    lo,hi=(0,2_000_000) if version==1 else (-5_000_000,5_000_000)
    if any(not lo<=voltage<=hi for voltage,_ in points) or any(a[0]>=b[0] or a[1]>=b[1] for a,b in zip(points,points[1:])):
        raise ValueError('Invalid/nonmonotonic calibration curve')
    return dict(kind='oscillator_profile',version=version,name=name.decode('ascii'),
        input=channel_in,output=channel_out,zero_note=note_name(zero),
        limited_low=bool(flags&1),limited_high=bool(flags&2),
        points=[dict(microvolts=uv,pitch_millicents=mc) for uv,mc in points])


def note_name(note):
    return ('C','C#','D','D#','E','F','F#','G','G#','A','A#','B')[note%12]+str(note//12-1)


def scala_text(record,description='TUNER exported scale'):
    if record['kind']!='scale':raise ValueError('An oscillator profile is not a quantization scale')
    if not description or len(description)>240 or not description.strip() or description.lstrip().startswith('!') or any(ord(c)<32 or ord(c)>126 for c in description):
        raise ValueError('Use a nonempty printable ASCII description, not a Scala comment')
    values=record['degrees_millicents'][1:]+[record['period_millicents']]
    # Decimal tokens are always cents in Scala, even for integer cent values.
    return '! TUNER scale export; exact 0.001-cent stored resolution\n'+description+'\n'+str(len(values))+'\n'+''.join(f'{mc//1000}.{mc%1000:03d}\n' for mc in values)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--export-scala',type=Path,help='Create a NEW .scl from a validated TSC1 scale')
    parser.add_argument('--description',default='TUNER exported scale')
    args=parser.parse_args()
    try:
        with args.source.open('rb') as stream:data=stream.read(MAX_FILE_BYTES+1)
        record=decode(data)
        if args.export_scala:
            text=scala_text(record,args.description)
            # Existing source/destination, symlink or invalid record must never
            # be overwritten. No create attempt happens before full validation.
            with args.export_scala.open('x',encoding='ascii') as stream:stream.write(text)
        print(json.dumps(record,indent=2))
    except (ValueError,OSError) as exc:parser.exit(1,f'Library file rejected: {exc}\n')


if __name__=='__main__':main()
