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
    NATIVE_GROUP_CENTERS,
    NATIVE_GROUP_TEXT_ROWS,
    NATIVE_INPUT_CONTROL_X0,
    NATIVE_INPUT_CONTROL_X1,
    NATIVE_INPUT_PANEL_Y0,
    NATIVE_INPUT_PANEL_Y1,
    NATIVE_INPUT_TEXT_ROWS,
    NATIVE_MAIN_CONTROL_TEXT_ROWS,
    NATIVE_MAIN_CONTROL_Y0S,
    NATIVE_OUTPUT_COL_CENTERS,
    NATIVE_OUTPUT_COL_SELECT_Y0,
    NATIVE_OUTPUT_ROW_CENTERS,
    NATIVE_OUTPUT_ROW_SELECT_X0,
    NATIVE_OUTPUT_TEXT_ROWS,
    native_feedback_track_rows,
    native_input_unity_x,
    put_legacy_support_page_labels,
    put_native_feedback_labels,
    put_native_page_headers,
    put_native_support_page_labels,
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


def test_shared_native_rows_and_centers_match_family_layout():
    assert NATIVE_INPUT_TEXT_ROWS == (
        (14, 16, 18), (20, 22, 24),
        (26, 28, 30), (32, 34, 36))
    assert NATIVE_GROUP_TEXT_ROWS == (20, 23, 26, 29)
    assert NATIVE_GROUP_CENTERS == (326, 374, 422, 470)
    assert NATIVE_OUTPUT_TEXT_ROWS == (21, 25, 29, 33)
    assert NATIVE_OUTPUT_ROW_CENTERS == (342, 406, 470, 534)
    assert NATIVE_OUTPUT_COL_CENTERS == (270, 334, 398, 462, 534)
    assert NATIVE_MAIN_CONTROL_TEXT_ROWS == (28, 30, 32, 34, 36)
    assert NATIVE_MAIN_CONTROL_Y0S == (448, 480, 512, 544, 576)


def test_shared_native_headers_preserve_product_identity_and_title_centers():
    calls = []
    put_native_page_headers(
        lambda *args: calls.append(args),
        "REZOMO", ("BANK", "FEEDBACK"))

    assert calls == [
        (0, "REZOMO", 19, 2),
        (0, "PAGE", 8, 8),
        (0, "BANK", 16, 8),
        (1, "REZOMO", 19, 2),
        (1, "PAGE", 8, 8),
        (1, "FEEDBACK", 14, 8),
    ]


def test_shared_support_labels_cover_every_common_page():
    calls = []
    put_native_support_page_labels(lambda *args: calls.append(args))

    assert (1, "FEEDBACK", 8, NATIVE_FEEDBACK_AMOUNT_ROW) in calls
    assert (2, "INPUT ROUTING", 8, 12) in calls
    assert (2, "DEPTH", 13, 36) in calls
    assert (3, "GRP4", 8, 29) in calls
    assert (4, "DRY", 32, 18) in calls
    assert (4, "OUT3", 9, 33) in calls
    assert (5, "SAVE DEFAULT", 8, 21) in calls
    assert (6, "SET FREQ", 8, 22) in calls


def test_rezo_can_layer_dynamic_input_depth_labels_over_shared_page():
    calls = []
    put_native_support_page_labels(
        lambda *args: calls.append(args), input_depth_labels=False)

    assert not any(page == 2 and text == "DEPTH"
                   for page, text, _x, _row in calls)
    assert (2, "VALUE", 13, 34) in calls


def test_legacy_support_labels_share_structure_with_product_overrides():
    calls = []
    put_legacy_support_page_labels(
        lambda *args: calls.append(args), frequency_col=18,
        output_row_col=2,
        output_labels=("GRP1", "GRP2", "GRP3", "GRP4", ""))

    assert (1, "FREQ:", 18, 11) in calls
    assert (2, "DEPTH", 8, 35) in calls
    assert (3, "GRP4", 3, 31) in calls
    assert (4, "OUT3", 2, 36) in calls
    assert not any(page == 4 and text == "DRY"
                   for page, text, _x, _row in calls)
    assert (5, "SAVE DEFAULT", 3, 19) in calls
    assert (6, "SET FREQ", 2, 22) in calls
