"""Opt-in diagnostic CSR adapter. Retains one complete score frame until start.

The baseline detector remains authoritative. This adapter never controls DACs.
Single-buffer/request-driven export is for hardware validation, not the final
four-channel 20-Hz scheduler or production double-buffered handoff.
"""
from amaranth import Array, Cat, Const, Module, Mux, Signal, signed, unsigned
from amaranth.lib import wiring
from amaranth.lib.wiring import In
from amaranth.lib.memory import Memory
from amaranth_soc import csr
from .nsdf_frontend import NsdfFrontend
from .nsdf_coefficients import coefficients
from .nsdf_source_energy import NsdfSourceEnergy


class Peripheral(wiring.Component):
    class Read(csr.Register,access='r'):
        value:csr.Field(csr.action.R,unsigned(32))
    class Write(csr.Register,access='w'):
        value:csr.Field(csr.action.W,unsigned(32))
    class Address(csr.Register,access='rw'):
        value:csr.Field(csr.action.RW,unsigned(11))

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
        self.source_sequence=regs.add('source_sequence',self.Read(),offset=36)
        self.source_sum=regs.add('source_sum',self.Read(),offset=40)
        self.source_squares_low=regs.add('source_squares_low',self.Read(),offset=44)
        self.source_squares_high=regs.add('source_squares_high',self.Read(),offset=48)
        self.source_samples=regs.add('source_samples',self.Read(),offset=52)
        self.source_status=regs.add('source_status',self.Read(),offset=56)
        self.frame_native_end=regs.add('frame_native_end',self.Read(),offset=60)
        self.bridge=csr.Bridge(regs.as_memory_map())
        super().__init__({'input_valid':In(1),**{f'sample{i}':In(signed(16)) for i in range(4)},
            'bus':In(csr.Signature(addr_width=regs.addr_width,data_width=regs.data_width))})
        self.bus.memory_map=self.bridge.bus.memory_map

    def elaborate(self,platform):
        m=Module();m.submodules.bridge=self.bridge
        wiring.connect(m,wiring.flipped(self.bus),self.bridge.bus)
        m.submodules.frontend=d=NsdfFrontend(coefficients())
        m.submodules.source_energy=e=NsdfSourceEnergy()
        m.submodules.scores=memory=Memory(shape=signed(22),depth=1024,init=[])
        write=memory.write_port();read=memory.read_port()
        completed=Signal();count=Signal(10);dropped=Signal()
        command=self.control.element.w_data;strobe=self.control.element.w_stb
        start=Signal()
        address=self.address.f.value.data
        m.d.comb += [start.eq(strobe & command[0] & d.ready),d.start.eq(start),
            d.cancel.eq(strobe & command[1]),d.low_bank.eq(command[2]),d.channel.eq(command[3:5]),
            d.input_valid.eq(self.input_valid),d.score_ready.eq(1),
            write.en.eq(d.score_valid),write.addr.eq(d.lag),write.data.eq(d.score),
            read.addr.eq(address[:10]),read.en.eq(1),
            d.inspect.eq(address[10] & completed & ~d.fault & ~d.overrun & ~dropped),
            d.inspect_address.eq(address[:10]),
            # Address bit 10 selects the immutable, centered/scaled frame used
            # for these scores. Samples are sign extended just like scores.
            self.data.f.value.r_data.eq(Mux(address[10],d.inspect_sample,read.data)),
            self.sequence.f.value.r_data.eq(d.frame_sequence),
            self.energy_low.f.value.r_data.eq(d.frame_energy[:32]),
            self.energy_high.f.value.r_data.eq(d.frame_energy[32:]),
            # bits 0..9 state/metadata; bits 16..25 number of completed scores.
            self.status.f.value.r_data.eq(Cat(d.busy,completed,d.fault,d.overrun,dropped,
                d.frame_low_bank,d.frame_channel,d.frame_scaled,d.frame_clipped,
                Const(0,6),count)),
            self.fill.f.value.r_data.eq(Cat(d.native_filled,Const(0,5),d.low_filled)),
            self.identity.f.value.r_data.eq(0x4e534407),e.input_valid.eq(self.input_valid),
            self.frame_native_end.f.value.r_data.eq(d.frame_native_end)]
        for ch in range(4):
            m.d.comb += [getattr(d,f'sample{ch}').eq(getattr(self,f'sample{ch}')),
                         getattr(e,f'sample{ch}').eq(getattr(self,f'sample{ch}'))]
        # Freeze source moments alongside the request. Slow serial export must
        # never combine live moments with an older score frame. Source sequence
        # is in native sample groups, not the low bank's decimated sequence.
        source_sequence=Signal(32);source_sum=Signal(signed(31));source_squares=Signal(45)
        source_samples=Signal(15);source_status=Signal(4)
        m.d.comb += [self.source_sequence.f.value.r_data.eq(source_sequence),
            self.source_sum.f.value.r_data.eq(source_sum),
            self.source_squares_low.f.value.r_data.eq(source_squares[:32]),
            self.source_squares_high.f.value.r_data.eq(source_squares[32:]),
            self.source_samples.f.value.r_data.eq(source_samples),
            self.source_status.f.value.r_data.eq(source_status)]
        with m.If(start):
            m.d.sync += [source_sequence.eq(e.sequence),source_samples.eq(e.samples),
                source_sum.eq(Array(getattr(e,f'sum{i}') for i in range(4))[command[3:5]]),
                source_squares.eq(Array(getattr(e,f'squares{i}') for i in range(4))[command[3:5]]),
                source_status.eq(Cat(e.valid,e.overrun,command[3:5]))]
        with m.If(self.input_valid & ~d.input_ready):m.d.sync += dropped.eq(1)
        with m.If(start):m.d.sync += [completed.eq(0),count.eq(0)]
        with m.If(d.score_valid):m.d.sync += count.eq(count+1)
        with m.If(d.done):m.d.sync += completed.eq(1)
        return m
