import random

from amaranth import signed
from amaranth.sim import Simulator
from tiliqua.raster.native_extrema import NativeExtrema


def test_extrema_windows_are_atomic_and_lossless():
    dut = NativeExtrema(shape=signed(18))

    async def bench(ctx):
        rng = random.Random(19)
        window = []
        held = None
        for cycle in range(1000):
            tick = cycle % 7 == 0 or cycle % 11 == 0
            snapshot = cycle % 17 == 0 or cycle % 17 == 1
            # Include a one-native-sample pulse and signed endpoint values.
            values = [rng.randrange(-131072, 131072) for _ in range(4)]
            if cycle == 7:
                values = [-131072, 131071, -1, 1]
            ctx.set(dut.tick, tick)
            ctx.set(dut.snapshot, snapshot)
            for ch in range(4):
                ctx.set(dut.sample[ch], values[ch])
            if tick:
                window.append(values)
            await ctx.tick()
            if snapshot:
                assert ctx.get(dut.valid) == bool(window)
                if window:
                    held = ([min(v[ch] for v in window) for ch in range(4)],
                            [max(v[ch] for v in window) for ch in range(4)])
                window = []
            if held is not None:
                assert [ctx.get(v) for v in dut.low] == held[0]
                assert [ctx.get(v) for v in dut.high] == held[1]

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()


def test_native_extrema_csr_snapshot_sign_and_hold():
    from amaranth import Module
    from amaranth_soc import csr
    from amaranth_soc.csr import wishbone as csr_wishbone
    from tiliqua.raster.digital_scope import DigitalScopePeripheral
    from tiliqua.test import csr as csr_util

    dut = DigitalScopePeripheral(fs=1536000, native_fs=192000)
    decoder = csr.Decoder(addr_width=28, data_width=8)
    decoder.add(dut.bus, addr=0, name="scope")
    bridge = csr_wishbone.WishboneCSRBridge(decoder.bus, data_width=32)
    m = Module()
    m.submodules += [dut, decoder, bridge]

    async def bench(ctx):
        async def sample(values):
            for ch, value in enumerate(values):
                ctx.set(dut.native_i.payload[ch].as_value(), value)
            ctx.set(dut.native_i.valid, 1)
            await ctx.tick()
            ctx.set(dut.native_i.valid, 0)
            # Invalid source payload must not affect the captured extrema.
            for ch in range(4):
                ctx.set(dut.native_i.payload[ch].as_value(), 777)
            await ctx.tick().repeat(8)

        async def snapshot():
            await csr_util.wb_csr_w_dict(ctx, dut.bus, bridge.wb_bus,
                                         "monitor_snapshot", {"snapshot": 1})

        async def check(values):
            for kind in ("low", "high"):
                for ch, value in enumerate(values):
                    actual = await csr_util.wb_csr_r(
                        ctx, dut.bus, bridge.wb_bus, f"monitor_{kind}{ch}", "value")
                    assert actual == value & 0xffffffff

        values = [-12345, 12345, -1, 1]
        await sample(values)
        await snapshot()
        assert (await csr_util.wb_csr_r(
            ctx, dut.bus, bridge.wb_bus, "monitor_status")) & 0x100
        await sample([0] * 4)
        await check(values)
        await snapshot()
        await check([0] * 4)
        await snapshot()
        assert not (await csr_util.wb_csr_r(
            ctx, dut.bus, bridge.wb_bus, "monitor_status")) & 0x100

        # Preserve every frame of a burst from the asynchronous ADC crossing,
        # including interior extrema. Average native rate is not a guarantee
        # that input frames are evenly spaced in the system-clock domain.
        frames = [[0] * 4, [-32000, 31000, -1, 1],
                  [15000, -16000, 2, -3], [5] * 4]
        for values in frames:
            for ch, value in enumerate(values):
                ctx.set(dut.native_i.payload[ch].as_value(), value)
            ctx.set(dut.native_i.valid, 1)
            assert ctx.get(dut.native_i.ready)
            await ctx.tick()
        ctx.set(dut.native_i.valid, 0)
        await ctx.tick().repeat(100)
        await snapshot()
        for kind, reduce in (("low", min), ("high", max)):
            for ch in range(4):
                actual = await csr_util.wb_csr_r(
                    ctx, dut.bus, bridge.wb_bus, f"monitor_{kind}{ch}", "value")
                assert actual == reduce(frame[ch] for frame in frames) & 0xffffffff

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
