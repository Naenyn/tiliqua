"""Run real allocation-free Rust calibration code on the host."""
from pathlib import Path
import shutil
import subprocess
import re


def test_calibration_menu_overrides_match_option_order():
    """Guard position-based snapshot overrides when CAL fields are removed."""
    firmware = Path(__file__).parents[1] / "src/top/tuner/fw/src"
    options = (firmware / "options.rs").read_text()
    fields = re.findall(r"pub (\w+):", options.split("pub struct CalibrateOpts {")[1].split("}")[0])
    assert fields == ["input", "output", "zero_note", "run"]
    snapshot = (firmware / "main.rs").read_text().split("impl MenuSnapshot {")[1].split("#[inline(never)]")[0]
    overrides = {int(index): label for index, label in re.findall(
        r'\(Page::Calibrate, (\d+)\) => "([^"]+)"', snapshot)}
    assert [overrides.get(i, field) for i, field in enumerate(fields)] == [
        "input", "output", "0v note", "run"]
    formatted_index = re.search(r"page==Page::Calibrate && index==(\d+)", snapshot)
    assert fields[int(formatted_index[1])] == "zero_note"


def test_live_calibration_protocol_and_profile_math(tmp_path):
    compiler = shutil.which("rustc") or str(Path.home()/".cargo/bin/rustc")
    fixture = Path(__file__).with_name("tuner_calibration_live_fixture.rs")
    executable = tmp_path/"calibration-tests"
    subprocess.run([compiler,"--edition=2021","--test",str(fixture),"-o",str(executable)],
                   check=True,capture_output=True,text=True)
    subprocess.run([str(executable)],check=True,capture_output=True,text=True)
