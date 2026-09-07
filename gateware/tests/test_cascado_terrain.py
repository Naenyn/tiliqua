import importlib.util
from pathlib import Path

from amaranth import Module, Signal
from amaranth.sim import Simulator
from amaranth_soc import csr
from amaranth_soc.csr import wishbone as csr_wishbone
from tiliqua.dsp import ASQ
from tiliqua.test import csr as csr_util


CASCADO_SRC = Path(__file__).parents[1] / "src" / "top" / "cascado"
spec = importlib.util.spec_from_file_location(
    "cascado_terrain_spectrogram", CASCADO_SRC / "spectrogram.py")
cascado_spectrogram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cascado_spectrogram)
_log_frequency_bin_buckets = cascado_spectrogram._log_frequency_bin_buckets
_terrain_visibility_level = cascado_spectrogram._terrain_visibility_level
_magnitude_raw_to_dbfs_level = cascado_spectrogram._magnitude_raw_to_dbfs_level
_approximate_magnitude_raw_to_dbfs_level = (
    cascado_spectrogram._approximate_magnitude_raw_to_dbfs_level)
Spectrogram = cascado_spectrogram.Spectrogram
MagnitudeToDbfs = cascado_spectrogram.MagnitudeToDbfs
LineStripCmd = cascado_spectrogram.LineStripCmd


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


def test_log_magnitude_approximation_is_monotonic_and_accurate():
    """The compact LUT must not step backward at exponent boundaries."""
    previous = 0
    maximum_error = 0
    for raw in range(1, 1 << 16):
        approximate = _approximate_magnitude_raw_to_dbfs_level(raw)
        exact = _magnitude_raw_to_dbfs_level(raw)
        assert approximate >= previous
        maximum_error = max(maximum_error, abs(approximate - exact))
        previous = approximate

    assert maximum_error <= 1


def test_hardware_log_magnitude_matches_fractional_lut_model():
    dut = MagnitudeToDbfs(ASQ)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.o.ready, 1)
        # Exercise both sides of every exponent transition as well as full
        # scale. The old independently rounded tables stepped backward at
        # 1023 -> 1024 even though the input magnitude increased.
        raw_values = [1]
        for exponent in range(1, ASQ.as_shape().width):
            boundary = 1 << exponent
            raw_values.extend((boundary - 1, boundary))
        raw_values.append((1 << ASQ.as_shape().width) - 1)

        previous = 0
        for raw in raw_values:
            ctx.set(dut.i.payload.sample.as_value(), raw)
            ctx.set(dut.i.valid, 1)
            while not ctx.get(dut.i.ready):
                await ctx.tick()
            await ctx.tick()
            ctx.set(dut.i.valid, 0)
            while not ctx.get(dut.o.valid):
                await ctx.tick()

            actual = ctx.get(dut.o.payload.sample)
            expected = _approximate_magnitude_raw_to_dbfs_level(raw)
            assert actual == expected
            assert actual >= previous
            previous = actual
            await ctx.tick()

    sim.add_testbench(bench)
    sim.run()


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


