# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

import unittest

from amaranth import *
from amaranth.lib import wiring
from amaranth.sim import *
from amaranth_soc import csr
from amaranth_soc.csr import wishbone

from tiliqua import test as test_util
from tiliqua.periph import eurorack_pmod, i2c
from vendor import i2c as vendor_i2c


class I2CTests(unittest.TestCase):

    def test_i2c_peripheral(self):

        m = Module()
        dut = i2c.Peripheral()
        i2c_stream = i2c.I2CStreamer(period_cyc=4)
        decoder = csr.Decoder(addr_width=28, data_width=8)
        decoder.add(dut.bus, addr=0, name="dut")
        bridge = wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
        wiring.connect(m, dut.i2c_stream, i2c_stream.control)
        m.submodules += [dut, decoder, bridge, i2c_stream]

        async def test_stimulus(ctx):

            async def csr_write(ctx, value, register, field=None):
                await test_util.csr.wb_csr_w(
                        ctx, dut.bus, bridge.wb_bus, value, register, field)

            async def csr_read(ctx, register, field=None):
                return await test_util.csr.wb_csr_r(
                        ctx, dut.bus, bridge.wb_bus, register, field)

            # set device address
            await csr_write(ctx, 0x55, "address")

            # enqueue 2x write ops
            await csr_write(ctx, 0x042, "transaction_reg")
            await csr_write(ctx, 0x013, "transaction_reg")

            # enqueue 1x read + last op
            await csr_write(ctx, 0x300, "transaction_reg")

            # 3 transactions are enqueued
            self.assertEqual(ctx.get(i2c_stream._transactions.level), 3)

            # busy flag should go high
            self.assertEqual(await csr_read(ctx, "status", "busy"), 1)

            await ctx.tick().repeat(500)

            await csr_read(ctx, "rx_data")

            await ctx.tick().repeat(200)

            # busy flag should go low
            self.assertEqual(await csr_read(ctx, "status", "busy"), 0)

            # all transactions drained.
            self.assertEqual(ctx.get(i2c_stream._transactions.level), 0)

        async def test_response(ctx):

            was_busy = False
            data_written = []
            while True:
                await ctx.tick()
                if ctx.get(i2c_stream.control.status.busy) and not was_busy:
                    was_busy = True
                if was_busy and not ctx.get(i2c_stream.control.status.busy):
                    break
                if ctx.get(i2c_stream.i2c.start):
                    print("i2c.start")
                if ctx.get(i2c_stream.i2c.write):
                    v = ctx.get(i2c_stream.i2c.data_i)
                    print("i2c.write", hex(v))
                    data_written.append(v)
                if ctx.get(i2c_stream.i2c.read):
                    print("i2c.read",  hex(ctx.get(i2c_stream.i2c.data_o)))
                if ctx.get(i2c_stream.i2c.stop):
                    print("i2c.stop")

            self.assertEqual(data_written, [0xaa, 0x42, 0x13, 0xab])

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(test_stimulus)
        sim.add_testbench(test_response, background=True)
        with sim.write_vcd(vcd_file=open("test_i2c_peripheral.vcd", "w")):
            sim.run()

    def test_i2c_master(self):

        m = Module()
        dut = eurorack_pmod.I2CMaster(audio_192=False)
        m.submodules += [dut]

        TICKS = 20000

        async def test_response(ctx):
            was_busy = False
            data_written = []
            ctx.set(dut.led[0], -10)
            ctx.set(dut.led[1], 10)
            for _ in range(TICKS):
                await ctx.tick()
                if ctx.get(dut.i2c_stream.i2c.start):
                    print("i2c.start")
                if ctx.get(dut.i2c_stream.i2c.write):
                    v = ctx.get(dut.i2c_stream.i2c.data_i)
                    print("i2c.write", hex(v))
                    data_written.append(v)
                if ctx.get(dut.i2c_stream.i2c.read):
                    print("i2c.read",  hex(ctx.get(dut.i2c_stream.i2c.data_o)))
                if ctx.get(dut.i2c_stream.i2c.stop):
                    print("i2c.stop")

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(test_response)
        with sim.write_vcd(vcd_file=open("test_i2c_peripheral.vcd", "w")):
            sim.run()

    def test_i2c_master_user_nvm_transactions(self):
        """REZO's lean NVM path reads and writes the writable reserved byte."""

        m = Module()
        dut = eurorack_pmod.I2CMaster(
            audio_192=False, with_user_nvm=True, i2c_period_cyc=8)
        m.submodules += dut

        async def eeprom_responder(ctx):
            # Release SDA while idle. Pull it low for every ACK bit and return
            # zero for read data; the synchronizer requires beginning at the
            # ACK/data setup state rather than waiting for the sample edge.
            ack_states = (
                "WRITE-ACK-SCL-L", "WRITE-ACK-SDA-H",
                "WRITE-ACK-SCL-H", "WRITE-ACK-SDA-N",
            )
            read_states = (
                "READ-DATA-SCL-L", "READ-DATA-SDA-H",
                "READ-DATA-SCL-H", "READ-DATA-SDA-N",
            )
            ctx.set(dut.pins.sda.i, 1)
            while True:
                pull_low = any(ctx.get(
                    dut.i2c_stream.i2c._fsm.ongoing(state))
                    for state in ack_states + read_states)
                ctx.set(dut.pins.sda.i, 0 if pull_low else 1)
                await ctx.tick()

        async def testbench(ctx):
            data_written = []
            write_requested = False
            for _ in range(100_000):
                if ctx.get(dut.i2c_stream.i2c.write):
                    data_written.append(ctx.get(dut.i2c_stream.i2c.data_i))

                if ctx.get(dut.nvm_valid) and not write_requested:
                    self.assertEqual(ctx.get(dut.nvm_value), 0)
                    ctx.set(dut.nvm_write_value, 2)
                    ctx.set(dut.nvm_write_request, 1)
                    write_requested = True

                if ctx.get(dut.nvm_write_done):
                    ctx.set(dut.nvm_write_request, 0)
                    break
                await ctx.tick()
            else:
                self.fail("NVM transaction did not complete")

            def contains(sequence):
                width = len(sequence)
                return any(data_written[ix:ix + width] == sequence
                           for ix in range(len(data_written) - width + 1))

            # Device address bytes are 0xa4/0xa5 for 7-bit address 0x52.
            self.assertTrue(contains([0xa4, 0x60, 0xa5]))
            self.assertTrue(contains([0xa4, 0x60, 0x02]))

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.add_testbench(eeprom_responder, background=True)
        sim.run()

    def test_i2c_luna_register_interface(self):

        m = Module()
        dut = vendor_i2c.I2CRegisterInterface(period_cyc=4, max_data_bytes=16)
        m.submodules += [dut]

        async def testbench(ctx):
            ctx.set(dut.dev_address,   0x5)
            ctx.set(dut.reg_address,   0x42)
            ctx.set(dut.size,          4)
            ctx.set(dut.write_request, 1)
            ctx.set(dut.write_data[-32:], 0xDEADBEEF)
            await ctx.tick()
            ctx.set(dut.write_request, 0)
            data_written = []
            print()
            while ctx.get(dut.busy):
                if ctx.get(dut.i2c.start):
                    print("i2c.start")
                if ctx.get(dut.i2c.write):
                    v = ctx.get(dut.i2c.data_i)
                    print("i2c.write", hex(v))
                    data_written.append(v)
                if ctx.get(dut.i2c.read):
                    print("i2c.read",  hex(ctx.get(dut.i2c.data_o)))
                if ctx.get(dut.i2c.stop):
                    print("i2c.stop")
                await ctx.tick()

            self.assertEqual(data_written, [0xa, 0x42, 0xde, 0xad, 0xbe, 0xef])

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_i2c_luna_register_interface.vcd", "w")):
            sim.run()
