"""Compact help text for the circular beam-raced display."""
import textwrap
from pathlib import Path

HELP_COLUMNS = 32
HELP_VISIBLE_ROWS = 24
HELP_X_CELL = 7
HELP_Y_CELL = 11
source = Path(__file__).with_name('STREZO_HELP.md').read_text()
body = source.split('<!-- HELP START -->', 1)[1].split('<!-- HELP END -->', 1)[0]
HELP_LINES = ('STREZO HELP', 'PAGE: CLICK TO CHANGE VIEW',
              'SCROLL: CLICK THEN TURN') + tuple(
    line for paragraph in body.strip().split('\n\n')
    for line in (*textwrap.wrap(paragraph.upper(), HELP_COLUMNS), ''))
HELP_SCROLL_MAX = max(0, len(HELP_LINES) - HELP_VISIBLE_ROWS)

if HELP_SCROLL_MAX > 127:
    raise ValueError('Help summary exceeds the seven-bit scroll range')

if __name__ == '__main__':
    # Cargo uses the same formatter as the display ROM, so editing the
    # Markdown updates both the text and its firmware scroll limit.
    print(HELP_SCROLL_MAX)
