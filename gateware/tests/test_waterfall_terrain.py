import importlib.util
from pathlib import Path

from amaranth import Module, Signal
from amaranth.sim import Simulator


WATERFALL_SRC = Path(__file__).parents[1] / "src" / "top" / "waterfall"
spec = importlib.util.spec_from_file_location(
    "waterfall_terrain_spectrogram", WATERFALL_SRC / "spectrogram.py")
waterfall_spectrogram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(waterfall_spectrogram)
_log_frequency_bin_buckets = waterfall_spectrogram._log_frequency_bin_buckets
_terrain_visibility_level = waterfall_spectrogram._terrain_visibility_level


def test_log_frequency_buckets_cover_positive_spectrum():
    for point_count in (64, 128):
        buckets = _log_frequency_bin_buckets(point_count)
        assert len(buckets) == point_count
        assert buckets[0][0] == 1
        assert buckets[-1][1] == 255
        assert all(1 <= first <= last <= 255 for first, last in buckets)
        assert all(
            next_first <= last + 1
            for (_, last), (next_first, _) in zip(buckets, buckets[1:])
        )


def test_log_frequency_buckets_give_octaves_equal_space():
    buckets = _log_frequency_bin_buckets(128)

    def center_of_points_containing(bin_index):
        points = [
            point for point, (first, last) in enumerate(buckets)
            if first <= bin_index <= last
        ]
        return sum(points) / len(points)

    # The first two integer FFT bins necessarily occupy wider repeated regions;
    # above them, each octave should consume essentially identical screen space.
    octave_points = [center_of_points_containing(bin_index)
                     for bin_index in (4, 8, 16, 32, 64, 128)]
    octave_widths = [b - a for a, b in zip(octave_points, octave_points[1:])]
    assert max(octave_widths) - min(octave_widths) <= 1


def test_terrain_visibility_culls_quiet_old_facets_without_recoloring():
    m = Module()
    level = Signal(6)
    age = Signal(4)
    age_fade = Signal()
    visibility = Signal(6)
    m.d.comb += visibility.eq(
        _terrain_visibility_level(level, age, age_fade))

    async def bench(ctx):
        for source_level, source_age, fade, expected in (
                (0, 15, 1, 0),
                (6, 15, 1, 0),
                (15, 15, 1, 0),
                (24, 15, 1, 0),
                (31, 15, 1, 1),
                (40, 15, 1, 10),
                (24, 7, 1, 10),
                (6, 15, 0, 6)):
            ctx.set(level, source_level)
            ctx.set(age, source_age)
            ctx.set(age_fade, fade)
            await ctx.delay(1e-9)
            assert ctx.get(visibility) == expected

    sim = Simulator(m)
    sim.add_testbench(bench)
    sim.run()
