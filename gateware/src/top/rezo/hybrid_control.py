"""Lean CPU control-plane footprint probe for the REZO family.

This keeps only the infrastructure needed by firmware-owned UI state:
VexiiRiscv, block-RAM execution, encoder CSR, and the CSR bridge. It
intentionally has no framebuffer, raster accelerators, or unrestricted flash
interface. Persistence will use a separate interface whose hardware address
range is limited to the active slot's option sectors.
"""

from amaranth import Array, Module, Signal, signed, unsigned
from amaranth.lib import wiring
from amaranth.lib.wiring import Component
from amaranth_soc import csr, wishbone
from amaranth_soc.csr.wishbone import WishboneCSRBridge
from luna_soc.gateware.core import blockram
from luna_soc.util import readbin

from tiliqua.periph import encoder
from vendor.vexiiriscv import VexiiRiscv

try:
    from .core_common import RezoCoreConstants
except ImportError:  # top_level_cli executes the REZO source directly.
    from core_common import RezoCoreConstants


class RezoFirmwareUIState:
    """Signals shared by firmware CSRs, the DSP, and the hardware renderer."""

    def __init__(self):
        self.enc_i = Signal()
        self.enc_q = Signal()
        self.button = Signal()

        self.levels = [Signal(signed(16), name=f"fw_level{n}")
                       for n in range(10)]
        self.band_enables = [Signal(init=1, name=f"fw_band_enable{n}")
                             for n in range(10)]
        self.band_frequencies = [Signal(
            unsigned(RezoCoreConstants.FREQ_INDEX_WIDTH),
            name=f"fw_band_frequency{n}")
                                 for n in range(10)]
        self.frequency_layout = Signal(2)
        self.frequency_layout_preview = Signal(2)
        self.frequency_preview = Signal(RezoCoreConstants.FREQ_INDEX_WIDTH)

        self.drive = Signal(16, init=8192)
        self.resonance = Signal(16, init=8192)
        self.feedback = Signal(16)
        self.filter_mode = Signal()
        self.filter_type = Signal(2)
        self.filter_cutoff = Signal(16, init=16384)
        self.filter_slope = Signal(16, init=16384)
        self.filter_width = Signal(16, init=12288)
        self.filter_cv_matrix = [Signal(signed(8), name=f"fw_filter_cv{n}")
                                 for n in range(15)]
        self.limit_knee = Signal(16, init=12288)
        self.limit_cap = Signal(16, init=28672)
        self.damp_mode = Signal(3)

        self.input_gains = [Signal(16, init=0xCCCC, name=f"fw_input_gain{n}")
                            for n in range(4)]
        self.input_modes = [Signal(name=f"fw_input_mode{n}") for n in range(4)]
        self.cv_targets = [Signal(3, name=f"fw_cv_target{n}") for n in range(4)]
        self.cv_depths = [Signal(signed(16), name=f"fw_cv_depth{n}")
                          for n in range(4)]
        self.bank_groups = [Signal(4, init=n % 4, name=f"fw_bank_group{n}")
                            for n in range(10)]
        self.feedback_sends = [Signal(init=1, name=f"fw_feedback_send{n}")
                               for n in range(10)]
        self.output_sends = [Signal(5, name=f"fw_output_send{n}")
                             for n in range(20)]

        self.selected = Signal(7)
        self.page = Signal(3)
        self.preset = Signal(3)
        self.palette = Signal(3)
        self.editing = Signal()

        self.save_default_available = Signal(init=1)
        self.save_default_busy = Signal()
        self.save_default_status = Signal(2)


