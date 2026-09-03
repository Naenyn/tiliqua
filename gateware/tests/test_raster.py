# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

import struct
import unittest

from amaranth import *
from amaranth.sim import *
from amaranth.lib import wiring

from tiliqua.test import wishbone, stream, csr as csr_util
from tiliqua.raster import (
    persist, stroke, plot, blit, line, scope_capture, scope_overlay,
)
from tiliqua.video import framebuffer, modeline, palette
from tiliqua.video.types import Rotation

from amaranth_soc import csr
from amaranth_soc.csr import wishbone as csr_wishbone


class RasterTests(unittest.TestCase):

    MODELINE = modeline.DVIModeline.all_timings()["1280x720p60"]

    def test_persist(self):

        m = Module()
        fb = framebuffer.DMAFramebuffer(
            fixed_modeline=self.MODELINE, palette=palette.ColorPalette())
        dut = persist.Persistance(bus_signature=fb.bus.signature)
        wiring.connect(m, wiring.flipped(fb.fbp), dut.fbp)
        check = wishbone.BusChecker(dut.bus, prefix='[bus] ')
        m.submodules += [dut, fb, fb.palette, check]

        # No actual FB backing store, just simulating WB transactions

        async def testbench(ctx):
            ctx.set(fb.fbp.enable, 1)
            # Simulate N burst accesses
            for _ in range(4):
                ix = 0
                while not ctx.get(dut.bus.stb):
                    await ctx.tick()
                # Simulate acks delayed from stb
                await ctx.tick().repeat(8)
                ctx.set(dut.bus.ack, 1)
                while ctx.get(dut.bus.stb):
                    # for all burst accesses, simulate full intensity.
                    ctx.set(dut.bus.dat_r, 0xffffff00 | (ix&0xf))
                    if ctx.get(dut.bus.we):
                        # for all burst reads, verify intensity of every
                        # pixel is reduced as expected
                        self.assertEqual(ctx.get(dut.bus.dat_w),
                                         0xefefef00 | (ix&0xf))
                    await ctx.tick()
                    ix = ix + 1
                ctx.set(dut.bus.ack, 0)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_persist.vcd", "w")):
            sim.run()

    def test_stroke(self):

        m = Module()
        dut = stroke.Stroke()
        m.submodules += [dut]

        N = 8

        async def stimulus(ctx):
            # Send a few sample points to the stroke
            for n in range(N):
                await stream.put(ctx, dut.i, [0, 0, 0, 0])
                await ctx.tick().repeat(4)

        async def testbench(ctx):
            for _ in range(N):
                # Test passes if we got something
                _ = await stream.get(ctx, dut.o)
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.add_process(stimulus)
        with sim.write_vcd(vcd_file=open("test_stroke.vcd", "w")):
            sim.run()

    def test_plot_backend(self):

        m = Module()
        fb = framebuffer.DMAFramebuffer(
            fixed_modeline=self.MODELINE, palette=palette.ColorPalette())
        dut = plot._FramebufferBackend(
            wishbone.Signature(addr_width=fb.bus.addr_width, data_width=32, granularity=8)
        )
        wiring.connect(m, wiring.flipped(fb.fbp), dut.fbp)
        check = wishbone.BusChecker(dut.bus, prefix='[bus] ')
        m.submodules += [dut, fb, fb.palette, check]

        async def testbench(ctx):
            ctx.set(fb.fbp.enable, 1)
            # Absolute positioning with replacement
            await stream.put(ctx, dut.i, {
                'x': 1,
                'y': 0,
                'pixel': {
                    'color': 0xa,
                    'intensity': 0xb,
                },
                'blend': plot.BlendMode.REPLACE,
                'offset': plot.OffsetMode.ABSOLUTE,
            })
            result = await wishbone.classic_ack(ctx, dut.bus)
            self.assertEqual(result.adr, 0x0)
            self.assertEqual(result.dat_w, 0xbabababa)
            self.assertEqual(result.sel, 0b0010)

            # Center positioning with replacement
            await stream.put(ctx, dut.i, {
                'x': 1,
                'y': 0,
                'pixel': {
                    'color': 0xa,
                    'intensity': 0xb,
                },
                'blend': plot.BlendMode.REPLACE,
                'offset': plot.OffsetMode.CENTER,
            })
            result = await wishbone.classic_ack(ctx, dut.bus)
            self.assertEqual(
                result.adr,
                int(self.MODELINE.h_active/4*(self.MODELINE.v_active/2 + 1/2)))
            self.assertEqual(result.dat_w, 0xbabababa)
            self.assertEqual(result.sel, 0b0010)

            # Absolute positioning, additive blending
            await stream.put(ctx, dut.i, {
                'x': 1,
                'y': 0,
                'pixel': {
                    'color': 0xa,
                    'intensity': 0xb,
                },
                'blend': plot.BlendMode.ADDITIVE,
                'offset': plot.OffsetMode.ABSOLUTE,
            })
            # Read cycle (get current pixel value)
            ctx.set(dut.bus.dat_r, 0x00009100)
            result = await wishbone.classic_ack(ctx, dut.bus)
            self.assertEqual(result.adr, 0x0)
            self.assertEqual(result.sel, 0b0010)
            # Write cycle (put newly calculated pixel value)
            result = await wishbone.classic_ack(ctx, dut.bus)
            self.assertEqual(result.adr, 0x0)
            self.assertEqual(result.sel, 0b0010)
            self.assertEqual(result.dat_w, 0xfafafafa)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_plot_backend.vcd", "w")):
            sim.run()

    def test_blit_peripheral(self):

        """
        Write a spritesheet to the blitter and blit a sub-rectangle of it, recording
        the plotted points into an ASCII grid for inspection.
        """

        m = Module()
        dut = blit.Peripheral()
        decoder = csr.Decoder(addr_width=28, data_width=8)
        decoder.add(dut.csr_bus, addr=0, name="dut")
        bridge = csr_wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
        m.submodules += [dut, decoder, bridge]

        async def test_stimulus(ctx):

            async def csr_write(ctx, register, fields):
                await csr_util.wb_csr_w_dict(
                        ctx, dut.csr_bus, bridge.wb_bus, register, fields)

            # Write spritesheet to the blitter - read 32-bit words from file in the same
            # way that a RISCV32 would memcpy a raw spritesheet to sprite memory.
            word_addr = 0
            with open('tests/data/font_9x15.raw', 'rb') as f:
                while True:
                    word_bytes = f.read(4)
                    if not word_bytes:
                        break
                    if len(word_bytes) < 4:
                        word_bytes += b'\x00' * (4 - len(word_bytes))
                    word_data = struct.unpack('<I', word_bytes)[0]
                    await wishbone.classic_wr(ctx, dut.sprite_mem_bus, adr=word_addr, dat_w=word_data)
                    word_addr += 1

            # Set spritesheet width so core can index it properly
            sheet_width = 144
            sheet_height = 90 # (width*height)//32 must fit in the sprite mem
            await csr_write(ctx, "sheet_width", {
                "width": sheet_width,
            })

            # Issue a blit
            await csr_write(ctx, "src", {
                "src_x": 0,
                "src_y": 0,
                "width": 0x28,
                "height": 0x24,
            })

            await csr_write(ctx, "blit", {
                "pixel": 0xab,
                "dst_x": 5,
                "dst_y": 3,
            })

            while True:
                await ctx.tick()

        async def test_response(ctx):
            # Collect all the blitted points into an ASCII grid, and print it
            ctx.set(dut.o.ready, 1)
            points = set()
            for _ in range(8000):
                if ctx.get(dut.o.valid):
                    p_x = ctx.get(dut.o.payload.x)
                    p_y = ctx.get(dut.o.payload.y)
                    points.add((p_x, p_y))
                await ctx.tick()
            print()
            for y in range(40):
                row = ''
                for x in range(50):
                    if (x, y) in points:
                        row = row+'#'
                    else:
                        row = row+'.'
                print(row)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(test_stimulus, background=True)
        sim.add_testbench(test_response)
        with sim.write_vcd(vcd_file=open("test_blit_peripheral.vcd", "w")):
            sim.run()

    def test_line_peripheral(self):

        """
        Draw lines using the line plotter, recording the plotted points into
        an ASCII grid for inspection.
        """

        m = Module()
        dut = line.Peripheral()
        decoder = csr.Decoder(addr_width=28, data_width=8)
        decoder.add(dut.csr_bus, addr=0, name="dut")
        bridge = csr_wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
        m.submodules += [dut, decoder, bridge]

        async def test_stimulus(ctx):

            async def csr_write(ctx, register, fields):
                await csr_util.wb_csr_w_dict(
                        ctx, dut.csr_bus, bridge.wb_bus, register, fields)

            # Draw a closed triangle line strip

            await csr_write(ctx, "point", {
                "cmd": 0,
                "pixel": 0xff,
                "x": 10,
                "y": 5,
            })

            await csr_write(ctx, "point", {
                "cmd": 0,
                "pixel": 0xff,
                "x": 30,
                "y": 5,
            })

            await csr_write(ctx, "point", {
                "cmd": 0,
                "pixel": 0xff,
                "x": 20,
                "y": 20,
            })

            await csr_write(ctx, "point", {
                "cmd": 1, # end
                "pixel": 0xff,
                "x": 10,
                "y": 5,
            })

            # Draw a single isolated line.

            await csr_write(ctx, "point", {
                "cmd": 0,
                "pixel": 0xff,
                "x": 4,
                "y": 5,
            })

            await csr_write(ctx, "point", {
                "cmd": 1, # end
                "pixel": 0xff,
                "x": 12,
                "y": 20,
            })

            while True:
                await ctx.tick()

        async def test_response(ctx):
            # Collect all the plotted points into an ASCII grid
            ctx.set(dut.o.ready, 1)
            points = set()
            for _ in range(5000):
                if ctx.get(dut.o.valid):
                    p_x = ctx.get(dut.o.payload.x)
                    p_y = ctx.get(dut.o.payload.y)
                    points.add((p_x, p_y))
                await ctx.tick()
            print()
            for y in range(25):
                row = ''
                for x in range(40):
                    if (x, y) in points:
                        row = row+'#'
                    else:
                        row = row+'.'
                print(row)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(test_stimulus, background=True)
        sim.add_testbench(test_response)
        with sim.write_vcd(vcd_file=open("test_line_peripheral.vcd", "w")):
            sim.run()


