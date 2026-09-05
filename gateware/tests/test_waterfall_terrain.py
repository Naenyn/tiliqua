import importlib.util
from pathlib import Path


WATERFALL_SRC = Path(__file__).parents[1] / "src" / "top" / "waterfall"
spec = importlib.util.spec_from_file_location(
    "waterfall_terrain_spectrogram", WATERFALL_SRC / "spectrogram.py")
waterfall_spectrogram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(waterfall_spectrogram)
_log_frequency_bin_buckets = waterfall_spectrogram._log_frequency_bin_buckets


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
