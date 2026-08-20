from top.rezo.ui_common import (
    NATIVE_FEEDBACK_AMOUNT_ROW,
    NATIVE_FEEDBACK_SAFETY_TITLE_ROW,
    NATIVE_INPUT_CONTROL_X0,
    NATIVE_INPUT_CONTROL_X1,
    NATIVE_INPUT_PANEL_Y0,
    NATIVE_INPUT_PANEL_Y1,
    NATIVE_OUTPUT_COL_SELECT_Y0,
    NATIVE_OUTPUT_ROW_SELECT_X0,
    native_input_unity_x,
)


def test_shared_native_page_geometry_matches_the_508_pixel_layout():
    assert (NATIVE_INPUT_PANEL_Y0, NATIVE_INPUT_PANEL_Y1) == (218, 599)
    assert (NATIVE_INPUT_CONTROL_X0, NATIVE_INPUT_CONTROL_X1) == (304, 576)
    assert NATIVE_OUTPUT_ROW_SELECT_X0 == 116
    assert NATIVE_OUTPUT_COL_SELECT_Y0 == 280
    assert NATIVE_FEEDBACK_AMOUNT_ROW == 21
    assert NATIVE_FEEDBACK_SAFETY_TITLE_ROW == 23


def test_shared_input_unity_marker_uses_the_established_gain_mapping():
    assert native_input_unity_x(52428) == 520
