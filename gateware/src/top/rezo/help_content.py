"""Compact help text for the circular beam-raced display."""
import textwrap
from pathlib import Path
try:
    from .display_common import STEREO_TILE_CHARS
except ImportError:
    from display_common import STEREO_TILE_CHARS

HELP_COLUMNS = 32
HELP_VISIBLE_ROWS = 21
HELP_X_CELL = 7
HELP_Y_CELL = 14
HELP_HEADER_ROWS = 16
HELP_STATUS_ROW = 8
HELP_MODES = ('NAV', 'EDIT', 'SCROLL')
HELP_TOPIC_ROW = 12
HELP_TOPIC_NAMES = ('START', 'BANK', 'INPUT', 'BANDS', 'GROUPS',
                    'FEEDBACK', 'CROSS', 'OUTPUT', 'OPTIONS')
HELP_TOPIC_BASE_ROWS = HELP_HEADER_ROWS + len(HELP_MODES)
HELP_BODY_BASE_ROWS = HELP_TOPIC_BASE_ROWS + len(HELP_TOPIC_NAMES)
HELP_ROW_BITS = 9
HELP_VIEW_BITS = HELP_ROW_BITS + 4
HELP_ROM_BUDGET_CHARS = 16384


def wrap_help(body):
    """Reject missing glyphs rather than silently displaying them as spaces."""
    unsupported = set(body.upper()) - set(STEREO_TILE_CHARS) - {'\n'}
    if unsupported:
        raise ValueError(
            f'Help text contains unsupported display characters: {sorted(unsupported)!r}')
    return tuple(
        line for paragraph in body.strip().split('\n\n')
        for line in (*textwrap.wrap(paragraph.upper(), HELP_COLUMNS), ''))


source = Path(__file__).with_name('STREZO_HELP.md').read_text()
body = source.split('<!-- HELP START -->', 1)[1].split('<!-- HELP END -->', 1)[0]
sections = body.strip().split('## ')[1:]
if tuple(section.split('\n', 1)[0] for section in sections) != HELP_TOPIC_NAMES:
    raise ValueError('Help topics must match the ordered page guides')
HELP_TOPICS = tuple(wrap_help(section.split('\n', 1)[1]) for section in sections)
HELP_TOPIC_SCROLL_MAX = tuple(max(0, len(lines) - HELP_VISIBLE_ROWS)
                              for lines in HELP_TOPICS)
offsets, lines = [], []
for topic in HELP_TOPICS:
    offsets.append(len(lines))
    lines.extend(topic)
    lines.extend([''] * max(0, HELP_VISIBLE_ROWS - len(topic)))
HELP_TOPIC_OFFSETS = tuple(offsets)
HELP_LINES = tuple(lines)
HELP_SCROLL_MAX = max(HELP_TOPIC_SCROLL_MAX)


def pack_help_view(topic, scroll):
    if not 0 <= topic < len(HELP_TOPIC_NAMES):
        raise ValueError('Invalid help topic')
    if not 0 <= scroll <= HELP_TOPIC_SCROLL_MAX[topic]:
        raise ValueError('Invalid help scroll')
    return (topic << HELP_ROW_BITS) | (HELP_TOPIC_OFFSETS[topic] + scroll)


def help_header_lines(mode):
    """Native family header with one mode-dependent status row."""
    rows = [' ' * HELP_COLUMNS for _ in range(HELP_HEADER_ROWS)]

    def put(text, x, y):
        x -= HELP_X_CELL
        rows[y] = rows[y][:x] + text + rows[y][x + len(text):]

    put('STREZO', 19, 2)
    put('PAGE', 8, 8)
    put('HELP', 16, 8)
    put(mode, 32 if mode == 'SCROLL' else 33, 8)
    put('TOPIC', 8, HELP_TOPIC_ROW)
    put('START', 16, HELP_TOPIC_ROW)
    put('SCROLL', 32, HELP_TOPIC_ROW)
    return tuple(rows)


# Share all fixed rows; only the PAGE/status row differs between modes.
# Keeping three entire headers wastes ROM space and address decoding.
HELP_ROM_LINES = (help_header_lines('NAV') +
                  tuple(help_header_lines(mode)[HELP_STATUS_ROW]
                        for mode in HELP_MODES) +
                  tuple(help_header_lines('NAV')[HELP_TOPIC_ROW][:9] +
                        name.ljust(8) + help_header_lines('NAV')[HELP_TOPIC_ROW][17:]
                        for name in HELP_TOPIC_NAMES) + HELP_LINES)

# Keep copy edits within the qualified ROM allocation on the nearly-full FPGA.
if len(HELP_ROM_LINES) * HELP_COLUMNS > HELP_ROM_BUDGET_CHARS:
    raise ValueError('Help summary exceeds its allocated text ROM budget')

if len(HELP_ROM_LINES) > (1 << HELP_ROW_BITS):
    raise ValueError('Help text exceeds its row address range')

if __name__ == '__main__':
    # Cargo uses the same formatter as the display ROM, so editing the
    # Markdown updates both the text and its firmware scroll limit.
    print(f'const HELP_TOPIC_COUNT: usize = {len(HELP_TOPIC_NAMES)};')
    print(f'const HELP_ROW_BITS: u32 = {HELP_ROW_BITS};')
    for name, values in (('HELP_TOPIC_OFFSETS', HELP_TOPIC_OFFSETS),
                         ('HELP_TOPIC_SCROLL_MAX', HELP_TOPIC_SCROLL_MAX)):
        print(f'const {name}: [u32; HELP_TOPIC_COUNT] = {list(values)!r};')
