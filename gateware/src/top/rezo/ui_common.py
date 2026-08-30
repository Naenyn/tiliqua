# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Shared REZO-family page geometry and small rendering expressions."""

from math import isqrt, log10

from amaranth import Mux, Signal, unsigned
from amaranth.lib.memory import Memory


COMMON_PAGE_TITLES = (
    "BANK", "FEEDBACK", "INPUT", "GROUPS", "OUTPUT", "OPTIONS", "BANDS",
)
NAV_NAMES = ("NAV ", "EDIT")
BASE_TARGET_NAMES = ("FB ", "RES", "DRV", "G1 ", "G2 ", "G3 ", "G4 ")
LAYOUT_NAMES = ("LEGACY ", "OCTAVE ", "PERCEPT", "USER   ")
PALETTE_NAMES = (
    "LCD   ", "AMBER ", "CYAN  ", "GREEN ",
    "VIOLET", "EMBER ", "NEON  ", "AZURE ",
)
DAMP_NAMES = ("OFF  ", "LIGHT", "MED  ", "HEAVY", "MAX  ")
SAVE_NAMES = ("SAVE   ", "SAVING ", "SAVED  ", "ERROR  ", "NO SLOT")
ROW_DRY_NAMES = ("EXCLUDE", "INCLUDE")


def format_frequency_name(frequency):
    """Format the common compact three-character band-frequency label."""
    if frequency < 1000:
        return f"{frequency:<3}"[:3]
    if frequency < 10_000:
        whole, remainder = divmod(frequency, 1000)
        tenth = (remainder + 50) // 100
        return f"{whole}K{tenth}" if tenth else f"{whole}K "
    return f"{round(frequency / 1000):02d}K"


NATIVE_CONTENT_PANEL_X0 = 125
NATIVE_CONTENT_PANEL_Y0 = 218
NATIVE_CONTENT_PANEL_X1 = 594
NATIVE_CONTENT_PANEL_Y1 = 599
# Every native page's descriptive heading occupies this final text row above
# the common content panel. A 16px cell on row 12 draws through y=205, leaving
# a consistent 12px gutter before the panel begins at y=218.
NATIVE_PAGE_HEADING_ROW = 12
# Interactive values sharing the heading band use one vertical chip geometry.
NATIVE_PAGE_HEADER_CHIP_Y0 = 184
NATIVE_PAGE_HEADER_CHIP_Y1 = 216
NATIVE_PAGE_HEADER_SELECT_Y0 = 180
NATIVE_PAGE_HEADER_SELECT_Y1 = 218
NATIVE_VALUE_CHIP_TEXT_INSET = 16
# Backwards-compatible aliases for the INPUT renderer. INPUT is the canonical
# family content panel; every other native page now uses the same bounds.
NATIVE_INPUT_PANEL_Y0 = NATIVE_CONTENT_PANEL_Y0
NATIVE_INPUT_PANEL_Y1 = NATIVE_CONTENT_PANEL_Y1
NATIVE_INPUT_CONTROL_X0 = 304
NATIVE_INPUT_CONTROL_X1 = 576
NATIVE_INPUT_CONTROL_MID = 440
NATIVE_FADER_INSET = 2
NATIVE_INPUT_FILL_X0 = NATIVE_INPUT_CONTROL_X0 + NATIVE_FADER_INSET
NATIVE_INPUT_FILL_X1 = NATIVE_INPUT_CONTROL_X1 - NATIVE_FADER_INSET

NATIVE_MAIN_TRACK_X0 = 283
NATIVE_MAIN_TRACK_X1 = 594
NATIVE_MAIN_FILL_X0 = NATIVE_MAIN_TRACK_X0 + NATIVE_FADER_INSET
NATIVE_MAIN_FILL_X1 = NATIVE_MAIN_TRACK_X1 - NATIVE_FADER_INSET
NATIVE_FEEDBACK_TRACK_X0 = 268
NATIVE_FEEDBACK_TRACK_X1 = 579
NATIVE_FEEDBACK_FILL_X0 = NATIVE_FEEDBACK_TRACK_X0 + NATIVE_FADER_INSET
NATIVE_FEEDBACK_FILL_X1 = NATIVE_FEEDBACK_TRACK_X1 - NATIVE_FADER_INSET

