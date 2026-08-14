from tiliqua.build.timing import (
    insufficient_clocks,
    parse_timing_report,
)


def test_parse_timing_report_and_enforce_hardware_headroom():
    report = """
Info: Max frequency for clock '$glbnet$dvi5x_clk': 404.37 MHz (PASS at 371.33 MHz)
Info: Max frequency for clock '$glbnet$audio_clk': 73.49 MHz (PASS at 49.15 MHz)
Info: Max frequency for clock       '$glbnet$clk': 60.22 MHz (PASS at 60.00 MHz)
Info: Max frequency for clock   '$glbnet$dvi_clk': 74.54 MHz (PASS at 74.25 MHz)
"""
    timings = parse_timing_report(report)
    assert [timing.clock for timing in timings] == [
        "$glbnet$dvi5x_clk",
        "$glbnet$audio_clk",
        "$glbnet$clk",
        "$glbnet$dvi_clk",
    ]
    assert [timing.clock for timing in insufficient_clocks(timings, 1.25)] == [
        "$glbnet$clk",
        "$glbnet$dvi_clk",
    ]


def test_reported_failure_is_rejected_despite_numeric_rounding():
    report = """
Warning: Max frequency for clock '$glbnet$clk': 60.00 MHz (FAIL at 60.00 MHz)
"""
    timing, = parse_timing_report(report)
    assert insufficient_clocks([timing], 0.0) == [timing]


def test_final_route_summary_replaces_preliminary_placement_estimate():
    report = """
Warning: Max frequency for clock '$glbnet$dvi_clk': 59.24 MHz (FAIL at 74.25 MHz)
Info: Max frequency for clock '$glbnet$dvi_clk': 75.05 MHz (PASS at 74.25 MHz)
"""
    timing, = parse_timing_report(report)
    assert timing.actual_mhz == 75.05
    assert timing.reported_status == "PASS"
