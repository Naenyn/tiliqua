"""Run real allocation-free Rust calibration code on the host."""
from pathlib import Path
import shutil
import subprocess
import re


def test_calibration_menu_overrides_match_option_order():
    """Guard position-based snapshot overrides when CAL fields are removed."""
    firmware = Path(__file__).parents[1] / "src/top/intono/fw/src"
    options = (firmware / "options.rs").read_text()
    fields = re.findall(r"pub (\w+):", options.split("pub struct CalibrateOpts {")[1].split("}")[0])
    assert fields == ["input", "output", "zero_note", "policy", "graph", "run", "accept", "discard", "profiles"]
    snapshot = (firmware / "main.rs").read_text().split("impl MenuSnapshot {")[1].split("#[inline(never)]")[0]
    overrides = {int(index): label for index, label in re.findall(
        r'\(Page::Calibrate, (\d+)\) => "([^"]+)"', snapshot)}
    assert [overrides.get(i, field) for i, field in enumerate(fields)] == [
        "input", "output", "0v note", "policy", "graph", "run", "accept", "discard", "profiles"]
    formatted_index = re.search(r"page == Page::Calibrate && index == (\d+)", snapshot)
    assert fields[int(formatted_index[1])] == "zero_note"


def test_live_calibration_protocol_and_profile_math(tmp_path):
    compiler = shutil.which("rustc") or str(Path.home()/".cargo/bin/rustc")
    fixture = Path(__file__).with_name("tuner_calibration_live_fixture.rs")
    executable = tmp_path/"calibration-tests"
    subprocess.run([compiler,"--edition=2021","--test",str(fixture),"-o",str(executable)],
                   check=True,capture_output=True,text=True)
    subprocess.run([str(executable)],check=True,capture_output=True,text=True)


def test_all_menu_pages_fit_without_hidden_scrolling():
    firmware = Path(__file__).parents[1] / "src/top/intono/fw/src"
    main = (firmware / "main.rs").read_text()
    assert "entries: [Option<MenuEntrySnapshot>; 9]" in main
    snapshot = main.split("impl MenuSnapshot {")[1].split("#[inline(never)]")[0]
    assert "let index = row;" in snapshot
    options = (firmware / "options.rs").read_text()
    for name, body in re.findall(r"pub struct (\w+Opts) \{(.*?)\n\}", options, re.S):
        assert len(re.findall(r"pub \w+:", body)) <= 9, name
    display = (firmware.parents[1] / "display.py").read_text()
    constants = {key: int(value) for key, value in re.findall(
        r"\b(MENU_Y|MENU_H|MENU_TEXT_Y|MENU_ROW_PITCH) = (\d+)", display)}
    assert constants["MENU_TEXT_Y"] + 8 * constants["MENU_ROW_PITCH"] + 15 <= \
        constants["MENU_Y"] + constants["MENU_H"]


def test_scale_editor_and_routes_share_configuration_but_only_routes_run():
    firmware = Path(__file__).parents[1] / "src/top/intono/fw/src"
    options=(firmware/'options.rs').read_text()
    fields=re.findall(r'pub (\w+):',options.split('pub struct QuantizerOpts {')[1].split('}')[0])
    assert fields==['output','scale','root','transpose','mapping','notes','setups','routes']
    main=(firmware/'main.rs').read_text()
    assert '(Page::Play, 2) => "0v note"' in main
    assert 'page == Page::Play && index == 2' in main
    assert 'Page::Quantizer => "SCALES"' in main
    assert 'Page::Play => "ROUTES"' in main
    assert '!c.quantize && c.correction == 0' in main
    assert 'quantizer.run' not in main
    assert 'if lane.arm_route(' in main
    assert 'if q.lanes[old].active' in main
    assert 'edited = q.configs[old];' in main
    assert '(Page::Play,6) => "RUN/STOP"' in main
    presets=options.split('pub enum ScalePreset {')[1].split('}')[0]
    assert re.findall(r'^\s*(\w+),', presets, re.M)==[
        'Chromatic','Major','Minor','MajorPentatonic','MinorPentatonic','Edo24','Custom2']
    assert 'Page::Quantizer' in (firmware/'runtime.rs').read_text()


def test_calibration_children_are_not_top_level_modes_and_manual_improve_is_advanced():
    firmware = Path(__file__).parents[1] / "src/top/intono/fw/src"
    options = (firmware / 'options.rs').read_text()
    for page in ['Verify', 'Profiles', 'QuantNotes', 'QuantSetups']:
        assert f'#[strum(disabled)]\n    {page},' in options
    verify = options.split('pub struct VerifyOpts {')[1].split('}')[0]
    assert re.findall(r'pub (\w+):', verify) == [
        'run', 'improve', 'accept', 'discard', 'back']
    main = (firmware / 'main.rs').read_text()
    assert 'calibration.toggle_automatic(&tuner' in main
    assert 'refine: app.ui.opts.verify.improve.poll()' in main
    assert 'else if header_back {' in main and 'parent' in main


def test_note_slots_fit_menu_and_legacy_slot_is_preserved():
    firmware=Path(__file__).parents[1]/'src/top/intono/fw/src'
    options=(firmware/'options.rs').read_text()
    fields=re.findall(r'pub (\w+):',options.split('pub struct QuantNotesOpts {')[1].split('}')[0])
    assert fields==['octave','note','toggle','clear','fill','learn','save','load','slot']
    assert 'min: 1, max: 8' in options
    record=(firmware/'note_pattern.rs').read_text()
    assert 'KEY + slot as u32 - 1' in record
    main=(firmware/'main.rs').read_text()
    assert 'note_pattern::key(slot)' in main
    assert 'slot == status_slot' in main
    assert 'entries: [Option<MenuEntrySnapshot>; 9]' in main
    display=(firmware.parent.parent/'display.py').read_text()
    def geometry(name):
        return int(re.search(rf'{name} = (\d+)', display).group(1))
    assert geometry('MENU_TEXT_Y') + 8 * geometry('MENU_ROW_PITCH') + 15 <= (
        geometry('MENU_Y') + geometry('MENU_H'))


def test_routes_do_not_consume_audio_or_start_a_second_playback_engine():
    main = (Path(__file__).parents[1] / "src/top/intono/fw/src/main.rs").read_text()
    assert 'static PLAYBACK:' not in main
    assert 'Owner::Play' not in main
    assert 'Owner::Tuner' not in main
    assert 'r.claim(Owner::Quant(n as u8), 1 << c.input, 1 << n)' in main
    assert 'r.focus(app.ui.opts.tuner.input.value, app.tuner_focus)' in main
    assert 'if cal.active() || outputs_running() {' in main
    assert 'return "STOP OUTPUTS BEFORE FLASH READ";' in main
    assert 'BIND CORRECTION ON ROUTE FIRST' in main


def test_scale_ui_preview_and_dense_control_regions(tmp_path):
    compiler = shutil.which("rustc") or str(Path.home()/".cargo/bin/rustc")
    fixture = Path(__file__).with_name("tuner_scale_ui_fixture.rs")
    executable = tmp_path/"scale-ui-tests"
    subprocess.run([compiler,"--edition=2021","--test",str(fixture),"-o",str(executable)],
                   check=True,capture_output=True,text=True)
    subprocess.run([str(executable)],check=True,capture_output=True,text=True)
