"""Topic isolation, native pixels and ABI coverage for the two HELP ports."""
import subprocess
import sys
import importlib
from pathlib import Path
import pytest
from amaranth import Module
from amaranth.sim import Simulator
from amaranth_soc import csr
from amaranth_soc.csr import wishbone
from tiliqua.test import csr as csr_util
from rezo_display_support import sample_native_rgb
from test_strezo_help import lit_points
from top.rezo.help_content import (
    load_help, HELP_COLUMNS, HELP_VISIBLE_ROWS, HELP_Y_CELL, HELP_X_CELL,
    HELP_ROW_BITS, HELP_ROM_BUDGET_CHARS)
from top.rezo.display_common import FONT_5X7, TILE_CHARS, STEREO_TILE_CHARS, HELP_EXTRA_CHARS
from top.rezo.help_content import wrap_help
from top.rezo.rezo_variant import RezoTileDisplay as RezoDisplay
from top.rezo.top import RezoTileDisplay as RezomoDisplay
from top.rezo.strezo_variant import RezoTileDisplay as StrezoDisplay
from top.rezo.cpu_control import (
    RezoFirmwareUIState, RezoUIControlPeripheral,
    RezomoFirmwareUIState, RezomoUIControlPeripheral)
from top.rezo.cpu_control import RezoProgramMemory

PRODUCTS = [('REZO', RezoDisplay), ('REZOMO', RezomoDisplay)]


def test_family_mixed_case_font_preserves_native_glyph_codes():
    assert RezomoDisplay.CHARS == TILE_CHARS + '.' + HELP_EXTRA_CHARS
    assert RezoDisplay.CHARS == TILE_CHARS + '.' + HELP_EXTRA_CHARS
    assert StrezoDisplay.CHARS == STEREO_TILE_CHARS + '|' + HELP_EXTRA_CHARS
    for display, native in ((RezoDisplay, TILE_CHARS + '.'),
                            (RezomoDisplay, TILE_CHARS + '.'),
                            (StrezoDisplay, STEREO_TILE_CHARS + '|')):
        assert len(set(display.CHARS)) == len(display.CHARS)
        assert 64 < len(display.CHARS) <= 128
        for code, char in enumerate(native):
            assert display.code(char) == code
        for char in HELP_EXTRA_CHARS:
            assert display.code(char) != 0
            assert len(FONT_5X7[char]) == 7
            assert all(0 <= row < 32 for row in FONT_5X7[char])
            assert any(FONT_5X7[char])
    assert wrap_help("On INPUT, adjust gain (1.0x).", mixed_case=True) == (
        'On INPUT, adjust gain (1.0x).', '')
    for char in ('—', '’', '“', '=', '_'):
        with pytest.raises(ValueError, match='unsupported display characters'):
            wrap_help('Invalid' + char, mixed_case=True)
    for product in ('REZO', 'REZOMO', 'STREZO'):
        assert any(any(char.islower() for char in line)
                   for line in load_help(product).lines)


@pytest.mark.parametrize('rotated', [False, True])
@pytest.mark.parametrize('product,display,module_name', [
    ('REZO', RezoDisplay, 'rezo_variant'),
    ('REZOMO', RezomoDisplay, 'top'),
    ('STREZO', StrezoDisplay, 'strezo_variant')])
def test_family_all_new_glyph_pixels_include_seven_bit_codes(
        monkeypatch, rotated, product, display, module_name):
    module = importlib.import_module('top.rezo.' + module_name)
    content = load_help(product)
    lines = [HELP_EXTRA_CHARS[start:start + HELP_COLUMNS]
             for start in range(0, len(HELP_EXTRA_CHARS), HELP_COLUMNS)]
    content.rom_lines = (content.rom_lines[:content.body_base] + tuple(lines) +
                         content.rom_lines[content.body_base + len(lines):])
    if product == 'STREZO':
        monkeypatch.setattr(module, 'HELP_ROM_LINES', content.rom_lines)
    else:
        monkeypatch.setattr(module, 'HELP_CONTENT', content)
    points, expected = [], []
    for line_index, line in enumerate(lines):
        for col, char in enumerate(line):
            for row, bits in enumerate((*FONT_5X7[char], 0)):
                for bit in range(5):
                    points.append(((HELP_X_CELL + col) * 16 + bit * 2,
                                   (HELP_Y_CELL + line_index) * 16 + row * 2))
                    expected.append(rgb(display, 1 if bits & (1 << (4 - bit)) else 7))
    assert render(display, points=points, rotated=rotated) == expected


