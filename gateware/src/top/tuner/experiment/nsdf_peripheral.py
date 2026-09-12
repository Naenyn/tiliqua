"""Opt-in diagnostic CSR adapter. Retains one complete score frame until start.

The baseline detector remains authoritative. This adapter never controls DACs.
Single-buffer/request-driven export is for hardware validation, not the final
four-channel 20-Hz scheduler or production double-buffered handoff.
"""
from amaranth import Cat, Const, Module, Signal, signed, unsigned
from amaranth.lib import wiring
from amaranth.lib.wiring import In
from amaranth.lib.memory import Memory
from amaranth_soc import csr
from .nsdf_frontend import NsdfFrontend
from .nsdf_coefficients import coefficients


class Peripheral(wiring.Component):
    class Read(csr.Register,access='r'):
        value:csr.Field(csr.action.R,unsigned(32))
    class Write(csr.Register,access='w'):
        value:csr.Field(csr.action.W,unsigned(32))
    class Address(csr.Register,access='rw'):
        value:csr.Field(csr.action.RW,unsigned(9))

    def __init__(self):
        regs=csr.Builder(addr_width=6,data_width=8)
        self.control=regs.add('control',self.Write(),offset=0)
        self.status=regs.add('status',self.Read(),offset=4)
        self.address=regs.add('address',self.Address(),offset=8)
        self.data=regs.add('data',self.Read(),offset=12)
        self.sequence=regs.add('sequence',self.Read(),offset=16)
        self.energy_low=regs.add('energy_low',self.Read(),offset=20)
        self.energy_high=regs.add('energy_high',self.Read(),offset=24)
        self.fill=regs.add('fill',self.Read(),offset=28)
        self.identity=regs.add('identity',self.Read(),offset=32)
        self.bridge=csr.Bridge(regs.as_memory_map())
        super().__init__({'input_valid':In(1),**{f'sample{i}':In(signed(16)) for i in range(4)},
            'bus':In(csr.Signature(addr_width=regs.addr_width,data_width=regs.data_width))})
        self.bus.memory_map=self.bridge.bus.memory_map

    def elaborate(self,platform):
        m=Module();m.submodules.bridge=self.bridge
        wiring.connect(m,wiring.flipped(self.bus),self.bridge.bus)
        m.submodules.frontend=d=NsdfFrontend(coefficients())
        m.submodules.scores=memory=Memory(shape=signed(22),depth=512,init=[])
        write=memory.write_port();read=memory.read_port()
        completed=Signal();count=Signal(10);dropped=Signal()
        command=self.control.element.w_data;strobe=self.control.element.w_stb
        start=Signal()
        m.d.comb += [start.eq(strobe & command[0] & d.ready),d.start.eq(start),
            d.cancel.eq(strobe & command[1]),d.low_bank.eq(command[2]),d.channel.eq(command[3:5]),
            d.input_valid.eq(self.input_valid),d.score_ready.eq(1),
            write.en.eq(d.score_valid),write.addr.eq(d.lag),write.data.eq(d.score),
            read.addr.eq(self.address.f.value.data),read.en.eq(1),
            self.data.f.value.r_data.eq(read.data),self.sequence.f.value.r_data.eq(d.frame_sequence),
            self.energy_low.f.value.r_data.eq(d.frame_energy[:32]),
            self.energy_high.f.value.r_data.eq(d.frame_energy[32:]),
            # bits 0..9 state/metadata; bits 16..25 number of completed scores.
            self.status.f.value.r_data.eq(Cat(d.busy,completed,d.fault,d.overrun,dropped,
                d.frame_low_bank,d.frame_channel,d.frame_scaled,d.frame_clipped,
                Const(0,6),count)),
            self.fill.f.value.r_data.eq(Cat(d.native_filled,Const(0,5),d.low_filled)),
            self.identity.f.value.r_data.eq(0x4e534401)]
        for ch in range(4):m.d.comb += getattr(d,f'sample{ch}').eq(getattr(self,f'sample{ch}'))
        with m.If(self.input_valid & ~d.input_ready):m.d.sync += dropped.eq(1)
        with m.If(start):m.d.sync += [completed.eq(0),count.eq(0)]
        with m.If(d.score_valid):m.d.sync += count.eq(count+1)
        with m.If(d.done):m.d.sync += completed.eq(1)
        return m
