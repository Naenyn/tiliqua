import subprocess
import sys
from pathlib import Path
import pytest
from top.rezo.help_content import (HELP_LINES, HELP_COLUMNS, HELP_ROM_LINES,
    HELP_VISIBLE_ROWS, HELP_SCROLL_MAX, HELP_X_CELL, HELP_Y_CELL,
    HELP_BODY_BASE_ROWS, HELP_HEADER_ROWS, HELP_STATUS_ROW, HELP_MODES,
    HELP_ROM_BUDGET_CHARS, help_header_lines, wrap_help,
    HELP_TOPIC_NAMES, HELP_TOPICS, HELP_TOPIC_OFFSETS, HELP_TOPIC_SCROLL_MAX,
    HELP_TOPIC_BASE_ROWS, HELP_TOPIC_ROW, HELP_ROW_BITS, pack_help_view)
from top.rezo.display_common import FONT_5X7
from top.rezo.strezo_variant import RezoTileDisplay
from test_strezo_native_display import _render_samples


def rgb(role):
    color = RezoTileDisplay.RGB_PALETTES[0][role]
    return color >> 16, (color >> 8) & 255, color & 255


def lit_points(line, x_cell, y_cell):
    for col, char in enumerate(line):
        for row, bits in enumerate(FONT_5X7.get(char, FONT_5X7[' '])):
            if bits:
                bit = next(bit for bit in range(5) if bits & (1 << (4 - bit)))
                yield (x_cell + col) * 16 + bit * 2, y_cell * 16 + row * 2
                break


def test_help_bounds_and_firmware_scroll_contract():
    assert len(HELP_ROM_LINES) * HELP_COLUMNS <= HELP_ROM_BUDGET_CHARS
    assert all(len(line) == HELP_COLUMNS
               for line in HELP_ROM_LINES[:HELP_BODY_BASE_ROWS])
    assert HELP_ROM_LINES[HELP_BODY_BASE_ROWS:] == HELP_LINES
    assert HELP_ROM_LINES[HELP_HEADER_ROWS:HELP_TOPIC_BASE_ROWS] == tuple(
        help_header_lines(mode)[HELP_STATUS_ROW] for mode in HELP_MODES)
    assert all(len(line) <= HELP_COLUMNS for line in HELP_ROM_LINES)
    assert all(char in RezoTileDisplay.CHAR_CODES and char in FONT_5X7
               for line in HELP_ROM_LINES for char in line)
    assert HELP_SCROLL_MAX == max(HELP_TOPIC_SCROLL_MAX)
    assert HELP_TOPIC_NAMES == ('START', 'BANK', 'INPUT', 'BANDS', 'GROUPS',
                                'FEEDBACK', 'CROSS', 'OUTPUT', 'OPTIONS')
    assert len(HELP_ROM_LINES) <= 1 << HELP_ROW_BITS
    for topic, name in enumerate(HELP_TOPIC_NAMES):
        assert name in HELP_ROM_LINES[HELP_TOPIC_BASE_ROWS + topic]
        assert HELP_TOPIC_SCROLL_MAX[topic] == max(0, len(HELP_TOPICS[topic]) - HELP_VISIBLE_ROWS)
        offset = HELP_TOPIC_OFFSETS[topic]
        assert HELP_LINES[offset:offset + len(HELP_TOPICS[topic])] == HELP_TOPICS[topic]
        assert offset + HELP_TOPIC_SCROLL_MAX[topic] + HELP_VISIBLE_ROWS <= (
            HELP_TOPIC_OFFSETS[topic + 1] if topic + 1 < len(HELP_TOPICS) else len(HELP_LINES))
    firmware = (Path(__file__).parents[1] / 'src/top/rezo/strezo_cpu_fw/src/main.rs').read_text()
    assert 'include!(concat!(env!("OUT_DIR"), "/help_scroll.rs"))' in firmware
    assert 'if flash_available && SHOW_HELP_ON_FIRST_BOOT && !have_active' in firmware
    assert 'if first_help_pending && state.page != 8' in firmware
    assert '|offset, byte| flash_program(0, offset, byte)' in firmware
    formatter = Path(__file__).parents[1] / 'src/top/rezo/help_content.py'
    generated = subprocess.check_output([sys.executable, formatter]).decode()
    assert f'const HELP_TOPIC_COUNT: usize = {len(HELP_TOPIC_NAMES)};' in generated
    assert f'= {list(HELP_TOPIC_OFFSETS)!r};' in generated
    assert f'= {list(HELP_TOPIC_SCROLL_MAX)!r};' in generated
    assert '8 => &[PAGE, PRESET, BAND]' in firmware
    assert 'self.help.packed(&HELP_TOPIC_OFFSETS, HELP_ROW_BITS)' in firmware
    for method in ('click', 'edit', 'continuous_accel_target'):
        section = firmware.split(f'fn {method}(', 1)[1].split('\n    fn ', 1)[0]
        assert 'if self.page == 8' in section
    for x in (HELP_X_CELL * 16, (HELP_X_CELL + HELP_COLUMNS) * 16):
        for y in (HELP_Y_CELL * 16, (HELP_Y_CELL + HELP_VISIBLE_ROWS) * 16):
            assert (x - 360) ** 2 + (y - 360) ** 2 < 360 ** 2
    for mode in ('NAV', 'EDIT', 'SCROLL'):
        for row, line in enumerate(help_header_lines(mode)):
            for x, y in lit_points(line, HELP_X_CELL, row):
                assert (x - 360) ** 2 + (y - 360) ** 2 < 360 ** 2


