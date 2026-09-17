"""Shared native HELP ROM and chrome, without a framebuffer or tile writer."""
from amaranth import Mux, Signal, unsigned
from amaranth.lib.memory import Memory
try:
    from .help_content import (
        HELP_COLUMNS, HELP_VISIBLE_ROWS, HELP_X_CELL, HELP_Y_CELL,
        HELP_HEADER_ROWS, HELP_STATUS_ROW, HELP_TOPIC_ROW, HELP_ROW_BITS)
except ImportError:
    from help_content import (
        HELP_COLUMNS, HELP_VISIBLE_ROWS, HELP_X_CELL, HELP_Y_CELL,
        HELP_HEADER_ROWS, HELP_STATUS_ROW, HELP_TOPIC_ROW, HELP_ROW_BITS)


class HelpDisplayLayer:
    def __init__(self, m, display, content, text_y_pre, cell_x, cell_y, normal_char):
        self.display = display
        char_bits = max(6, (len(display.CHARS) - 1).bit_length())
        help_init = [display.code(ch) for line in content.rom_lines
                     for ch in line.ljust(HELP_COLUMNS)]
        m.submodules.help_mem = help_mem = Memory(
            shape=unsigned(char_bits), depth=len(help_init), init=help_init,
            attrs={"ram_style": "block"})
        help_rport = help_mem.read_port(domain="dvi")
        help_row_base_q = Signal.like(help_rport.addr)
        help_row = text_y_pre[display.CELL_SHIFT:]
        self.scrolling = (display.page == 8) & display.editing & (display.selected == 2)
        help_mode = Mux(self.scrolling, 2, Mux(display.editing, 1, 0))
        m.d.dvi += help_row_base_q.eq(
            Mux(help_row < HELP_Y_CELL,
                Mux(help_row == HELP_STATUS_ROW,
                    (HELP_HEADER_ROWS + help_mode) << 5,
                    Mux(help_row == HELP_TOPIC_ROW,
                        (content.topic_base + display.help_scroll[HELP_ROW_BITS:]) << 5,
                        help_row << 5)),
                (content.body_base + help_row - HELP_Y_CELL +
                 display.help_scroll[:HELP_ROW_BITS]) << 5) - HELP_X_CELL)
        m.d.comb += help_rport.addr.eq(help_row_base_q + cell_x)
        help_visible_q = Signal()
        help_page_q = Signal()
        m.d.dvi += [
            help_page_q.eq(display.page == 8),
            help_visible_q.eq((display.page == 8) &
                (cell_x >= HELP_X_CELL) & (cell_x < HELP_X_CELL + HELP_COLUMNS) &
                (cell_y >= 2) & (cell_y < HELP_Y_CELL + HELP_VISIBLE_ROWS)),
        ]
        self.char = Signal(unsigned(char_bits), name="rendered_char")
        m.d.comb += self.char.eq(Mux(help_page_q,
            Mux(help_visible_q, help_rport.data, 0), normal_char))

    def cursor(self, active, text_x, text_y):
        d = self.display
        return active & d.outline(text_x, text_y,
            Mux(self.scrolling, 504, 520), 122,
            Mux(self.scrolling, 616, Mux(d.editing, 600, 584)), 148, t=2)

    def palette(self, m, active, x, y, text_x, text_y, page_selected_q,
                page_chip, cursor_chip, text_q, background_q, normal_role, normal_visible):
        d = self.display
        help_selected_q0, help_selected_q = Signal(), Signal()
        help_line_q0, help_line_q = Signal(), Signal()
        help_panel_q0, help_panel_q = Signal(), Signal()
        help_surface_q, help_active_q = Signal(), Signal()
        m.d.dvi += [
            help_selected_q0.eq((d.selected == 1) &
                d.outline(text_x, text_y, 248, 184, 400, 212, t=3) |
                (d.selected == 2) & d.outline(text_x, text_y, 504, 184, 616, 212, t=3)),
            help_selected_q.eq(page_selected_q | help_selected_q0),
            help_line_q0.eq(cursor_chip), help_line_q.eq(help_line_q0),
            help_panel_q0.eq(page_chip | d.rect(text_x, text_y, 248, 184, 400, 212)),
            help_panel_q.eq(help_panel_q0),
            help_surface_q.eq(active & d.rect(x, y, 108, 218, 628, 566)),
            help_active_q.eq(active),
        ]
        role = Signal(unsigned(3), name="help_palette_role")
        m.d.comb += role.eq(normal_role)
        with m.If(d.page == 8):
            m.d.comb += role.eq(6)
            with m.If(help_selected_q):
                m.d.comb += role.eq(0)
            with m.Elif(text_q):
                m.d.comb += role.eq(1)
            with m.Elif(help_line_q):
                m.d.comb += role.eq(4)
            with m.Elif(help_panel_q):
                m.d.comb += role.eq(5)
            with m.Elif(help_surface_q):
                m.d.comb += role.eq(7)
        visible = Mux(d.page == 8, help_active_q &
            (text_q | background_q | help_surface_q | help_selected_q |
             help_line_q | help_panel_q), normal_visible)
        return role, visible
