import subprocess
import sys
from pathlib import Path
import pytest
from top.rezo.help_content import (HELP_LINES, HELP_COLUMNS,
    HELP_VISIBLE_ROWS, HELP_SCROLL_MAX, HELP_X_CELL, HELP_Y_CELL)
from top.rezo.display_common import FONT_5X7
from top.rezo.strezo_variant import RezoTileDisplay
from test_strezo_native_display import _render_samples


def rgb(role):
    color = RezoTileDisplay.RGB_PALETTES[0][role]
    return color >> 16, (color >> 8) & 255, color & 255


def test_help_bounds_and_firmware_scroll_contract():
    assert all(len(line) <= HELP_COLUMNS for line in HELP_LINES)
    assert all(not char.isalpha() or char in FONT_5X7
               for line in HELP_LINES for char in line)
    assert HELP_SCROLL_MAX == len(HELP_LINES) - HELP_VISIBLE_ROWS
    firmware = (Path(__file__).parents[1] / 'src/top/rezo/strezo_cpu_fw/src/main.rs').read_text()
    assert 'include!(concat!(env!("OUT_DIR"), "/help_scroll.rs"))' in firmware
    formatter = Path(__file__).parents[1] / 'src/top/rezo/help_content.py'
    assert int(subprocess.check_output([sys.executable, formatter])) == HELP_SCROLL_MAX
    for x in (HELP_X_CELL * 16, (HELP_X_CELL + HELP_COLUMNS) * 16):
        for y in (HELP_Y_CELL * 16, (HELP_Y_CELL + HELP_VISIBLE_ROWS) * 16):
            assert (x - 360) ** 2 + (y - 360) ** 2 < 360 ** 2


@pytest.mark.parametrize('rotated', [False, True])
def test_help_scroll_pixels_and_fixed_heading(rotated):
    points = []
    expected = []
    for scroll in (0, HELP_SCROLL_MAX):
        for viewport_row in (0, 3, HELP_VISIBLE_ROWS - 1):
            source_row = viewport_row + (scroll if viewport_row >= 3 else 0)
            line = HELP_LINES[source_row].ljust(HELP_COLUMNS)
            for col, char in enumerate(line):
                glyph = FONT_5X7.get(char, FONT_5X7[' '])
                for row, bits in enumerate(glyph):
                    for bit in range(5):
                        if bits & (1 << (4 - bit)):
                            points.append((HELP_X_CELL * 16 + col * 16 + bit * 2,
                                           (HELP_Y_CELL + viewport_row) * 16 + row * 2))
                            expected.append(rgb(1))
                            break
                    if bits:
                        break
        actual = _render_samples(h_active=720 if rotated else 1280,
            rotate_left=rotated, page=8, help_scroll=scroll, points=points)
        assert actual == expected
        points.clear()
        expected.clear()


@pytest.mark.parametrize('selected', [0, 1])
def test_help_controls_show_navigation_selection(selected):
    points = []
    for row in (1, 2):
        bits = FONT_5X7[HELP_LINES[row][0]][0]
        bit = next(bit for bit in range(5) if bits & (1 << (4 - bit)))
        points.append((HELP_X_CELL * 16 + bit * 2,
                       (HELP_Y_CELL + row) * 16))
    assert _render_samples(page=8, selected=selected, points=points) == [
        rgb(0 if selected == 0 else 1), rgb(0 if selected == 1 else 1)]


def test_help_has_no_underlying_controls_or_text_outside_viewport():
    assert _render_samples(page=8, points=((300, 86), (212, 120),
        (300, 600), (0, 0))) == [rgb(6), (0, 0, 0), (0, 0, 0), (0, 0, 0)]
