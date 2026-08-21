# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Shared REZO-family page geometry and small rendering expressions."""

from amaranth import Mux


NATIVE_INPUT_PANEL_Y0 = 218
NATIVE_INPUT_PANEL_Y1 = 599
NATIVE_INPUT_CONTROL_X0 = 304
NATIVE_INPUT_CONTROL_X1 = 576
NATIVE_INPUT_CONTROL_MID = 440

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
NATIVE_FEEDBACK_DAMPING_CHIP_X0 = 264
NATIVE_FEEDBACK_DAMPING_CHIP_X1 = 360
NATIVE_FEEDBACK_DAMPING_CHIP_Y0 = NATIVE_FEEDBACK_DAMPING_ROW * 16 - 8
NATIVE_FEEDBACK_DAMPING_CHIP_Y1 = NATIVE_FEEDBACK_DAMPING_ROW * 16 + 24
NATIVE_FEEDBACK_DAMPING_TEXT_COL = 17
NATIVE_FEEDBACK_DAMPING_TEXT_ROW = NATIVE_FEEDBACK_DAMPING_ROW


def native_feedback_track_rows(rect, x, y, x0, x1):
    """Return the three shared FEEDBACK-page shaded control tracks."""
    return (
        rect(x, y, x0, NATIVE_FEEDBACK_AMOUNT_Y0 - 2,
             x1, NATIVE_FEEDBACK_AMOUNT_Y0 + 18) |
        rect(x, y, x0, NATIVE_FEEDBACK_KNEE_Y0 - 2,
             x1, NATIVE_FEEDBACK_KNEE_Y0 + 18) |
        rect(x, y, x0, NATIVE_FEEDBACK_CEILING_Y0 - 2,
             x1, NATIVE_FEEDBACK_CEILING_Y0 + 18))


def put_native_feedback_labels(put):
    """Place the labels shared by every native REZO FEEDBACK page."""
    put(1, "FEEDBACK SOURCES", 8, 13)
    put(1, "BANDS", 8, 16)
    put(1, "FREQ:", 23, 16)
    put(1, "FEEDBACK", NATIVE_FEEDBACK_LABEL_RIGHT - len("FEEDBACK"),
        NATIVE_FEEDBACK_AMOUNT_ROW)
    put(1, "FEEDBACK SAFETY", 8, NATIVE_FEEDBACK_SAFETY_TITLE_ROW)
    put(1, "KNEE", NATIVE_FEEDBACK_LABEL_RIGHT - len("KNEE"),
        NATIVE_FEEDBACK_KNEE_ROW)
    put(1, "CEILING", NATIVE_FEEDBACK_LABEL_RIGHT - len("CEILING"),
        NATIVE_FEEDBACK_CEILING_ROW)
    put(1, "DAMPING", NATIVE_FEEDBACK_LABEL_RIGHT - len("DAMPING"),
        NATIVE_FEEDBACK_DAMPING_ROW)


