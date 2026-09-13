"""Offline Scala converter. No USB/device access; never modifies profiles.

Format reference: https://www.huygens-fokker.org/scala/scl_format.html
Usage: python tuner_scale_import.py input.scl output.tscale
The binary is a transport-independent staging format, not yet uploadable.
"""
import argparse
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
import re
import struct
import zlib

MAX_DEGREES = 128
MAX_FILE_BYTES = 1024 * 1024


def parse_scl(text):
    lines = [line for line in text.splitlines() if not line.lstrip().startswith('!')]
    if len(lines) < 2:
        raise ValueError('Missing description or degree count')
    description = lines[0]
    if not re.fullmatch(r'\s*\d+\s*', lines[1]):
        raise ValueError('Invalid degree count')
    count = int(lines[1])
    if not 1 <= count <= MAX_DEGREES:
        raise ValueError('This engine supports 1..128 degrees and a positive repeat interval')
    if len(lines) < count + 2:
        raise ValueError('Incomplete scale')
    if any(line.strip() for line in lines[count + 2:]):
        raise ValueError('Unexpected data after the declared scale')
    values = []
    for index, line in enumerate(lines[2:count + 2], 1):
        # A pitch token may be followed by a human-readable annotation.
        tokens = line.split()
        if not tokens:
            raise ValueError(f'Degree {index}: missing pitch')
        token = tokens[0]
        if len(token) > 256:
            raise ValueError(f'Degree {index}: pitch token exceeds 256 characters')
        with localcontext() as context:
            context.prec = 60
            try:
                if '.' in token:
                    if not re.fullmatch(r'[+-]?(?:\d+\.\d*|\.\d+)', token):
                        raise ValueError('Invalid cents value')
                    cents = Decimal(token)
                else:
                    if not re.fullmatch(r'\d+(?:/\d+)?', token):
                        raise ValueError('Invalid positive ratio')
                    parts = token.split('/')
                    numerator = Decimal(parts[0])
                    denominator = Decimal(parts[1]) if len(parts) == 2 else Decimal(1)
                    if numerator <= 0 or denominator <= 0:
                        raise ValueError('Ratio components must be positive')
                    cents = Decimal(1200) * (numerator / denominator).ln() / Decimal(2).ln()
                if not cents.is_finite() or not 0 < cents <= Decimal(2147483647) / 1000:
                    raise ValueError('Degree outside positive fixed-point range')
                value = int((cents * 1000).to_integral_value(rounding=ROUND_HALF_UP))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f'Degree {index}: {exc}') from exc
        if value <= (values[-1] if values else 0):
            raise ValueError(f'Degree {index}: not increasing or collapsed at 0.001-cent resolution')
        values.append(value)
    # Scala includes the repeat interval, excludes implicit unison.
    return description, [0] + values[:-1], values[-1]


def encode(degrees, period):
    if not 1 <= len(degrees) <= MAX_DEGREES or not 0 < period <= 2147483647:
        raise ValueError('Invalid degree count or period')
    if degrees[0] != 0 or any(type(d) is not int or d < 0 or d >= period for d in degrees):
        raise ValueError('Invalid degrees')
    if any(a >= b for a, b in zip(degrees, degrees[1:])):
        raise ValueError('Degrees must be strictly increasing')
    body = struct.pack('<4sHHi', b'TSC1', len(degrees), 0, period)
    body += struct.pack('<' + 'i' * len(degrees), *degrees)
    return body + struct.pack('<I', zlib.crc32(body))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        with args.source.open('rb') as source:
            data = source.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('Input exceeds 1 MiB limit')
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('latin-1')
        description, degrees, period = parse_scl(text)
        payload = encode(degrees, period)
        # Exclusive creation: a bad import or accidental filename cannot replace
        # the source, another scale, or any existing user file.
        with args.output.open('xb') as output:
            output.write(payload)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Import rejected: {exc}\n')
    print(f'{description}\n{len(degrees)} degrees; repeat {period / 1000:.3f} cents')
    print(f'Wrote {args.output}; offline file only, no device upload performed.')


if __name__ == '__main__':
    main()
