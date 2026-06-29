# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

import struct
import unittest

from amaranth import *
from amaranth.sim import *
from amaranth.lib import wiring

from tiliqua.test import wishbone, stream, csr as csr_util
from tiliqua.raster import persist, stroke, plot, blit, line, scope_capture
from tiliqua.video import framebuffer, modeline, palette

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


class ColumnCaptureTests(unittest.TestCase):

    def _unpack_ch0(self, word):
        ymin = word & 0xffff
        ymax = (word >> 16) & 0xffff
        if ymin >= 0x8000:
            ymin -= 0x10000
        if ymax >= 0x8000:
            ymax -= 0x10000
        return ymin, ymax

    def test_pen_lift_flush_is_not_bridged(self):
        """Sweep wrap must not treat end-of-sweep Y as a steep edge into the new sweep."""
        from amaranth_future import fixed
        from tiliqua.raster import PSQ

        m = Module()
        dut = scope_capture.ColumnCapture()
        m.submodules.dut = dut

        plot_x_lo = 100

        async def sample(ctx, ramp_val, audio_val):
            ctx.set(dut.ramp, fixed.Const(ramp_val, shape=PSQ))
            ctx.set(dut.audio[0], fixed.Const(audio_val, shape=PSQ))
            ctx.set(dut.sample_valid, 1)
            await ctx.delay(0.5e-6)
            flush = ctx.get(dut.flush_valid)
            word = ctx.get(dut.flush_word) if flush else 0
            col = ctx.get(dut.flush_col) if flush else 0
            pen = ctx.get(dut.dbg_pen_lift)
            await ctx.delay(0.5e-6)
            ctx.set(dut.sample_valid, 0)
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
