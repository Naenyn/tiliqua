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

NATIVE_FEEDBACK_LABEL_RIGHT = 16
NATIVE_FEEDBACK_AMOUNT_ROW = 21
NATIVE_FEEDBACK_SAFETY_TITLE_ROW = 23
NATIVE_FEEDBACK_KNEE_ROW = 25
NATIVE_FEEDBACK_CEILING_ROW = 27
NATIVE_FEEDBACK_DAMPING_ROW = 29
NATIVE_FEEDBACK_AMOUNT_Y0 = NATIVE_FEEDBACK_AMOUNT_ROW * 16
NATIVE_FEEDBACK_KNEE_Y0 = NATIVE_FEEDBACK_KNEE_ROW * 16
NATIVE_FEEDBACK_CEILING_Y0 = NATIVE_FEEDBACK_CEILING_ROW * 16


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