class RezoUIControlPeripheral(Component):
    """Firmware-owned REZO UI state.

    Firmware is the sole owner of this state, so hardware never needs a wide
    readable register file. A single write-only command port updates both
    scalar and indexed values. This keeps the CPU/renderer boundary compact
    and avoids a large CSR read mux on an already-congested device.
    """

    class CommandReg(csr.Register, access="w"):
        kind: csr.Field(csr.action.W, unsigned(5))
        index: csr.Field(csr.action.W, unsigned(5))
        value: csr.Field(csr.action.W, unsigned(16))

    def __init__(self, ui):
        self.ui = ui
        regs = csr.Builder(addr_width=8, data_width=8)
        self._command = regs.add("command", self.CommandReg(), offset=0x00)
        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__({
            "bus": wiring.In(csr.Signature(
                addr_width=regs.addr_width, data_width=regs.data_width)),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        command = self._command
        kind = command.f.kind.w_data
        index = command.f.index.w_data
        value = command.f.value.w_data
        with m.Switch(kind):
            with m.Case(0):
                with m.If((index < 10) & command.element.w_stb):
                    m.d.sync += Array(self.ui.band_enables)[index].eq(value[0])
            with m.Case(1):
                with m.If((index < 10) & command.element.w_stb):
                    m.d.sync += Array(self.ui.band_frequencies)[index].eq(
                        value[:RezoCoreConstants.FREQ_INDEX_WIDTH])
            with m.Case(2):
                with m.If((index < 4) & command.element.w_stb):
                    m.d.sync += Array(self.ui.input_gains)[index].eq(value)
            with m.Case(3):
                with m.If((index < 4) & command.element.w_stb):
                    m.d.sync += Array(self.ui.input_modes)[index].eq(value[0])
            with m.Case(4):
                with m.If((index < 4) & command.element.w_stb):
                    m.d.sync += Array(self.ui.cv_targets)[index].eq(value[:3])
            with m.Case(5):
                with m.If((index < 4) & command.element.w_stb):
                    m.d.sync += Array(self.ui.cv_depths)[index].eq(value)
            with m.Case(6):
                with m.If((index < 10) & command.element.w_stb):
                    m.d.sync += Array(self.ui.bank_groups)[index].eq(value[:4])
            with m.Case(7):
                with m.If((index < 10) & command.element.w_stb):
                    m.d.sync += Array(self.ui.feedback_sends)[index].eq(value[0])
            with m.Case(8):
                with m.If((index < 15) & command.element.w_stb):
                    m.d.sync += Array(self.ui.filter_cv_matrix)[index].eq(
                        value[:8])
            with m.Case(9):
                with m.If((index < 20) & command.element.w_stb):
                    m.d.sync += Array(self.ui.output_sends)[index].eq(value[:5])
            with m.Case(10):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.page.eq(value[:3])
            with m.Case(11):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.selected.eq(value[:7])
            with m.Case(12):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.preset.eq(value[:3])
            with m.Case(13):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.palette.eq(value[:3])
            with m.Case(14):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.editing.eq(value[0])
            with m.Case(15):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.drive.eq(value)
            with m.Case(16):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.resonance.eq(value)
            with m.Case(17):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.feedback.eq(value)
            with m.Case(18):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.filter_mode.eq(value[0])
            with m.Case(19):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.filter_type.eq(value[:2])
            with m.Case(20):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.damp_mode.eq(value[:3])
            with m.Case(21):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.limit_knee.eq(value)
            with m.Case(22):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.limit_cap.eq(value)
            with m.Case(23):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.filter_cutoff.eq(value)
            with m.Case(24):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.filter_slope.eq(value)
            with m.Case(25):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.filter_width.eq(value)
            with m.Case(26):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.frequency_layout.eq(value[:2])
            with m.Case(27):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.frequency_layout_preview.eq(value[:2])
            with m.Case(28):
                with m.If(command.element.w_stb):
                    m.d.sync += self.ui.frequency_preview.eq(
                        value[:RezoCoreConstants.FREQ_INDEX_WIDTH])
            with m.Case(29):
                with m.If((index < 10) & command.element.w_stb):
                    m.d.sync += Array(self.ui.levels)[index].eq(value)
            with m.Case(30):
                with m.If(command.element.w_stb):
                    m.d.sync += [
                        self.ui.save_default_available.eq(value[0]),
                        self.ui.save_default_busy.eq(value[1]),
                        self.ui.save_default_status.eq(value[2:4]),
                    ]

        return m


class RezoHybridControlPlane(Component):
    """Minimal firmware control plane, without video or audio ownership."""

    MAINRAM_BASE = 0x00000000
    MAINRAM_SIZE = 0x4000
    CODE_SIZE = 0x2000
    DATA_BASE = CODE_SIZE
    DATA_SIZE = 0x0800
    CSR_BASE = 0xF0000000

    ENCODER_BASE = 0x600
    REZO_UI_BASE = 0x1000

    def __init__(self, clock_settings, *, firmware_bin_path):
        super().__init__({})
        self.clock_settings = clock_settings
        self.firmware_bin_path = firmware_bin_path

        self.cpu = VexiiRiscv(
            regions=[
                VexiiRiscv.MemoryRegion(
                    base=self.MAINRAM_BASE, size=self.MAINRAM_SIZE,
                    cacheable=True, executable=True),
                VexiiRiscv.MemoryRegion(
                    base=self.CSR_BASE, size=0x10000,
                    cacheable=False, executable=False),
            ],
            variant="rezo_control",
            reset_addr=self.MAINRAM_BASE,
        )

        self.wb_arbiter = wishbone.Arbiter(
            addr_width=30, data_width=32, granularity=8,
            features={"cti", "bte", "err"})
        self.wb_decoder = wishbone.Decoder(
            addr_width=30, data_width=32, granularity=8,
            alignment=0, features={"cti", "bte", "err"})

        # Keep immutable firmware and mutable stack/state in separate memories.
        # The control firmware occupies less than 8 KiB and needs no writable
        # globals. A dedicated 2 KiB data RAM is ample for its bounded stack.
        # This uses five ECP5 block-RAM banks instead of eight for a monolithic
        # 16 KiB memory, materially reducing placement congestion.
        self.mainram = blockram.Peripheral(
            size=self.CODE_SIZE, writable=False, name="code")
        self.wb_decoder.add(
            self.mainram.bus, addr=self.MAINRAM_BASE, name="code")
        self.dataram = blockram.Peripheral(
            size=self.DATA_SIZE, name="data")
        self.wb_decoder.add(
            self.dataram.bus, addr=self.DATA_BASE, name="data")

        self.csr_decoder = csr.Decoder(addr_width=28, data_width=8)
        self.encoder0 = encoder.Peripheral()
        self.csr_decoder.add(
            self.encoder0.bus, addr=self.ENCODER_BASE, name="encoder0")
        self.ui = RezoFirmwareUIState()
        self.rezo_ui = RezoUIControlPeripheral(self.ui)
        self.csr_decoder.add(
            self.rezo_ui.bus, addr=self.REZO_UI_BASE, name="rezo_ui")
        self.wb_to_csr = WishboneCSRBridge(
            self.csr_decoder.bus, data_width=32)
        self.wb_decoder.add(
            self.wb_to_csr.wb_bus, addr=self.CSR_BASE,
            sparse=False, name="wb_to_csr")

    def elaborate(self, platform):
        m = Module()

        self.mainram.init = readbin.get_mem_data(
            self.firmware_bin_path, data_width=32, endianness="little")
        assert self.mainram.init

        m.submodules.wb_arbiter = self.wb_arbiter
        m.submodules.wb_decoder = self.wb_decoder
        wiring.connect(m, self.wb_arbiter.bus, self.wb_decoder.bus)

        m.submodules.cpu = self.cpu
        self.wb_arbiter.add(self.cpu.ibus)
        self.wb_arbiter.add(self.cpu.dbus)
        m.d.comb += self.cpu.irq_external.eq(0)

        m.submodules.mainram = self.mainram
        m.submodules.dataram = self.dataram
        m.submodules.csr_decoder = self.csr_decoder
        m.submodules.wb_to_csr = self.wb_to_csr
        m.submodules.encoder0 = self.encoder0
        m.submodules.rezo_ui = self.rezo_ui

        return m