class ScopeRasterAccuracyTests(unittest.TestCase):

    def test_vertical_scale_lut_tracks_grid_voltage(self):
        """Every V/div choice should map its nominal voltage to one grid division."""
        from tiliqua.raster import PSQ, PSQ_BASE_FBITS, psq_from_volts

        counts_per_volt = (
            psq_from_volts(1.0).as_value().value <<
            (PSQ_BASE_FBITS - PSQ.f_bits)
        )
        pixels_per_div = counts_per_volt >> 6
        volts_per_div = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

        self.assertEqual(counts_per_volt, 4000)
        self.assertEqual(pixels_per_div, 62)
        for v_div, (mul, shift) in zip(
                volts_per_div, scope_capture.YSCALE_LUT):
            actual_pixels_per_volt = counts_per_volt * mul / (1 << shift)
            target_pixels_per_volt = pixels_per_div / v_div
            relative_error = abs(
                actual_pixels_per_volt / target_pixels_per_volt - 1.0)
            self.assertLess(
                relative_error, 0.002,
                f"{v_div} V/div scale error is {relative_error:.3%}")

            # Coordinate conversion rounds rather than flooring signed values:
            # one nominal division must have equal magnitude in both polarities.
            sample = int(counts_per_volt * v_div)
            bias = 1 << (shift - 1)
            positive_y = ((-sample * mul) + bias) >> shift
            negative_y = ((sample * mul) + bias) >> shift
            self.assertEqual(positive_y, -pixels_per_div)
            self.assertEqual(negative_y, pixels_per_div)

    def _unpack_ch0(self, word):
        bits = scope_capture.ENVELOPE_COORD_BITS
        mask = (1 << bits) - 1
        self.assertEqual(word & 1, 1)
        ymin = (word >> 1) & mask
        ymax = (word >> (1 + bits)) & mask
        if ymin >= (1 << (bits - 1)):
            ymin -= 1 << bits
        if ymax >= (1 << (bits - 1)):
            ymax -= 1 << bits
        return ymin, ymax

    def test_column_capture_maps_nominal_division_symmetrically(self):
        """Exercise the RTL path: +/- one V/div must land at +/- one grid step."""
        from amaranth_future import fixed
        from tiliqua.raster import PSQ

        m = Module()
        dut = scope_capture.ColumnCapture()
        m.submodules.dut = dut

        async def testbench(ctx):
            ctx.set(dut.active, 1)
            ctx.set(dut.plot_x_lo, -600)
            ctx.set(dut.plot_x_hi, 600)
            ctx.set(dut.scale_x, 5)
            ctx.set(dut.x_offset, 0)
            ctx.set(dut.y_offset[0], 0)
            ctx.set(dut.visible[0], 1)
            for ch in range(1, 4):
                ctx.set(dut.visible[ch], 0)

            async def push(ramp, volts):
                flushes = []
                ctx.set(dut.ramp, fixed.Const(ramp, shape=PSQ))
                ctx.set(dut.audio[0], fixed.Const(volts / 8.192, shape=PSQ))
                ctx.set(dut.sample_valid, 1)
                await ctx.tick()
                ctx.set(dut.sample_valid, 0)
                for _ in range(10):
                    if ctx.get(dut.flush_valid):
                        flushes.append(ctx.get(dut.flush_word))
                    await ctx.tick()
                return flushes

            volts_per_div = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
            for scale, volts in enumerate(volts_per_div):
                ctx.set(dut.scale_y[0], scale)
                ctx.set(dut.clear, 1)
                await ctx.tick()
                ctx.set(dut.clear, 0)
                await ctx.tick()

                # A top-to-low ramp transition arms a clean sweep. The next
                # two positions occupy different columns, flushing the first.
                await push(0.99, 0.0)
                await push(0.00, 0.0)
                await push(0.01, 0.0)
                zero = await push(0.02, 0.0)
                self.assertTrue(zero)
                self.assertEqual(self._unpack_ch0(zero[-1]), (0, 0))

                await push(0.99, 0.0)
                await push(0.00, 0.0)
                await push(0.01, volts)
                positive = await push(0.02, volts)
                self.assertTrue(positive)
                self.assertEqual(self._unpack_ch0(positive[-1]), (-62, -62))

                await push(0.99, 0.0)
                await push(0.00, 0.0)
                await push(0.01, -volts)
                negative = await push(0.02, -volts)
                self.assertTrue(negative)
                self.assertEqual(self._unpack_ch0(negative[-1]), (62, 62))

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

    def test_monitor_ranges_map_and_clip_to_lane_window(self):
        """Monitor range indices must honor their voltage endpoints per channel."""
        from amaranth_future import fixed
        from tiliqua.raster import PSQ

        m = Module()
        dut = scope_capture.ColumnCapture()
        m.submodules.dut = dut

        async def testbench(ctx):
            ctx.set(dut.active, 1)
            ctx.set(dut.plot_x_lo, -600)
            ctx.set(dut.plot_x_hi, 600)
            ctx.set(dut.scale_x, 5)
            ctx.set(dut.x_offset, 0)
            ctx.set(dut.visible[0], 1)
            for ch in range(1, 4):
                ctx.set(dut.visible[ch], 0)

            async def push(ramp, volts):
                flushes = []
                ctx.set(dut.ramp, fixed.Const(ramp, shape=PSQ))
                ctx.set(dut.audio[0], fixed.Const(volts / 8.192, shape=PSQ))
                ctx.set(dut.sample_valid, 1)
                await ctx.tick()
                ctx.set(dut.sample_valid, 0)
                for _ in range(12):
                    if ctx.get(dut.flush_valid):
                        flushes.append(ctx.get(dut.flush_word))
                    await ctx.tick()
                return flushes

            # scale, vertical offset, input voltage, expected screen Y.
            # Inputs beyond either endpoint verify that a trace cannot escape
            # its lane and overwrite neighboring monitor statistics or traces.
            cases = (
                (6, 0, 5.0, -80),
                (6, 0, 8.0, -80),
                (6, 0, -8.0, 80),
                (7, 0, 8.0, -64),
                (7, 0, -8.0, 64),
                (8, 80, 0.0, 80),
                (8, 80, 8.0, -48),
                (8, 80, -2.0, 80),
                (9, 80, 5.0, -80),
                (9, 80, 8.0, -80),
                (9, 80, -1.0, 80),
            )
            for scale, offset, volts, expected_y in cases:
                ctx.set(dut.scale_y[0], scale)
                ctx.set(dut.y_offset[0], offset)
                ctx.set(dut.clear, 1)
                await ctx.tick()
                ctx.set(dut.clear, 0)
                await ctx.tick()

                await push(0.99, 0.0)
                await push(0.00, 0.0)
                await push(0.01, volts)
                flushed = await push(0.02, volts)
                self.assertTrue(flushed)
                self.assertEqual(
                    self._unpack_ch0(flushed[-1]),
                    (expected_y, expected_y),
                    f"scale {scale}, input {volts} V",
                )

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

    def test_column_capture_resumes_mid_sweep_after_invalidation(self):
        """A slow progressive trace must not wait for another ramp wrap."""
        from amaranth_future import fixed
        from tiliqua.raster import PSQ

        m = Module()
        dut = scope_capture.ColumnCapture()
        m.submodules.dut = dut

        async def testbench(ctx):
            ctx.set(dut.plot_x_lo, -600)
            ctx.set(dut.plot_x_hi, 600)
            ctx.set(dut.scale_x, 5)
            ctx.set(dut.x_offset, 0)
            ctx.set(dut.scale_y[0], 7)
            ctx.set(dut.y_offset[0], 0)
            ctx.set(dut.visible[0], 1)
            for ch in range(1, 4):
                ctx.set(dut.visible[ch], 0)

            async def push(ramp, volts):
                flushes = []
                ctx.set(dut.ramp, fixed.Const(ramp, shape=PSQ))
                ctx.set(dut.audio[0], fixed.Const(volts / 8.192, shape=PSQ))
                ctx.set(dut.sample_valid, 1)
                await ctx.tick()
                ctx.set(dut.sample_valid, 0)
                for _ in range(12):
                    if ctx.get(dut.flush_valid):
                        flushes.append(ctx.get(dut.flush_word))
                    await ctx.tick()
                return flushes

            # Model an overlay invalidation: capture drops while its back bank
            # is cleared, then rises again with the ramp still in mid-sweep.
            ctx.set(dut.clear, 1)
            await ctx.tick()
            ctx.set(dut.clear, 0)
            await ctx.tick()
            ctx.set(dut.active, 1)
            await ctx.tick()

            await push(0.25, 2.0)
            flushed = await push(0.27, 2.0)
            self.assertTrue(flushed)
            self.assertEqual(self._unpack_ch0(flushed[-1]), (-16, -16))

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

    @staticmethod
    def _packed_ch0(ymin, ymax):
        bits = scope_capture.ENVELOPE_COORD_BITS
        mask = (1 << bits) - 1
        # Channel 0 is {valid, ymin, ymax}; all other channels remain invalid.
        return 1 | ((ymin & mask) << 1) | ((ymax & mask) << (1 + bits))

    def test_completed_column_hits_same_logical_coordinate_in_all_rotations(self):
        """Exercise compact capture memory through the complete DVI pixel path."""
        m = Module()
        m.domains.sync = ClockDomain("sync")
        m.domains.dvi = ClockDomain("dvi")
        m.submodules.dut = dut = scope_overlay.ScopeTraceOverlay()

        column = 100
        logical_y = 7
        trace_color = 9
        trace_intensity = 12

        # Inverse mappings of ScopeTraceOverlay's physical-to-logical rotation.
        cases = (
            # 1280x720 landscape output.
            (1280, 720, Rotation.NORMAL, -632, 108, 367),
            (1280, 720, Rotation.INVERTED, -632, 1171, 352),
            (1280, 720, Rotation.LEFT, -352, 632, 108),
            (1280, 720, Rotation.RIGHT, -352, 647, 611),
            # Official 720x720 companion display geometry.
            (720, 720, Rotation.NORMAL, -352, 108, 367),
            (720, 720, Rotation.INVERTED, -352, 611, 352),
            (720, 720, Rotation.LEFT, -352, 352, 108),
            (720, 720, Rotation.RIGHT, -352, 367, 611),
        )

        async def testbench(ctx):
            ctx.set(dut.enable, 1)
            ctx.set(dut.h_active, 1280)
            ctx.set(dut.v_active, 720)
            ctx.set(dut.hue[0], trace_color)
            ctx.set(dut.intensity[0], trace_intensity)
            for ch in range(1, 4):
                ctx.set(dut.intensity[ch], 0)

            # Keep scanout in vertical blank while the initial hidden bank is
            # cleared and the completed sweep is atomically made visible.
            ctx.set(dut.i.y, -1)
            ctx.set(dut.i.de, 0)
            for _ in range(scope_capture.MAX_CAPTURE_COLS + 20):
                if ctx.get(dut.capture_active):
                    break
                await ctx.tick("sync")
            self.assertEqual(ctx.get(dut.capture_active), 1)

            ctx.set(dut.flush_valid, 1)
            ctx.set(dut.flush_col, column)
            ctx.set(dut.flush_word, self._packed_ch0(logical_y, logical_y))
            await ctx.tick("sync")
            ctx.set(dut.flush_valid, 0)
            ctx.set(dut.sweep_done, 1)
            await ctx.tick("sync")
            ctx.set(dut.sweep_done, 0)

            for _ in range(30):
                if ctx.get(dut.swap_done):
                    break
                await ctx.tick("sync")
            self.assertEqual(ctx.get(dut.swap_done), 1)

            for (h_active, v_active, rotation, plot_x_lo,
                 physical_x, physical_y) in cases:
                ctx.set(dut.h_active, h_active)
                ctx.set(dut.v_active, v_active)
                ctx.set(dut.rotation, rotation)
                ctx.set(dut.plot_x_lo, plot_x_lo)
                ctx.set(dut.i.x, physical_x)
                ctx.set(dut.i.y, physical_y)
                ctx.set(dut.i.de, 1)
                ctx.set(dut.i.pixel.color, 1)
                ctx.set(dut.i.pixel.intensity, 1)

                # Allow the coherent configuration CDC, synchronous memory,
                # bank mux, comparisons, and color pipeline all to settle.
                await ctx.tick("sync").repeat(10)
                hit = False
                for _ in range(24):
                    await ctx.tick("dvi")
                    hit |= (
                        ctx.get(dut.o.de) == 1 and
                        ctx.get(dut.o.pixel.color) == trace_color and
                        ctx.get(dut.o.pixel.intensity) == trace_intensity
                    )
                self.assertTrue(hit, f"trace miss for rotation {rotation.name}")

        sim = Simulator(m)
        sim.add_clock(1e-6, domain="sync")
        sim.add_clock(0.8e-6, domain="dvi")
        sim.add_testbench(testbench)
        sim.run()

    def test_scope_swap_waits_for_payload_before_acknowledging(self):
        """The request must be published after its bundled CDC payload.

        The request toggle and bank/generation payload cross independently.
        Holding the payload stable before publishing the request prevents CDC
        skew from making the displayed front bank alias the bank being cleared.
        """
        m = Module()
        m.domains.sync = ClockDomain("sync")
        m.domains.dvi = ClockDomain("dvi")
        m.submodules.dut = dut = scope_overlay.ScopeTraceOverlay()

        async def testbench(ctx):
            ctx.set(dut.enable, 1)
            ctx.set(dut.i.y, -1)
            ctx.set(dut.i.de, 0)

            for _ in range(scope_capture.MAX_CAPTURE_COLS + 20):
                if ctx.get(dut.capture_active):
                    break
                await ctx.tick("sync")
            self.assertEqual(ctx.get(dut.capture_active), 1)

            ctx.set(dut.sweep_done, 1)
            await ctx.tick("sync")
            ctx.set(dut.sweep_done, 0)

            # Even in vertical blank, the source-domain payload guard plus the
            # two request synchronizers must delay acknowledgement.
            dvi_clocks_to_ack = None
            for _ in range(20):
                await ctx.tick("dvi")
                if ctx.get(dut.swap_done):
                    dvi_clocks_to_ack = _ + 1
                    break
            self.assertIsNotNone(dvi_clocks_to_ack)
            self.assertGreaterEqual(dvi_clocks_to_ack, 6)

        sim = Simulator(m)
        sim.add_clock(1e-6, domain="sync")
        sim.add_clock(0.8e-6, domain="dvi")
        sim.add_testbench(testbench)
        sim.run()

    def test_pen_lift_flush_is_not_bridged(self):
        """Sweep wrap must not treat end-of-sweep Y as a steep edge into the new sweep."""
        from amaranth_future import fixed
        from tiliqua.raster import PSQ

        m = Module()
        dut = scope_capture.ColumnCapture()
        m.submodules.dut = dut

        plot_x_lo = 100

        async def sample(ctx, ramp_val, audio_val):
            flush = 0
            word = 0
            col = 0
            pen = 0
            ctx.set(dut.ramp, fixed.Const(ramp_val, shape=PSQ))
            ctx.set(dut.audio[0], fixed.Const(audio_val, shape=PSQ))
            ctx.set(dut.sample_valid, 1)
            await ctx.tick()
            ctx.set(dut.sample_valid, 0)
            for _ in range(10):
                if ctx.get(dut.flush_valid):
                    flush = 1
                    word = ctx.get(dut.flush_word)
                    col = ctx.get(dut.flush_col)
                if ctx.get(dut.sweep_done):
                    pen = 1
                await ctx.tick()
            return flush, col, word, pen

        async def testbench(ctx):
            ctx.set(dut.active, 1)
            ctx.set(dut.plot_x_lo, plot_x_lo)
            ctx.set(dut.plot_x_hi, 900)
            ctx.set(dut.scale_x, 6)
            ctx.set(dut.x_offset, plot_x_lo)
            ctx.set(dut.scale_y[0], 3)
            ctx.set(dut.y_offset[0], 360)
            ctx.set(dut.visible[0], 1)
            for ch in range(1, 4):
                ctx.set(dut.visible[ch], 0)

            ctx.set(dut.clear, 1)
            await ctx.tick()
            ctx.set(dut.clear, 0)
            await ctx.tick()

            # Leave the ramp top to arm a fresh sweep, then advance monotonically.
            await sample(ctx, 0.99, 0.0)
            await sample(ctx, 0.50, 0.0)

            for ramp in (0.52, 0.54, 0.56, 0.58):
                await sample(ctx, ramp, -0.5)
            steep_flush = await sample(ctx, 0.60, 0.5)

            flushes = []
            for ramp in (0.62, 0.64, 0.66, 0.68, 0.70, 0.72, 0.74, 0.76):
                flush, col, word, _pen = await sample(ctx, ramp, 0.5)
                if flush:
                    ymin, ymax = self._unpack_ch0(word)
                    flushes.append((col, ymin, ymax))

            self.assertTrue(flushes, "expected column flushes during sweep")
            self.assertTrue(steep_flush[0], "expected flush on steep edge")
            ymin, ymax = self._unpack_ch0(steep_flush[2])
            self.assertGreater(ymax - ymin, 10,
                               "steep edge should bridge the vertical jump")

            # Wrap the ramp: pen lifts and the sweep ends at the previous column.
            wrap_flush, _col, word, pen = await sample(ctx, -0.90, -0.5)
            self.assertEqual(pen, 1)
            self.assertTrue(wrap_flush, "expected one final flush on pen lift")
            ymin, ymax = self._unpack_ch0(word)
            self.assertLessEqual(ymax - ymin, 2,
                                 f"wrap flush must not bridge Y levels: ymin={ymin} ymax={ymax}")

            # New sweep starts without a spurious left-column flush.
            restart_flush, _, _, _ = await sample(ctx, 0.50, 0.5)
            self.assertFalse(restart_flush)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()