@pytest.mark.parametrize('product', ['REZO', 'REZOMO', 'STREZO'])
def test_help_control_names_match_native_page_labels(product):
    source = Path(__file__).parents[1] / 'src/top/rezo'
    text = source.joinpath(product + '_HELP.md').read_text()
    bands = text.split('## BANDS\n')[1].split('\n## ')[0]
    feedback = text.split('## FEEDBACK\n')[1].split('\n## ')[0]
    native = source.joinpath('ui_common.py').read_text()
    assert 'put_native_page_heading(put, 6, "PRESET")' in native
    assert 'PRESET chooses LEGACY' in bands
    assert 'LAYOUT' not in bands
    assert '"CEILING"' in native
    assert 'CEILING sets' in feedback
    assert ' CEIL.' not in feedback and ' CEIL ' not in feedback
    assert 'AMOUNT' not in feedback


def test_shared_program_rom_reads_above_sixteen_kib_on_both_ports():
    init = [0x12345678] + [0] * 4095 + [0xCAFEBABE]
    dut = RezoProgramMemory(size=0x5000, init=init)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    async def bench(ctx):
        for bus in (dut.ibus, dut.dbus):
            ctx.set(bus.cyc, 1)
            ctx.set(bus.stb, 1)
        ctx.set(dut.ibus.adr, 4096)
        ctx.set(dut.dbus.adr, 0)
        for _ in range(2):
            await ctx.tick()
        assert ctx.get(dut.ibus.dat_r) == 0xCAFEBABE
        assert ctx.get(dut.dbus.dat_r) == 0x12345678
        ctx.set(dut.ibus.adr, 0)
        ctx.set(dut.dbus.adr, 4096)
        for _ in range(2):
            await ctx.tick()
        assert ctx.get(dut.ibus.dat_r) == 0x12345678
        assert ctx.get(dut.dbus.dat_r) == 0xCAFEBABE
    sim.add_testbench(bench)
    sim.run()


def render(display, *, points, view=0, rotated=False, editing=False, selected=0):
    dut = display(h_active=720 if rotated else 1280, rotate_left=rotated)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain='sync')
    sim.add_clock(1e-6, domain='dvi')
    samples = []
    async def bench(ctx):
        ctx.set(dut.page, 8)
        ctx.set(dut.help_scroll, view)
        ctx.set(dut.editing, editing)
        ctx.set(dut.selected, selected)
        ctx.set(dut.de, 1)
        for _ in range(30):
            await ctx.tick('dvi')
        samples.extend(await sample_native_rgb(ctx, dut, points, rotate_left=rotated))
    sim.add_testbench(bench)
    sim.run()
    return samples


def rgb(display, role):
    c = display.RGB_PALETTES[0][role]
    return c >> 16, (c >> 8) & 255, c & 255


@pytest.mark.parametrize('product,display', PRODUCTS)
def test_help_rom_and_firmware_contract(product, display):
    content = load_help(product)
    assert len(content.rom_lines) * HELP_COLUMNS <= HELP_ROM_BUDGET_CHARS
    assert len(content.rom_lines) <= 1 << HELP_ROW_BITS
    assert content.rom_lines[content.body_base:] == content.lines
    assert display.CHARS[:len(TILE_CHARS)] == TILE_CHARS
    assert all(ch in display.CHAR_CODES and ch in FONT_5X7
               for line in content.rom_lines for ch in line)
    for topic, name in enumerate(content.topic_names):
        offset = content.offsets[topic]
        end = offset + content.scroll_max[topic] + HELP_VISIBLE_ROWS
        assert end <= (content.offsets[topic + 1]
                       if topic + 1 < len(content.topics) else len(content.lines))
        assert name in content.rom_lines[content.topic_base + topic]
        packed = content.pack_view(topic, content.scroll_max[topic])
        assert packed >> HELP_ROW_BITS == topic
        assert packed & ((1 << HELP_ROW_BITS) - 1) == end - HELP_VISIBLE_ROWS
    formatter = Path(__file__).parents[1] / 'src/top/rezo/help_content.py'
    generated = subprocess.check_output([sys.executable, formatter, product]).decode().strip()
    assert generated == content.firmware_tables()
    fw = 'cpu_fw' if product == 'REZO' else 'rezomo_cpu_fw'
    firmware = formatter.with_name(fw).joinpath('src/main.rs').read_text()
    assert '8 => &[PAGE, PRESET, BAND]' in firmware
    assert 'SHOW_HELP_ON_FIRST_BOOT && !have_active' in firmware
    assert 'first_help_pending && state.page != 8' in firmware
    for method in ('click', 'edit', 'continuous_accel_target', 'write_edit_target', 'write_click_result'):
        body = firmware.split(f'fn {method}(', 1)[1].split('\n    ', 1)[1]
        assert 'self.page == 8' in body[:200]
    for method in ('pack_words', 'load_words'):
        body = firmware.split(f'fn {method}(', 1)[1].split('\n    fn ', 1)[0].split('\n    unsafe fn ', 1)[0]
        assert 'self.help' not in body
    with pytest.raises(ValueError):
        content.pack_view(len(content.topics), 0)
    with pytest.raises(ValueError):
        content.pack_view(0, content.scroll_max[0] + 1)


