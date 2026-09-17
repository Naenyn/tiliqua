"""Page-based help data shared by all three beam-raced displays."""
import sys
import textwrap
from pathlib import Path
try:
    from .display_common import STEREO_TILE_CHARS, HELP_EXTRA_CHARS
except ImportError:
    from display_common import STEREO_TILE_CHARS, HELP_EXTRA_CHARS

HELP_COLUMNS = 32
HELP_VISIBLE_ROWS = 21
HELP_X_CELL = 7
HELP_Y_CELL = 14
HELP_HEADER_ROWS = 16
HELP_STATUS_ROW = 8
HELP_MODES = ('NAV', 'EDIT', 'SCROLL')
HELP_TOPIC_ROW = 12
HELP_ROW_BITS = 9
HELP_VIEW_BITS = HELP_ROW_BITS + 4
HELP_ROM_BUDGET_CHARS = 16384

TOPIC_NAMES = {
    'REZO': ('START', 'BANK', 'FILTER', 'INPUT', 'BANDS', 'MATRIX',
             'GROUPS', 'FEEDBACK', 'OUTPUT', 'OPTIONS'),
    'REZOMO': ('START', 'BANK', 'INPUT', 'BANDS', 'CLOCK',
               'GROUPS', 'FEEDBACK', 'OUTPUT', 'OPTIONS'),
    'STREZO': ('START', 'BANK', 'INPUT', 'BANDS', 'GROUPS',
               'FEEDBACK', 'CROSS', 'OUTPUT', 'OPTIONS'),
}


def wrap_help(body, *, mixed_case=False):
    """Reject missing glyphs rather than silently displaying them as spaces."""
    text = body if mixed_case else body.upper()
    alphabet = STEREO_TILE_CHARS + (HELP_EXTRA_CHARS if mixed_case else '')
    unsupported = set(text) - set(alphabet) - {'\n'}
    if unsupported:
        raise ValueError(
            f'Help text contains unsupported display characters: {sorted(unsupported)!r}')
    return tuple(
        line for paragraph in text.strip().split('\n\n')
        for line in (*textwrap.wrap(paragraph, HELP_COLUMNS), ''))


class HelpContent:
    """One formatter supplies ROM layout and firmware topic/scroll tables."""
    def __init__(self, product):
        self.product = product
        self.topic_names = TOPIC_NAMES[product]
        source = Path(__file__).with_name(f'{product}_HELP.md').read_text()
        body = source.split('<!-- HELP START -->', 1)[1].split('<!-- HELP END -->', 1)[0]
        sections = body.strip().split('## ')[1:]
        if tuple(section.split('\n', 1)[0] for section in sections) != self.topic_names:
            raise ValueError('Help topics must match the ordered page guides')
        # Trial mixed-case HELP in REZOMO first; retain qualified sibling ROMs.
        self.topics = tuple(wrap_help(section.split('\n', 1)[1],
                           mixed_case=(product == 'REZOMO')) for section in sections)
        self.scroll_max = tuple(max(0, len(lines) - HELP_VISIBLE_ROWS) for lines in self.topics)
        offsets, lines = [], []
        for topic in self.topics:
            offsets.append(len(lines))
            lines.extend(topic)
            lines.extend([''] * max(0, HELP_VISIBLE_ROWS - len(topic)))
        self.offsets = tuple(offsets)
        self.lines = tuple(lines)
        self.topic_base = HELP_HEADER_ROWS + len(HELP_MODES)
        self.body_base = self.topic_base + len(self.topic_names)
        header = self.header_lines('NAV')
        self.rom_lines = (header +
            tuple(self.header_lines(mode)[HELP_STATUS_ROW] for mode in HELP_MODES) +
            tuple(header[HELP_TOPIC_ROW][:9] + name.ljust(8) + header[HELP_TOPIC_ROW][17:]
                  for name in self.topic_names) + self.lines)
        if len(self.rom_lines) * HELP_COLUMNS > HELP_ROM_BUDGET_CHARS:
            raise ValueError('Help summary exceeds its allocated text ROM budget')
        if len(self.rom_lines) > (1 << HELP_ROW_BITS):
            raise ValueError('Help text exceeds its row address range')

    def pack_view(self, topic, scroll):
        if not 0 <= topic < len(self.topic_names):
            raise ValueError('Invalid help topic')
        if not 0 <= scroll <= self.scroll_max[topic]:
            raise ValueError('Invalid help scroll')
        return (topic << HELP_ROW_BITS) | (self.offsets[topic] + scroll)

    def header_lines(self, mode):
        rows = [' ' * HELP_COLUMNS for _ in range(HELP_HEADER_ROWS)]
        def put(text, x, y):
            x -= HELP_X_CELL
            rows[y] = rows[y][:x] + text + rows[y][x + len(text):]
        put(self.product, 19 + (6 - len(self.product)) // 2, 2)
        put('PAGE', 8, 8)
        put('HELP', 16, 8)
        put(mode, 32 if mode == 'SCROLL' else 33, 8)
        put('TOPIC', 8, HELP_TOPIC_ROW)
        put('START', 16, HELP_TOPIC_ROW)
        put('SCROLL', 32, HELP_TOPIC_ROW)
        return tuple(rows)

    def firmware_tables(self):
        rows = [f'const HELP_TOPIC_COUNT: usize = {len(self.topic_names)};',
                f'const HELP_ROW_BITS: u32 = {HELP_ROW_BITS};']
        for name, values in (('HELP_TOPIC_OFFSETS', self.offsets),
                             ('HELP_TOPIC_SCROLL_MAX', self.scroll_max)):
            rows.append(f'const {name}: [u32; HELP_TOPIC_COUNT] = {list(values)!r};')
        return '\n'.join(rows)


def load_help(product):
    return HelpContent(product)


# Preserve the qualified STREZO imports and byte-for-byte ROM layout.
_strezo = load_help('STREZO')
HELP_TOPIC_NAMES = _strezo.topic_names
HELP_TOPICS = _strezo.topics
HELP_TOPIC_SCROLL_MAX = _strezo.scroll_max
HELP_TOPIC_OFFSETS = _strezo.offsets
HELP_LINES = _strezo.lines
HELP_SCROLL_MAX = max(HELP_TOPIC_SCROLL_MAX)
HELP_TOPIC_BASE_ROWS = _strezo.topic_base
HELP_BODY_BASE_ROWS = _strezo.body_base
HELP_ROM_LINES = _strezo.rom_lines
help_header_lines = _strezo.header_lines
pack_help_view = _strezo.pack_view

if __name__ == '__main__':
    print(load_help(sys.argv[1] if len(sys.argv) > 1 else 'STREZO').firmware_tables())
