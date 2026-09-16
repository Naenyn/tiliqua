"""Compact help text for the circular beam-raced display."""
import textwrap
from pathlib import Path

HELP_COLUMNS = 32
HELP_VISIBLE_ROWS = 21
HELP_X_CELL = 7
HELP_Y_CELL = 14
HELP_HEADER_ROWS = 16
HELP_BODY_BASE_ROWS = 3 * HELP_HEADER_ROWS
source = Path(__file__).with_name('STREZO_HELP.md').read_text()
body = source.split('<!-- HELP START -->', 1)[1].split('<!-- HELP END -->', 1)[0]
HELP_LINES = tuple(
    line for paragraph in body.strip().split('\n\n')
    for line in (*textwrap.wrap(paragraph.upper(), HELP_COLUMNS), ''))
HELP_SCROLL_MAX = max(0, len(HELP_LINES) - HELP_VISIBLE_ROWS)


def help_header_lines(mode):
    """Native family header; each mode gets a shift-addressable ROM bank."""
    rows = [' ' * HELP_COLUMNS for _ in range(HELP_HEADER_ROWS)]

    def put(text, x, y):
        x -= HELP_X_CELL
        rows[y] = rows[y][:x] + text + rows[y][x + len(text):]

    put('STREZO', 19, 2)
    put('PAGE', 8, 8)
    put('HELP', 16, 8)
    put(mode, 32 if mode == 'SCROLL' else 33, 8)
    put('SCROLL   CLICK THEN TURN', 8, 12)
    return tuple(rows)


HELP_ROM_LINES = tuple(line for mode in ('NAV', 'EDIT', 'SCROLL')
                       for line in help_header_lines(mode)) + HELP_LINES

if HELP_SCROLL_MAX > 127:
    raise ValueError('Help summary exceeds the seven-bit scroll range')

if __name__ == '__main__':
    # Cargo uses the same formatter as the display ROM, so editing the
    # Markdown updates both the text and its firmware scroll limit.
    print(HELP_SCROLL_MAX)