NATIVE_INPUT_TEXT_ROWS = (
    (14, 16, 18), (20, 22, 24),
    (26, 28, 30), (32, 34, 36))
NATIVE_GROUP_TEXT_ROWS = (20, 23, 26, 29)
NATIVE_GROUP_CENTERS = tuple(row * 16 + 6
                             for row in NATIVE_GROUP_TEXT_ROWS)
NATIVE_OUTPUT_TEXT_ROWS = (21, 25, 29, 33)
NATIVE_OUTPUT_ROW_CENTERS = tuple(row * 16 + 6
                                  for row in NATIVE_OUTPUT_TEXT_ROWS)
NATIVE_OUTPUT_COL_CENTERS = (
    16 * 16 + 14, 20 * 16 + 14, 24 * 16 + 14,
    28 * 16 + 14, 32 * 16 + 22)
NATIVE_INPUT_BUS_TRACK_X0 = 183
NATIVE_INPUT_BUS_TRACK_X1 = 537
NATIVE_INPUT_BUS_FILL_X0 = 187
NATIVE_INPUT_BUS_FILL_X1 = 533
INPUT_BUS_FULL_SCALE_VOLTS = 8.192
INPUT_BUS_NOMINAL_VOLTS = 5.0


def input_bus_meter_db_value(magnitude):
    """Map the common mono input bus onto -48..0 dBFS."""
    if magnitude == 0:
        return 0
    dbfs = 20 * log10(magnitude / 1023)
    return max(0, min(63, round((dbfs + 48) * 63 / 48)))


INPUT_BUS_NOMINAL_MAGNITUDE = round(
    1023 * INPUT_BUS_NOMINAL_VOLTS / INPUT_BUS_FULL_SCALE_VOLTS)
INPUT_BUS_NOMINAL_METER_VALUE = input_bus_meter_db_value(
    INPUT_BUS_NOMINAL_MAGNITUDE)


def native_input_bus_meter_endpoint(value):
    """Map the calibrated 0..63 input-bus meter across the bottom arc."""
    return (NATIVE_INPUT_BUS_FILL_X0 + (value << 2) + value +
            (value >> 1))
NATIVE_MAIN_CONTROL_TEXT_ROWS = (28, 30, 32, 34, 36)
NATIVE_MAIN_CONTROL_Y0S = (448, 480, 512, 544, 576)

NATIVE_FEEDBACK_LABEL_RIGHT = 16
NATIVE_FEEDBACK_AMOUNT_ROW = 21
NATIVE_FEEDBACK_SAFETY_TITLE_ROW = 24
NATIVE_FEEDBACK_KNEE_ROW = 26
NATIVE_FEEDBACK_CEILING_ROW = 28
NATIVE_FEEDBACK_DAMPING_ROW = 30
NATIVE_FEEDBACK_AMOUNT_Y0 = NATIVE_FEEDBACK_AMOUNT_ROW * 16
NATIVE_FEEDBACK_KNEE_Y0 = NATIVE_FEEDBACK_KNEE_ROW * 16
NATIVE_FEEDBACK_CEILING_Y0 = NATIVE_FEEDBACK_CEILING_ROW * 16
NATIVE_FEEDBACK_DAMPING_CHIP_X0 = 272
NATIVE_FEEDBACK_DAMPING_CHIP_X1 = 376
NATIVE_FEEDBACK_DAMPING_CHIP_Y0 = NATIVE_FEEDBACK_DAMPING_ROW * 16 - 8
NATIVE_FEEDBACK_DAMPING_CHIP_Y1 = NATIVE_FEEDBACK_DAMPING_ROW * 16 + 24
NATIVE_FEEDBACK_DAMPING_TEXT_COL = 18
NATIVE_FEEDBACK_DAMPING_TEXT_ROW = NATIVE_FEEDBACK_DAMPING_ROW


