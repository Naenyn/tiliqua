"""Exercise the real PHY through pixel/serializer reset and restart boundaries."""

from types import SimpleNamespace

import pytest
from amaranth import Module, ResetInserter, ResetSignal, Signal
from amaranth.lib.cdc import FFSynchronizer, ResetSynchronizer
from amaranth.sim import Simulator

from tiliqua.video import dvi


@pytest.mark.parametrize("release_phase", [0.1, 0.7, 1.3, 1.9, 2.5])
def test_serializer_clock_survives_synchronized_reset_and_restarts(monkeypatch, release_phase):
    pins = []

    def oddr(kind, **kwargs):
        assert kind == "ODDRX1F"
        pins.append((kwargs["i_D0"], kwargs["i_D1"]))
        return Module()

    monkeypatch.setattr(dvi, "Instance", oddr)
    monkeypatch.setattr(dvi.sim, "is_hw", lambda platform: True)

    class Platform:
        def request(self, name):
            return SimpleNamespace(**{
                lane: SimpleNamespace(o=Signal())
                for lane in ("d0", "d1", "d2", "ck")})

    m = Module()
    inhibit, pll_unlocked = Signal(init=1), Signal(init=1)
    pixel_reset = Signal(init=1)
    m.submodules.en = FFSynchronizer(inhibit, pixel_reset, o_domain="dvi", init=1)
    m.submodules.pll_reset = ResetSynchronizer(
        pll_unlocked | pixel_reset, domain="dvi5x")
    pll_reset = Signal()
    m.d.comb += pll_reset.eq(ResetSignal("dvi5x"))
    phy = dvi.DVIPHY(circular_shift=True)
    m.submodules.phy = ResetInserter({
        "dvi": pixel_reset})(phy.elaborate(Platform()))
    sim = Simulator(m)
    # Ratios match hardware. Release away from a clock edge, at five phases
    # across the serializer period; repeat while the encoder has live data.
    sim.add_clock(13.46e-6, domain="dvi")
    sim.add_clock(2.692e-6, domain="dvi5x")

    async def bench(ctx):
        for restart in range(3):
            ctx.set(inhibit, 1)
            ctx.set(pll_unlocked, 1)
            await ctx.tick("dvi").repeat(4)
            await ctx.delay(release_phase * 1e-6)
            ctx.set(inhibit, 0)
            ctx.set(pll_unlocked, 0)
            ctx.set(phy.i.de, 1)
            ctx.set(phy.i.r, restart * 79)
            ctx.set(phy.i.g, 255 - restart * 37)
            ctx.set(phy.i.b, 55)
            await ctx.tick("dvi").repeat(12)
            assert ctx.get(pll_reset) == 0
            bits = []
            for _ in range(100):
                await ctx.tick("dvi5x")
                bits.extend(ctx.get(pin) for pin in pins[3])
            # Every 10-bit clock word contains exactly five high samples and
            # five low samples. It must keep repeating after each restart.
            assert sum(bits[:10]) == 5
            assert bits == bits[:10] * 20
            assert sum(bits[i] != bits[(i + 1) % 10] for i in range(10)) == 2

    sim.add_testbench(bench)
    sim.run()