def test_terrain_ridges_replay_only_the_newest_row_after_the_fill():
    """Terrain ridges are one post-fill line strip, not embedded fragments."""
    dut = Spectrogram(fs=192_000)
    m = Module()
    decoder = csr.Decoder(addr_width=28, data_width=8)
    decoder.add(dut.bus, addr=0, name="dut")
    bridge = csr_wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
    m.submodules += [dut, decoder, bridge]
    sim = Simulator(m)
    sim.add_clock(1 / 60_000_000, domain="sync")
    sim.add_clock(1 / 74_250_000, domain="dvi")
    line_commands = []
    triangle_commands = 0

    async def write_flags(ctx, enable, axes):
        await csr_util.wb_csr_w_dict(ctx, dut.bus, bridge.wb_bus, "flags", {
            "enable": enable,
            "axes": axes,
            "input_ch": 0,
            "display_ack": 0,
        })

    async def bench(ctx):
        nonlocal triangle_commands
        ctx.set(dut.clear_done, 1)
        ctx.set(dut.flush_done, 1)
        ctx.set(dut.line_busy, 0)
        ctx.set(dut.line_o.ready, 1)
        ctx.set(dut.triangle_o.ready, 1)

        # Stop the power-on sweep before configuring an axis-free adaptive
        # terrain frame. Untouched history is quiet, so no fill triangles are
        # needed; the optional ridge must nevertheless replay the complete
        # newest projected row through the independent line renderer.
        await write_flags(ctx, 0, 0)
        for _ in range(100_000):
            if ctx.get(dut._status.f.renderer_idle.r_data):
                break
            await ctx.tick()
        else:
            raise AssertionError("renderer did not stop for ridge test")

        await csr_util.wb_csr_w_dict(
            ctx, dut.bus, bridge.wb_bus, "config_3d", {
                "quality": 0,
                "style": 1,
                "log_scale": 0,
                "age_fade": 0,
                "frequency_color": 0,
                "ridges": 1,
            })
        await write_flags(ctx, 1, 0)

        for _ in range(150_000):
            if ctx.get(dut.triangle_o.valid):
                triangle_commands += 1
            if ctx.get(dut.line_o.valid):
                line_commands.append({
                    "x": ctx.get(dut.line_o.payload.x),
                    "y": ctx.get(dut.line_o.payload.y),
                    "pixel": ctx.get(dut.line_o.payload.pixel.as_value()),
                    "cmd": ctx.get(dut.line_o.payload.cmd),
                })
                if line_commands[-1]["cmd"] == LineStripCmd.END:
                    return
            await ctx.tick()
        raise AssertionError("terrain emitted no completed newest-row ridge")

    sim.add_testbench(bench)
    sim.run()
    assert triangle_commands == 0
    assert len(line_commands) == 128
    assert all(command["pixel"] == 0 for command in line_commands)
    assert all(command["cmd"] == LineStripCmd.CONTINUE
               for command in line_commands[:-1])
    assert line_commands[-1]["cmd"] == LineStripCmd.END


def test_adaptive_wire_geometry_refines_near_history_only():
    """Adaptive mode emits 8x64 far points followed by 8x128 near points."""
    dut = Spectrogram(fs=192_000)
    m = Module()
    decoder = csr.Decoder(addr_width=28, data_width=8)
    decoder.add(dut.bus, addr=0, name="dut")
    bridge = csr_wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
    m.submodules += [dut, decoder, bridge]
    sim = Simulator(m)
    sim.add_clock(1 / 60_000_000, domain="sync")
    sim.add_clock(1 / 74_250_000, domain="dvi")
    command_count = 0
    completed_rows = 0
    row_lengths = []
    current_row_length = 0

    async def write_flags(ctx, enable, axes):
        await csr_util.wb_csr_w_dict(ctx, dut.bus, bridge.wb_bus, "flags", {
            "enable": enable,
            "axes": axes,
            "input_ch": 0,
            "display_ack": 0,
        })

    async def bench(ctx):
        nonlocal command_count, completed_rows, current_row_length
        ctx.set(dut.clear_done, 1)
        ctx.set(dut.flush_done, 1)
        ctx.set(dut.line_busy, 0)
        ctx.set(dut.line_o.ready, 1)
        ctx.set(dut.triangle_o.ready, 1)

        # Stop the power-on default sweep before configuring a deterministic
        # wire-only adaptive frame.
        await write_flags(ctx, 0, 0)
        for _ in range(100_000):
            if ctx.get(dut._status.f.renderer_idle.r_data):
                break
            await ctx.tick()
        else:
            raise AssertionError("renderer did not stop for adaptive test")

        await csr_util.wb_csr_w_dict(
            ctx, dut.bus, bridge.wb_bus, "config_3d", {
                "quality": 0,
                "style": 0,
                "log_scale": 0,
                "age_fade": 0,
                "frequency_color": 0,
                "ridges": 0,
            })
        await write_flags(ctx, 1, 0)

        for _ in range(150_000):
            if ctx.get(dut.line_o.valid):
                command_count += 1
                current_row_length += 1
                if ctx.get(dut.line_o.payload.cmd) == LineStripCmd.END:
                    row_lengths.append(current_row_length)
                    current_row_length = 0
                    completed_rows += 1
                    if completed_rows == 16:
                        return
            await ctx.tick()
        raise AssertionError("adaptive wire frame did not finish")

    sim.add_testbench(bench)
    sim.run()
    assert command_count == 8 * 64 + 8 * 128
    assert row_lengths == [64] * 8 + [128] * 8