def native_input_row_geometry(height, *, first_y=221):
    """Encode the four common 96px INPUT lanes for one y-coordinate ROM.

    Bits 0..6 are local y, bits 7..8 are the input index, and bit 9 marks a
    valid lane.  Keeping this table here prevents the three renderers from
    independently changing cadence, bit layout, or panel bounds.
    """
    init = []
    for pixel_y in range(height):
        if first_y <= pixel_y < first_y + 4 * 96:
            offset = pixel_y - first_y
            init.append((offset % 96) | ((offset // 96) << 7) | (1 << 9))
        else:
            init.append(0)
    return init


def native_clock_row_geometry(height):
    """Encode REZOMO's nine compact CLOCK value rows in one y ROM.

    Bits 0..3 select the row, bit 4 marks the 28-pixel selection band,
    bit 5 marks its three-pixel top/bottom outline edge, and bit 6 marks the
    inset 22-pixel chip fill. The rows share an exact 32-pixel cadence.
    """
    init = []
    for pixel_y in range(height):
        encoded = 0
        for row in range(9):
            select_y0 = 249 + row * 32
            select_y1 = select_y0 + 28
            if select_y0 <= pixel_y < select_y1:
                encoded = row | (1 << 4)
                if (pixel_y < select_y0 + 3 or
                        pixel_y >= select_y1 - 3):
                    encoded |= 1 << 5
                else:
                    encoded |= 1 << 6
                break
        init.append(encoded)
    return init


def native_group_geometry(width, *, content_shift=16, x_prefetch=1):
    """Encode the common 10x4 GROUPS marker geometry.

    Bits 0..3 select a band, bit 4 marks an active x column, bits 5..6
    select a group, bit 7 marks an active y row, and bit 8 marks the row's
    two-pixel ghost rail.
    """
    centers = tuple(center - content_shift for center in NATIVE_GROUP_CENTERS)
    init = []
    for coordinate in range(width):
        encoded = 0
        pixel_x = coordinate + x_prefetch
        for band in range(10):
            x0 = 208 + band * 34
            marker_width = 18
            if x0 <= pixel_x < x0 + marker_width:
                encoded |= band | (1 << 4)
                break
        for group, center in enumerate(centers):
            y0 = center - 9
            marker_height = 20
            if y0 <= coordinate < y0 + marker_height:
                encoded |= (group << 5) | (1 << 7)
                if (coordinate < y0 + 2 or
                        coordinate >= y0 + marker_height - 2):
                    encoded |= 1 << 8
                break
        init.append(encoded)
    return init


def native_output_column_geometry(width, *, x_prefetch=1):
    """Encode the common five-column OUTPUT routing geometry.

    Bits 0..2 select the source, bit 3 marks the two-pixel edge, and bit 4
    marks an active cell column.
    """
    init = []
    for address in range(width):
        pixel_x = address + x_prefetch
        encoded = 0
        for source, center in enumerate(NATIVE_OUTPUT_COL_CENTERS):
            x0 = center - 27
            cell_width = 56
            if x0 <= pixel_x < x0 + cell_width:
                encoded = source | (1 << 4)
                if (pixel_x < x0 + 2 or
                        pixel_x >= x0 + cell_width - 2):
                    encoded |= 1 << 3
                break
        init.append(encoded)
    return init


def native_value_chip_x0(text_col):
    """Return the chip edge one standard inset left of a text-RAM column."""
    return text_col * 16 - NATIVE_VALUE_CHIP_TEXT_INSET


def native_viewport_circle_outline(m, x, lookup_y, *, pipeline_bounds=False):
    """Return a thin guide for the edge of the native 720px round panel.

    Native pixels are centred between coordinates 359 and 360, so doubled
    absolute coordinates keep the ring exactly symmetric without fractional
    arithmetic. A synchronous row lookup is prefetched alongside the existing
    coordinate pipeline; this avoids putting two live squares on the DVI path.
    A two-pixel inward ring keeps the nominal 360px-radius edge visible at all
    four active-video boundaries.
    """
    inner_squared = 716 * 716
    outer_squared = 720 * 720
    bounds_init = []
    for pixel_y in range(720):
        dy2 = abs((pixel_y << 1) - 719)
        inner_remainder = max(0, inner_squared - dy2 * dy2)
        outer_remainder = outer_squared - dy2 * dy2
        min_dx2 = isqrt(inner_remainder)
        if min_dx2 * min_dx2 < inner_remainder:
            min_dx2 += 1
        max_dx2 = isqrt(outer_remainder)
        bounds_init.append(min_dx2 | (max_dx2 << 10))

    m.submodules.native_viewport_circle_mem = circle_mem = Memory(
        shape=unsigned(20), depth=720, init=bounds_init,
        attrs={"ram_style": "block"})
    circle_rport = circle_mem.read_port(domain="dvi")
    m.d.comb += circle_rport.addr.eq(lookup_y)

    circle_bounds = circle_rport.data
    circle_x = x
    if pipeline_bounds:
        circle_bounds_q = Signal.like(circle_rport.data)
        circle_x_q = Signal.like(x)
        m.d.dvi += [
            circle_bounds_q.eq(circle_rport.data),
            circle_x_q.eq(x),
        ]
        circle_bounds = circle_bounds_q
        circle_x = circle_x_q

    dx2 = Mux(circle_x < 360,
              719 - (circle_x << 1),
              (circle_x << 1) - 719)
    return ((dx2 >= circle_bounds[:10]) &
            (dx2 <= circle_bounds[10:20]))


def native_viewport_regions(m, x, lookup_y, *, inner_radius=250):
    """Return the circular panel interior and an outer annular band.

    The fixed row lookup gives circular chrome a genuinely curved inner and
    outer edge without putting a square-root or multiplier on the pixel path.
    Coordinates are doubled for exact symmetry around the half-pixel centre.
    """
    outer_radius2 = 716
    inner_radius2 = inner_radius * 2
    bounds_init = []
    for pixel_y in range(720):
        dy2 = abs((pixel_y << 1) - 719)
        outer_remainder = max(0, outer_radius2 * outer_radius2 - dy2 * dy2)
        inner_remainder = inner_radius2 * inner_radius2 - dy2 * dy2
        outer_dx2 = isqrt(outer_remainder)
        inner_dx2 = isqrt(inner_remainder) if inner_remainder > 0 else 0
        if inner_dx2 * inner_dx2 < max(0, inner_remainder):
            inner_dx2 += 1
        bounds_init.append(inner_dx2 | (outer_dx2 << 10))

    m.submodules.native_viewport_annulus_mem = annulus_mem = Memory(
        shape=unsigned(20), depth=720, init=bounds_init,
        attrs={"ram_style": "block"})
    annulus_rport = annulus_mem.read_port(domain="dvi")
    m.d.comb += annulus_rport.addr.eq(lookup_y)

    dx2 = Mux(x < 360, 719 - (x << 1), (x << 1) - 719)
    circle_inside = dx2 <= annulus_rport.data[10:20]
    annulus = (dx2 >= annulus_rport.data[:10]) & circle_inside
    return circle_inside, annulus


def native_feedback_track_rows(
        rect, x, y, x0, x1, *, y_shift=0, amount_y_shift=0):
    """Return the three shared FEEDBACK-page shaded control tracks."""
    return (
        rect(x, y, x0,
             NATIVE_FEEDBACK_AMOUNT_Y0 + y_shift + amount_y_shift - 2,
             x1, NATIVE_FEEDBACK_AMOUNT_Y0 + y_shift + amount_y_shift + 18) |
        rect(x, y, x0, NATIVE_FEEDBACK_KNEE_Y0 + y_shift - 2,
             x1, NATIVE_FEEDBACK_KNEE_Y0 + y_shift + 18) |
        rect(x, y, x0, NATIVE_FEEDBACK_CEILING_Y0 + y_shift - 2,
             x1, NATIVE_FEEDBACK_CEILING_Y0 + y_shift + 18))


def put_native_feedback_labels(
        put, *, content_row_offset=0, amount_row_offset=0):
    """Place the labels shared by every native REZO FEEDBACK page."""
    put_native_page_heading(put, 1, "FEEDBACK SOURCES")
    put(1, "BANDS", 8, 16 + content_row_offset)
    put(1, "FREQ:", 23, 16 + content_row_offset)
    put(1, "FEEDBACK", NATIVE_FEEDBACK_LABEL_RIGHT - len("FEEDBACK"),
        NATIVE_FEEDBACK_AMOUNT_ROW + content_row_offset + amount_row_offset)
    put(1, "FEEDBACK SAFETY", 8,
        NATIVE_FEEDBACK_SAFETY_TITLE_ROW + content_row_offset)
    put(1, "KNEE", NATIVE_FEEDBACK_LABEL_RIGHT - len("KNEE"),
        NATIVE_FEEDBACK_KNEE_ROW + content_row_offset)
    put(1, "CEILING", NATIVE_FEEDBACK_LABEL_RIGHT - len("CEILING"),
        NATIVE_FEEDBACK_CEILING_ROW + content_row_offset)
    put(1, "DAMPING", NATIVE_FEEDBACK_LABEL_RIGHT - len("DAMPING"),
        NATIVE_FEEDBACK_DAMPING_ROW + content_row_offset)


def put_native_page_headers(put, identity, titles):
    """Place the identity and common PAGE selector on native family pages."""
    for page, title in enumerate(titles):
        put(page, identity, 22 - ((len(identity) + 1) // 2), 2)
        put(page, "PAGE", 8, 8)
        put(page, title, 14 + ((8 - len(title)) // 2), 8)


def put_native_page_heading(put, page, text, x0=8):
    """Place a native page's descriptive heading above the content panel."""
    put(page, text, x0, NATIVE_PAGE_HEADING_ROW)


def put_native_support_page_labels(put, *, output_label_col=9,
                                   content_row_offsets=None,
                                   feedback_amount_row_offset=0,
                                   row_dry=False):
    """Place the common FEEDBACK through BANDS native static labels.

    Product-specific additions such as STREZO's OPTIONS ADVANCED section and
    BANDS MOTION controls are intentionally layered on by the caller.
    """
    offsets = content_row_offsets or {}
    feedback_offset = offsets.get(1, 0)
    input_offset = offsets.get(2, 0)
    group_offset = offsets.get(3, 0)
    output_offset = offsets.get(4, 0)
    options_offset = offsets.get(5, 0)
    bands_offset = offsets.get(6, 0)

    put_native_feedback_labels(
        put, content_row_offset=feedback_offset,
        amount_row_offset=feedback_amount_row_offset)

    put_native_page_heading(put, 2, "INPUT ROUTING")
    for input_index, (mode_row, value_row, depth_row) in enumerate(
            NATIVE_INPUT_TEXT_ROWS):
        put(2, f"IN{input_index}", 8, mode_row + input_offset)
        put(2, "MODE", 14, mode_row + input_offset)
        put(2, "VALUE", 13, value_row + input_offset)
        # DEPTH is mode-dependent and is written dynamically by each display
        # renderer. Keeping it out of the static template prevents AUDIO lanes
        # from inheriting a stale CV-only label.

    put_native_page_heading(put, 3, "BANK GROUPS")
    put(3, "BANKS", 20, 16 + group_offset)
    for group, row in enumerate(NATIVE_GROUP_TEXT_ROWS):
        put(3, f"GRP{group + 1}", 8, row + group_offset)

    put_native_page_heading(put, 4, "OUTPUT ROUTING")
    for x0, label in zip((16, 20, 24, 28, 32),
                         ("G1", "G2", "G3", "G4", "DRY")):
        put(4, label, x0, 18 + output_offset)
    for output, row in enumerate(NATIVE_OUTPUT_TEXT_ROWS):
        put(4, f"OUT{output}", output_label_col, row + output_offset)

    put_native_page_heading(put, 5, "STATE AND DISPLAY")
    put(5, "PALETTE", 13, 17 + options_offset)
    if row_dry:
        put(5, "ROW DRY", 10, 21 + options_offset)
        put(5, "SAVE DEFAULT", 8, 25 + options_offset)
    else:
        put(5, "SAVE DEFAULT", 8, 21 + options_offset)

    put_native_page_heading(put, 6, "PRESET")
    put(6, "ENABLE", 8, 16 + bands_offset)
    put(6, "SET FREQ", 8, 22 + bands_offset)
    put(6, "HZ", 26, 22 + bands_offset)


NATIVE_OUTPUT_ROW_SELECT_X0 = 116
NATIVE_OUTPUT_ROW_SELECT_X1 = 120
NATIVE_OUTPUT_COL_SELECT_Y0 = 280
NATIVE_OUTPUT_COL_SELECT_Y1 = 284
def native_input_gain_endpoint(gain):
    """Map an unsigned 8-bit gain onto the inset native VALUE fill lane."""
    mapped = NATIVE_INPUT_FILL_X0 + gain + (gain >> 4)
    return Mux(
        gain == 255,
        # The input renderer's registered comparison advances the visible
        # endpoint by one pixel.  Keeping the endpoint at the half-open fill
        # bound leaves two visible panel pixels at the chip's right edge.
        NATIVE_INPUT_FILL_X1,
        Mux(mapped > NATIVE_INPUT_FILL_X1,
            NATIVE_INPUT_FILL_X1, mapped),
    )


def native_input_depth_endpoint(depth):
    """Map signed CV DEPTH onto the inset bipolar native control lane."""
    mapped = NATIVE_INPUT_CONTROL_MID + depth + (depth >> 5)
    return Mux(
        depth <= -128, NATIVE_INPUT_FILL_X0,
        Mux(depth >= 127, NATIVE_INPUT_FILL_X1,
            Mux(mapped < NATIVE_INPUT_FILL_X0, NATIVE_INPUT_FILL_X0,
                Mux(mapped > NATIVE_INPUT_FILL_X1,
                    NATIVE_INPUT_FILL_X1, mapped))))


def native_input_meter_endpoint(meter, is_cv):
    """Scale INPUT telemetry across the compact lane and clamp its endpoint."""
    # Audio telemetry is signed(6) but non-negative in AUDIO mode. Nine pixels
    # per step reaches the end of the 272-pixel lane at the top code, while a
    # single shift/add keeps this display-only path inexpensive. The clamp
    # absorbs the final seven-pixel overrun at full scale.
    audio_offset = (meter << 3) + meter
    mapped = Mux(
        is_cv,
        NATIVE_INPUT_CONTROL_MID + (meter << 2) + (meter << 1),
        NATIVE_INPUT_CONTROL_X0 + audio_offset,
    )
    return Mux(mapped < NATIVE_INPUT_CONTROL_X0,
               NATIVE_INPUT_CONTROL_X0,
               Mux(mapped > NATIVE_INPUT_CONTROL_X1,
                   NATIVE_INPUT_CONTROL_X1, mapped))


def native_input_unity_x(unity_position):
    """Return the native x coordinate of a 16-bit gain's 0 dB marker."""
    coarse = unity_position >> 8
    return NATIVE_INPUT_FILL_X0 + coarse + (coarse >> 4)


def native_main_fader_endpoint(value, x0=NATIVE_MAIN_FILL_X0):
    """Map a 0..128 long control across a 307-pixel inset fill lane."""
    return (x0 + (value << 1) + (value >> 2) + (value >> 3) +
            (value >> 6) + (value >> 7))


def native_cross_fader_endpoint(value, x0=234):
    """Map a 0..128 CROSS control across its 344-pixel inset fill lane."""
    return (x0 + (value << 1) + (value >> 1) + (value >> 3) +
            (value >> 4))


def native_motion_depth_endpoint(value, x0=282):
    """Map a 0..128 motion DEPTH across its 284-pixel inset fill lane."""
    return (x0 + (value << 1) + (value >> 3) + (value >> 4) +
            (value >> 5))


def output_header_selection(*, page, row_active, col_active,
                            row_target, col_target,
                            selected_row, selected_col,
                            matrix_row, matrix_col, dry_selected,
                            x, y, y_shift=0):
    """Shared solid-bar selector for the common OUTPUT routing matrix."""
    row_x0 = NATIVE_OUTPUT_ROW_SELECT_X0
    row_x1 = NATIVE_OUTPUT_ROW_SELECT_X1
    col_y0 = NATIVE_OUTPUT_COL_SELECT_Y0 + y_shift
    col_y1 = NATIVE_OUTPUT_COL_SELECT_Y1 + y_shift
    return page & (
        (row_active & row_target & (selected_row == matrix_row) &
         (x >= row_x0) & (x < row_x1)) |
        (col_active & (y >= col_y0) & (y < col_y1) &
         ((col_target & (selected_col == matrix_col)) |
          (dry_selected & (matrix_col == 4))))
    )