@pytest.mark.parametrize('punctuation', [':', ',', ';', '/', '-', '—', '?'])
def test_help_rejects_unsupported_punctuation(punctuation):
    with pytest.raises(ValueError, match='unsupported display characters'):
        wrap_help(f'INPUT{punctuation} assign audio.')


def test_help_preserves_supported_sentence_punctuation_and_letters():
    assert wrap_help('Adjust J. Gain is 1.0.\n\nNext page.') == (
        'ADJUST J. GAIN IS 1.0.', '', 'NEXT PAGE.', '')


@pytest.mark.parametrize('rotated', [False, True])
@pytest.mark.parametrize('topic', range(len(HELP_TOPIC_NAMES)))
def test_help_scroll_pixels_and_fixed_family_header(rotated, topic):
    for scroll in (0, HELP_TOPIC_SCROLL_MAX[topic]):
        points = list(lit_points('STREZO', 19, 2))
        points += list(lit_points('PAGE', 8, 8))
        points += list(lit_points('HELP', 16, 8))
        points += list(lit_points('TOPIC', 8, 12))
        points += list(lit_points(HELP_TOPIC_NAMES[topic], 16, 12))
        points += list(lit_points('SCROLL', 32, 12))
        for viewport_row in (0, 1, HELP_VISIBLE_ROWS - 1):
            points += list(lit_points(HELP_LINES[HELP_TOPIC_OFFSETS[topic] + viewport_row + scroll],
                                     HELP_X_CELL, HELP_Y_CELL + viewport_row))
        actual = _render_samples(h_active=720 if rotated else 1280,
            rotate_left=rotated, page=8, help_scroll=pack_help_view(topic, scroll), points=points)
        assert actual == [rgb(1)] * len(points)


@pytest.mark.parametrize('mode,editing,selected', [
    ('NAV', False, 0), ('EDIT', True, 0), ('EDIT', True, 1), ('SCROLL', True, 2)])
def test_help_mode_status_and_matching_cursor(mode, editing, selected):
    points = list(lit_points(mode, 32 if mode == 'SCROLL' else 33, 8))
    points += [(520, 122), (610, 122)]
    assert _render_samples(page=8, editing=editing, selected=selected,
        points=points) == [rgb(1)] * (len(points) - 2) + [rgb(4),
            rgb(4) if mode == 'SCROLL' else (0, 0, 0)]


@pytest.mark.parametrize('selected', [0, 1, 2])
def test_help_controls_use_normal_selection_outlines(selected):
    assert _render_samples(page=8, selected=selected,
        points=((212, 120), (248, 190), (504, 190), (240, 140))) == [
        rgb(0) if selected == 0 else (0, 0, 0),
        rgb(0) if selected == 1 else rgb(5),
        rgb(0) if selected == 2 else (0, 0, 0), rgb(5)]


def test_help_content_panel_fits_text_and_hides_audio_geometry():
    assert _render_samples(page=8, points=((110, 220), (626, 564),
        (300, 86), (300, 600), (0, 0))) == [
        rgb(7), rgb(7), rgb(6), (0, 0, 0), (0, 0, 0)]


def test_help_address_width_follows_a_larger_summary(monkeypatch):
    import top.rezo.strezo_variant as variant

    # First body row beyond a 13-bit character address. Growing the summary
    # must not silently wrap its base address back into the fixed header.
    rows = list(HELP_ROM_LINES)
    scroll = 256 - HELP_BODY_BASE_ROWS
    rows.extend([' ' * HELP_COLUMNS] * max(0, 256 + HELP_VISIBLE_ROWS - len(rows)))
    rows[256] = 'Z'.ljust(HELP_COLUMNS)
    monkeypatch.setattr(variant, 'HELP_ROM_LINES', tuple(rows))
    points = list(lit_points('Z', HELP_X_CELL, HELP_Y_CELL))
    assert _render_samples(page=8, help_scroll=scroll, points=points) == [rgb(1)] * len(points)
