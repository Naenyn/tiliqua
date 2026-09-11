"""Exercise the real opt-in decoder construction without a black-box CPU."""
from types import SimpleNamespace
import pytest
from amaranth import Module
from amaranth.lib.wiring import Component, flipped
from amaranth.sim import Simulator
from amaranth_soc import csr, wishbone
from amaranth_soc.memory import MemoryMap
from tiliqua.tiliqua_soc import TiliquaSoc


@pytest.mark.parametrize("name,base", [("mainram",0), ("spiflash_periph",0x10000000),
                                      ("psram_periph",0x20000000)])
@pytest.mark.parametrize("write", [False, True])
def test_split_decoders_keep_memory_bursts_independent_of_csr_reads(name, base, write):
    def memory(name):
        bus = flipped(wishbone.Interface(addr_width=10, data_width=32, granularity=8,
                                 features={"cti", "bte", "err"}))
        bus.memory_map = MemoryMap(addr_width=12, data_width=8)
        bus.memory_map.add_resource(Component({}), name=name, size=4096)
        return SimpleNamespace(bus=bus)

    soc = SimpleNamespace(
        isolate_cpu_peripherals=True,
        csr_decoder=csr.Decoder(addr_width=28, data_width=8),
        wb_decoder=wishbone.Decoder(addr_width=30, data_width=32, granularity=8,
                                   features={"cti", "bte", "err"}),
        mainram=memory("ram"), mainram_base=0,
        spiflash_periph=memory("flash"), spiflash_base=0x10000000,
        psram_periph=memory("psram"), psram_base=0x20000000,
        csr_base=0xf0000000)
    csr_bus = flipped(csr.Interface(addr_width=2, data_width=8))
    csr_bus.memory_map = MemoryMap(addr_width=2, data_width=8)
    csr_bus.memory_map.add_resource(Component({}), name="test", size=4)
    soc.csr_decoder.add(csr_bus, addr=0x1100, name="display")
    for peripheral, address, region_name in [(soc.mainram, 0, "ram"),
            (soc.spiflash_periph, 0x10000000, "flash"),
            (soc.psram_periph, 0x20000000, "psram")]:
        soc.wb_decoder.add(peripheral.bus, addr=address, name=region_name)
    TiliquaSoc.finalize_csr_bridge(soc)
    # Software introspection must still see the peripheral's original address.
    resources = list(soc.wb_decoder.bus.memory_map.all_resources())
    assert any(r.start == 0xf0001100 for r in resources)
    assert not any(r.start >= 0xf0000000
                   for r in soc.memory_decoder.bus.memory_map.all_resources())

    m = Module()
    m.submodules.memory_decoder = soc.memory_decoder
    m.submodules.peripheral_decoder = soc.peripheral_decoder
    m.submodules.csr_decoder = soc.csr_decoder
    m.submodules.bridge = soc.wb_to_csr
    # CSR reads are synchronous, as with the production register bridge.
    m.d.sync += csr_bus.r_data.eq(0x5a)
    sim = Simulator(m)
    sim.add_clock(1e-6)

    async def bench(ctx):
        mem, io = soc.memory_decoder.bus, soc.peripheral_decoder.bus
        target = getattr(soc,name).bus
        ctx.set(io.adr, 0xf0001100 // 4)
        ctx.set(io.cyc, 1); ctx.set(io.stb, 1); ctx.set(io.sel, 15)
        ctx.set(mem.cyc, 1); ctx.set(mem.stb, 1); ctx.set(mem.sel, 15)
        ctx.set(mem.we, write)
        complete = False
        for beat in range(16):
            ctx.set(mem.adr, base // 4 + beat)
            ctx.set(mem.cti, 7 if beat == 15 else 2)
            ctx.set(mem.dat_w, 0x200 + beat)
            ctx.set(target.ack, 1)
            ctx.set(target.dat_r, 0x100 + beat)
            assert ctx.get(target.adr) == beat
            assert ctx.get(target.cti) == (7 if beat == 15 else 2)
            assert ctx.get(target.we) == write
            assert ctx.get(target.dat_w) == 0x200 + beat
            assert ctx.get(target.sel) == 15
            assert ctx.get(mem.ack) == 1
            assert ctx.get(mem.dat_r) == 0x100 + beat
            for other in (soc.mainram.bus, soc.spiflash_periph.bus, soc.psram_periph.bus):
                if other is not target: assert ctx.get(other.cyc) == 0
            if ctx.get(io.ack):
                assert ctx.get(io.dat_r) == 0x5a5a5a5a
                complete = True
                ctx.set(io.cyc, 0); ctx.set(io.stb, 0)
            await ctx.tick()
        assert complete
        ctx.set(target.ack, 0)
        assert ctx.get(mem.ack) == 0
        ctx.set(target.err, 1)
        assert ctx.get(mem.err) == 1
        assert ctx.get(io.err) == 0

    sim.add_testbench(bench)
    sim.run()
