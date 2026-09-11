"""Compare actual serializer DDR inputs; only the physical DDR cell is mocked."""
from types import SimpleNamespace
from amaranth import Module, Signal
from amaranth.sim import Simulator
from tiliqua.video import dvi


def test_circular_serializer_matches_legacy_every_output_pair(monkeypatch):
    pairs=[]
    def oddr(kind, **kwargs):
        assert kind == "ODDRX1F"
        pairs.append((kwargs["i_D0"],kwargs["i_D1"]))
        return Module()
    monkeypatch.setattr(dvi,"Instance",oddr)
    monkeypatch.setattr(dvi.sim,"is_hw",lambda platform: True)
    class Platform:
        def request(self,name):
            return SimpleNamespace(**{key:SimpleNamespace(o=Signal()) for key in ["d0","d1","d2","ck"]})
    old=dvi.DVIPHY(); new=dvi.DVIPHY(circular_shift=True)
    m=Module(); m.submodules.old=old.elaborate(Platform()); m.submodules.new=new.elaborate(Platform())
    sim=Simulator(m); sim.add_clock(1e-6,domain="dvi5x");sim.add_clock(5e-6,domain="dvi")
    async def bench(ctx):
        for pixel in range(1024):
            for dut in [old,new]:
                ctx.set(dut.i.r,pixel&255);ctx.set(dut.i.g,(pixel*71)&255);ctx.set(dut.i.b,(pixel*137)&255)
                ctx.set(dut.i.de,pixel%11!=0);ctx.set(dut.i.hsync,(pixel>>2)&1);ctx.set(dut.i.vsync,(pixel>>3)&1)
            for _ in range(5):
                await ctx.tick("dvi5x")
                for channel in range(3):
                    assert tuple(ctx.get(v) for v in pairs[channel]) == tuple(ctx.get(v) for v in pairs[channel+3])
    sim.add_testbench(bench);sim.run()
