"""Exercise the real fixed-point scale engine without target hardware."""
from pathlib import Path
import shutil
import subprocess
import struct
import zlib
import sys
import pytest
from tuner_scale_import import parse_scl, encode


@pytest.mark.parametrize('module', ['scale', 'quantizer_setup'])
def test_scale_engine(tmp_path, module):
    source = Path(__file__).parents[1] / f'src/top/intono/fw/src/{module}.rs'
    compiler = shutil.which('rustc') or str(Path.home() / '.cargo/bin/rustc')
    executable = tmp_path / 'scale-tests'
    subprocess.run([compiler, '--edition=2021', '--test', str(source), '-o',
                    str(executable)], check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)


def test_scala_ratios_cents_comments_and_non_octave():
    description, degrees, period = parse_scl('! name\nExample\n3\n! comment\n100.0 cents\n3/2 fifth\n3\n')
    assert description == 'Example'
    assert degrees == [0, 100000, 701955]
    assert period == 1901955
    assert parse_scl('\n1\n2/1\n') == ('', [0], 1200000)
    # Large ratio components are supported; intervals that collapse to unison
    # at the chosen fixed-point resolution are explicitly rejected.
    assert parse_scl('x\n1\n2147483647/1073741824\n')[2] == 1200000


@pytest.mark.parametrize('text', [
    '', 'name', 'name\n0\n', 'name\n129\n', 'name\n2\n100.0\n',
    'name\n1\n-2\n', 'name\n1\n1/0\n', 'name\n1\nNaN\n',
    'name\n1\n0.0\n', 'name\n1\n-5.0\n',
    'name\n2\n700.0\n600.0\n', 'name\n2\n100.0001\n100.0002\n',
    'name\n1\n100.0\n200.0\n', 'name\n1\n2147483.648\n',
    'name\n1\n1/2/3\n', 'name\n1\n2147483647/2147483646\n',
])
def test_scala_invalid_or_unsupported_scales_rejected(text):
    with pytest.raises(ValueError):
        parse_scl(text)


def test_binary_python_to_rust_and_corruption_is_atomic(tmp_path):
    source = Path(__file__).parents[1] / 'src/top/intono/fw/src/scale.rs'
    good = encode([0, 100000, 701955], 1901955)
    path = tmp_path / 'good.tscale'
    path.write_bytes(good)
    # Structurally invalid but CRC-correct degree table.
    invalid = bytearray(good)
    struct.pack_into('<i', invalid, 12, 1)
    struct.pack_into('<I', invalid, len(invalid)-4, zlib.crc32(invalid[:-4]))
    bad = tmp_path / 'bad.tscale'
    bad.write_bytes(invalid)
    fixture = tmp_path / 'decode.rs'
    fixture.write_text(f'''
#[path="{source}"] mod scale;
fn main() {{
    let bytes=include_bytes!("{path}");
    let mut storage=[-99;128];
    {{
        let scale=scale::decode(bytes,&mut storage).unwrap();
        assert_eq!(scale.quantize(1901955+701950,0,None),Ok(1901955+701955));
    }}
    let before=storage;
    assert!(scale::decode(include_bytes!("{bad}"),&mut storage).is_err());
    assert_eq!(storage,before);
    for i in 0..bytes.len() {{
        let mut corrupt=*bytes;corrupt[i]^=1;
        assert!(scale::decode(&corrupt,&mut storage).is_err());
        assert_eq!(storage,before);
        assert!(scale::decode(&bytes[..i],&mut storage).is_err());
        assert_eq!(storage,before);
    }}
}}
''')
    compiler = shutil.which('rustc') or str(Path.home() / '.cargo/bin/rustc')
    executable = tmp_path / 'decode'
    subprocess.run([compiler, '--edition=2021', str(fixture), '-o', str(executable)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)


def test_converter_cli_never_overwrites_files(tmp_path):
    script = Path(__file__).with_name('tuner_scale_import.py')
    source = tmp_path / 'custom.scl'
    source.write_text('My custom scale\n3\n100.0\n3/2\n3/1\n')
    output = tmp_path / 'custom.tscale'
    command = [sys.executable, str(script), str(source), str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    expected = encode([0, 100000, 701955], 1901955)
    assert output.read_bytes() == expected
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == expected
    original = source.read_bytes()
    assert subprocess.run(command[:-1] + [str(source)], capture_output=True).returncode != 0
    assert source.read_bytes() == original
    invalid = tmp_path / 'invalid.scl'
    invalid.write_text('Invalid\n2\n700.0\n600.0\n')
    missing = tmp_path / 'not-created.tscale'
    result = subprocess.run([sys.executable, str(script), str(invalid), str(missing)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert not missing.exists()