@pytest.mark.parametrize('product,display', PRODUCTS)
@pytest.mark.parametrize('rotated', [False, True])
def test_every_help_topic_first_and_last_window(product, display, rotated):
    content = load_help(product)
    for topic, name in enumerate(content.topic_names):
        for scroll in (0, content.scroll_max[topic]):
            points = list(lit_points(product, 19 + (6 - len(product)) // 2, 2))
            points += list(lit_points('TOPIC', 8, 12))
            points += list(lit_points(name, 16, 12))
            points += list(lit_points('SCROLL', 32, 12))
            for row in (0, 1, HELP_VISIBLE_ROWS - 1):
                points += list(lit_points(content.lines[content.offsets[topic] + scroll + row],
                                         HELP_X_CELL, HELP_Y_CELL + row))
            assert render(display, view=content.pack_view(topic, scroll),
                rotated=rotated, points=points) == [rgb(display, 1)] * len(points)


@pytest.mark.parametrize('product,display', PRODUCTS)
@pytest.mark.parametrize('selected', [0, 1, 2])
def test_help_header_selection_and_mode(product, display, selected):
    mode = 'SCROLL' if selected == 2 else 'EDIT'
    points = list(lit_points(mode, 32 if selected == 2 else 33, 8))
    assert render(display, selected=selected, editing=True, points=points) == [rgb(display, 1)] * len(points)
    assert render(display, selected=selected,
        points=((212, 120), (248, 190), (504, 190), (110, 220), (300, 600))) == [
        rgb(display, 0) if selected == 0 else (0, 0, 0),
        rgb(display, 0) if selected == 1 else rgb(display, 5),
        rgb(display, 0) if selected == 2 else (0, 0, 0),
        rgb(display, 7), (0, 0, 0)]


@pytest.mark.parametrize('state,peripheral,kind_bits', [
    (RezoFirmwareUIState, RezoUIControlPeripheral, 5),
    (RezomoFirmwareUIState, RezomoUIControlPeripheral, 6)])
def test_help_uses_an_isolated_command_subindex(state, peripheral, kind_bits):
    ui = state()
    dut = peripheral(ui)
    m = Module()
    decoder = csr.Decoder(addr_width=28, data_width=8)
    decoder.add(dut.bus, addr=0, name='dut')
    bridge = wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
    m.submodules += [dut, decoder, bridge]
    async def bench(ctx):
        async def command(kind, index, value):
            packed = kind | (index << kind_bits) | ((value & 0xffff) << (kind_bits + 5))
            await csr_util.wb_csr_w(ctx, dut.bus, bridge.wb_bus, packed, 'command')
        await command(10, 0, 8)
        await command(30, 0, 11)
        await command(30, 1, 0)
        await command(30, 2, (9 << 9) | 400)
        assert ctx.get(ui.page) == 8
        assert ctx.get(ui.help_scroll) == (9 << 9) | 400
        assert ctx.get(ui.row_dry_include) == 0
        assert ctx.get(ui.save_default_available) == 1
        assert ctx.get(ui.save_default_busy) == 1
        assert ctx.get(ui.save_default_status) == 2
        await command(30, 1, 1)
        assert ctx.get(ui.help_scroll) == (9 << 9) | 400
    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