def put_native_page_headers(put, identity, titles):
    """Place the identity and common PAGE selector on native family pages."""
    for page, title in enumerate(titles):
        put(page, identity, 22 - ((len(identity) + 1) // 2), 2)
        put(page, "PAGE", 8, 8)
        put(page, title, 14 + ((8 - len(title)) // 2), 8)


def put_native_support_page_labels(put, *, input_depth_labels=True):
    """Place the common FEEDBACK through BANDS native static labels.

    Product-specific additions such as STREZO's OPTIONS ADVANCED section and
    BANDS MOTION controls are intentionally layered on by the caller.
    """
    put_native_feedback_labels(put)

    put(2, "INPUT ROUTING", 8, 12)
    for input_index, (mode_row, value_row, depth_row) in enumerate(
            NATIVE_INPUT_TEXT_ROWS):
        put(2, f"IN{input_index}", 8, mode_row)
        put(2, "MODE", 14, mode_row)
        put(2, "VALUE", 13, value_row)
        if input_depth_labels:
            put(2, "DEPTH", 13, depth_row)

    put(3, "BANK GROUPS", 8, 13)
    put(3, "BANKS", 20, 16)
    for group, row in enumerate(NATIVE_GROUP_TEXT_ROWS):
        put(3, f"GRP{group + 1}", 8, row)

    put(4, "OUTPUT ROUTING", 8, 13)
    for x0, label in zip((16, 20, 24, 28, 32),
                         ("G1", "G2", "G3", "G4", "DRY")):
        put(4, label, x0, 18)
    for output, row in enumerate(NATIVE_OUTPUT_TEXT_ROWS):
        put(4, f"OUT{output}", 9, row)

    put(5, "STATE AND DISPLAY", 8, 13)
    put(5, "PALETTE", 13, 17)
    put(5, "SAVE DEFAULT", 8, 21)

    put(6, "PRESET", 8, 11)
    put(6, "ENABLE", 8, 16)
    put(6, "SET FREQ", 8, 22)
    put(6, "HZ", 26, 22)


def put_legacy_support_page_labels(put, *, frequency_col,
                                   output_row_col=3,
                                   input_depth_labels=True,
                                   output_labels=("GRP1", "GRP2", "GRP3",
                                                  "GRP4", "DRY")):
    """Place common support-page labels on the original 45-cell layout."""
    put(1, "FEEDBACK SOURCES", 2, 8)
    put(1, "BANDS", 2, 11)
    put(1, "FREQ:", frequency_col, 11)
    put(1, "FEEDBACK SAFETY", 2, 23)
    put(1, "KNEE", 2, 26)
    put(1, "CEILING", 2, 29)
    put(1, "DAMPING", 2, 32)

    put(2, "INPUT ROUTING", 2, 11)
    for lane in range(4):
        row = 13 + lane * 6
        put(2, f"IN{lane}", 3, row)
        put(2, "MODE", 8, row)
        put(2, "VALUE", 8, row + 2)
        if input_depth_labels:
            put(2, "DEPTH", 8, row + 4)

    put(3, "BANK GROUPS", 2, 11)
    put(3, "BANKS", 21, 15)
    for group in range(4):
        put(3, f"GRP{group + 1}", 3, 19 + group * 4)

    put(4, "OUTPUT ROUTING", 2, 11)
    for source, label in enumerate(output_labels):
        put(4, label, 12 + source * 6, 17)
    for output in range(4):
        put(4, f"OUT{output}", output_row_col, 21 + output * 5)

    put(5, "STATE AND DISPLAY", 2, 11)
    put(5, "PALETTE", 8, 15)
    put(5, "SAVE DEFAULT", 3, 19)

    put(6, "PRESET", 2, 7)
    put(6, "ENABLE", 2, 12)
    put(6, "SET FREQ", 2, 22)
    put(6, "HZ", 20, 22)


def add_feedback_navigation(m, *, edit_direction, selected, next_selected,
                            target_visible, page_target, send_base,
                            feedback_target, knee_target, damping_target,
                            band_count):
    """Emit navigation shared by every REZO-family FEEDBACK page."""
    with m.If(edit_direction):
        with m.If(~target_visible):
            m.d.comb += next_selected.eq(send_base)
        with m.Elif(selected == page_target):
            m.d.comb += next_selected.eq(send_base)
        with m.Elif(selected == damping_target):
            m.d.comb += next_selected.eq(page_target)
        with m.Elif(selected == send_base + band_count - 1):
            m.d.comb += next_selected.eq(feedback_target)
        with m.Elif(selected == feedback_target):
            m.d.comb += next_selected.eq(knee_target)
        with m.Else():
            m.d.comb += next_selected.eq(selected + 1)
    with m.Else():
        with m.If(~target_visible):
            m.d.comb += next_selected.eq(damping_target)
        with m.Elif(selected == page_target):
            m.d.comb += next_selected.eq(damping_target)
        with m.Elif(selected == send_base):
            m.d.comb += next_selected.eq(page_target)
        with m.Elif(selected == knee_target):
            m.d.comb += next_selected.eq(feedback_target)
        with m.Elif(selected == feedback_target):
            m.d.comb += next_selected.eq(send_base + band_count - 1)
        with m.Else():
            m.d.comb += next_selected.eq(selected - 1)


def add_input_navigation(m, *, edit_direction, selected, next_selected,
                         target_visible, page_target, input_base,
                         input_modes, cv_mode):
    """Emit four-lane MODE/VALUE/conditional-DEPTH INPUT navigation."""
    with m.If(edit_direction):
        with m.If(~target_visible):
            m.d.comb += next_selected.eq(input_base)
        with m.Elif(selected == page_target):
            m.d.comb += next_selected.eq(input_base)
        for lane in range(4):
            target_base = input_base + lane * 3
            next_input = page_target if lane == 3 else target_base + 3
            with m.Elif(selected == target_base):
                m.d.comb += next_selected.eq(target_base + 1)
            with m.Elif(selected == target_base + 1):
                m.d.comb += next_selected.eq(
                    Mux(input_modes[lane] == cv_mode,
                        target_base + 2, next_input))
            with m.Elif(selected == target_base + 2):
                m.d.comb += next_selected.eq(next_input)
    with m.Else():
        last_base = input_base + 9
        last_target = Mux(input_modes[3] == cv_mode,
                          last_base + 2, last_base + 1)
        with m.If(~target_visible):
            m.d.comb += next_selected.eq(last_target)
        with m.Elif(selected == page_target):
            m.d.comb += next_selected.eq(last_target)
        for lane in range(4):
            target_base = input_base + lane * 3
            if lane == 0:
                previous_input = page_target
            else:
                previous_base = input_base + (lane - 1) * 3
                previous_input = Mux(
                    input_modes[lane - 1] == cv_mode,
                    previous_base + 2, previous_base + 1)
            with m.Elif(selected == target_base):
                m.d.comb += next_selected.eq(previous_input)
            with m.Elif(selected == target_base + 1):
                m.d.comb += next_selected.eq(target_base)
            with m.Elif(selected == target_base + 2):
                m.d.comb += next_selected.eq(target_base + 1)


def add_group_navigation(m, *, edit_direction, selected, next_selected,
                         target_visible, page_target, group_base,
                         group_count):
    """Emit the linear BANK GROUPS navigation shared by the family."""
    last_group = group_base + group_count - 1
    with m.If(edit_direction):
        with m.If(~target_visible):
            m.d.comb += next_selected.eq(group_base)
        with m.Elif(selected == page_target):
            m.d.comb += next_selected.eq(group_base)
        with m.Elif(selected == last_group):
            m.d.comb += next_selected.eq(page_target)
        with m.Else():
            m.d.comb += next_selected.eq(selected + 1)
    with m.Else():
        with m.If(~target_visible):
            m.d.comb += next_selected.eq(last_group)
        with m.Elif(selected == page_target):
            m.d.comb += next_selected.eq(last_group)
        with m.Elif(selected == group_base):
            m.d.comb += next_selected.eq(page_target)
        with m.Else():
            m.d.comb += next_selected.eq(selected - 1)

NATIVE_OUTPUT_ROW_SELECT_X0 = 116
NATIVE_OUTPUT_ROW_SELECT_X1 = 120
NATIVE_OUTPUT_COL_SELECT_Y0 = 280
NATIVE_OUTPUT_COL_SELECT_Y1 = 284
LEGACY_OUTPUT_ROW_SELECT_X0 = 26
LEGACY_OUTPUT_ROW_SELECT_X1 = 30
LEGACY_OUTPUT_COL_SELECT_Y0 = 264
LEGACY_OUTPUT_COL_SELECT_Y1 = 268


def native_input_gain_endpoint(gain):
    """Map an unsigned 8-bit gain onto the complete native VALUE lane."""
    return Mux(
        gain == 255,
        # The input renderer prefetches x by one pixel before comparing the
        # registered endpoint.  Compensate here so full scale paints the last
        # pixel of the half-open VALUE lane without spilling into x=576.
        NATIVE_INPUT_CONTROL_X1 + 1,
        NATIVE_INPUT_CONTROL_X0 + gain + (gain >> 4),
    )


def native_input_unity_x(unity_position):
    """Return the native x coordinate of a 16-bit gain's 0 dB marker."""
    coarse = unity_position >> 8
    return NATIVE_INPUT_CONTROL_X0 + coarse + (coarse >> 4)


def output_header_selection(*, page, row_active, col_active,
                            row_target, col_target,
                            selected_row, selected_col,
                            matrix_row, matrix_col, dry_selected,
                            x, y, compact):
    """Shared solid-bar selector for the common OUTPUT routing matrix."""
    row_x0 = (NATIVE_OUTPUT_ROW_SELECT_X0 if compact
              else LEGACY_OUTPUT_ROW_SELECT_X0)
    row_x1 = (NATIVE_OUTPUT_ROW_SELECT_X1 if compact
              else LEGACY_OUTPUT_ROW_SELECT_X1)
    col_y0 = (NATIVE_OUTPUT_COL_SELECT_Y0 if compact
              else LEGACY_OUTPUT_COL_SELECT_Y0)
    col_y1 = (NATIVE_OUTPUT_COL_SELECT_Y1 if compact
              else LEGACY_OUTPUT_COL_SELECT_Y1)
    return page & (
        (row_active & row_target & (selected_row == matrix_row) &
         (x >= row_x0) & (x < row_x1)) |
        (col_active & (y >= col_y0) & (y < col_y1) &
         ((col_target & (selected_col == matrix_col)) |
          (dry_selected & (matrix_col == 4))))
    )
