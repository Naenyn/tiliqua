from top.rezo.ui_common import (
    NATIVE_FEEDBACK_AMOUNT_ROW,
    NATIVE_FEEDBACK_AMOUNT_Y0,
    NATIVE_FEEDBACK_CEILING_Y0,
    NATIVE_FEEDBACK_DAMPING_CHIP_X0,
    NATIVE_FEEDBACK_DAMPING_CHIP_X1,
    NATIVE_FEEDBACK_DAMPING_CHIP_Y0,
    NATIVE_FEEDBACK_DAMPING_CHIP_Y1,
    NATIVE_FEEDBACK_DAMPING_ROW,
    NATIVE_FEEDBACK_DAMPING_TEXT_COL,
    NATIVE_FEEDBACK_DAMPING_TEXT_ROW,
    NATIVE_FEEDBACK_KNEE_Y0,
    NATIVE_FEEDBACK_KNEE_ROW,
    NATIVE_FEEDBACK_LABEL_RIGHT,
    NATIVE_FEEDBACK_SAFETY_TITLE_ROW,
    NATIVE_FEEDBACK_CEILING_ROW,
    NATIVE_INPUT_CONTROL_X0,
    NATIVE_INPUT_CONTROL_X1,
    NATIVE_INPUT_PANEL_Y0,
    NATIVE_INPUT_PANEL_Y1,
    NATIVE_OUTPUT_COL_SELECT_Y0,
    NATIVE_OUTPUT_ROW_SELECT_X0,
    native_feedback_track_rows,
    native_input_unity_x,
    put_native_feedback_labels,
)


def test_shared_native_page_geometry_matches_the_508_pixel_layout():
    assert (NATIVE_INPUT_PANEL_Y0, NATIVE_INPUT_PANEL_Y1) == (218, 599)
    assert (NATIVE_INPUT_CONTROL_X0, NATIVE_INPUT_CONTROL_X1) == (304, 576)
    assert NATIVE_OUTPUT_ROW_SELECT_X0 == 116
    assert NATIVE_OUTPUT_COL_SELECT_Y0 == 280
    assert NATIVE_FEEDBACK_AMOUNT_ROW == 21
    assert NATIVE_FEEDBACK_SAFETY_TITLE_ROW == 24
    assert (
        NATIVE_FEEDBACK_KNEE_ROW,
        NATIVE_FEEDBACK_CEILING_ROW,
        NATIVE_FEEDBACK_DAMPING_ROW,
    ) == (26, 28, 30)
    assert (
        NATIVE_FEEDBACK_DAMPING_CHIP_X0,
        NATIVE_FEEDBACK_DAMPING_CHIP_X1,
        NATIVE_FEEDBACK_DAMPING_CHIP_Y0,
        NATIVE_FEEDBACK_DAMPING_CHIP_Y1,
    ) == (264, 360, 472, 504)
    assert (
        NATIVE_FEEDBACK_DAMPING_TEXT_COL,
        NATIVE_FEEDBACK_DAMPING_TEXT_ROW,
    ) == (17, NATIVE_FEEDBACK_DAMPING_ROW)


def test_shared_input_unity_marker_uses_the_established_gain_mapping():
    assert native_input_unity_x(52428) == 520


def test_shared_feedback_tracks_follow_the_label_control_rows():
    calls = []

    def rect(*args):
        calls.append(args)
        return 0

    native_feedback_track_rows(rect, "x", "y", 268, 588)

    assert calls == [
        ("x", "y", 268, NATIVE_FEEDBACK_AMOUNT_Y0 - 2,
         588, NATIVE_FEEDBACK_AMOUNT_Y0 + 18),
        ("x", "y", 268, NATIVE_FEEDBACK_KNEE_Y0 - 2,
         588, NATIVE_FEEDBACK_KNEE_Y0 + 18),
        ("x", "y", 268, NATIVE_FEEDBACK_CEILING_Y0 - 2,
         588, NATIVE_FEEDBACK_CEILING_Y0 + 18),
    ]


def test_shared_feedback_control_labels_have_a_common_right_edge():
    calls = []

    def put(*args):
        calls.append(args)

    put_native_feedback_labels(put)

    controls = {
        text: x
        for _enabled, text, x, _row in calls
        if text in ("FEEDBACK", "KNEE", "CEILING", "DAMPING")
    }
    assert controls
    assert {
        x + len(text) for text, x in controls.items()
    } == {NATIVE_FEEDBACK_LABEL_RIGHT}
