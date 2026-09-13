# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Low-cost streaming measurements and reference tone for the tuner."""

import math

from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.memory import Memory
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr

from . import ASQ
from .period_verifier import PeriodVerifier
from .calibration_output import CalibrationOutput
from .cv_snapshot import CVSnapshot


class ReferenceOscillator(wiring.Component):
    """Backpressure-aware, fixed-amplitude sine reference oscillator."""

    def __init__(self, *, table_depth=1024, peak_counts=2000):
        if table_depth & (table_depth - 1):
            raise ValueError("table_depth must be a power of two")
        self.table_depth = table_depth
        self.peak_counts = peak_counts
        super().__init__({
            "advance": In(1),
            "enable": In(1),
            "increment": In(32),
            "o": Out(ASQ),
        })

    def elaborate(self, platform):
        m = Module()
        address_bits = (self.table_depth - 1).bit_length()
        sine_init = [round(self.peak_counts * math.sin(
            2 * math.pi * n / self.table_depth))
            for n in range(self.table_depth)]
        sine_mem = Memory(
            shape=signed(ASQ.as_shape().width), depth=self.table_depth,
            init=sine_init, attrs={"ram_style": "block"})
        sine_r = sine_mem.read_port(domain="sync")
        m.submodules.sine = sine_mem
        phase = Signal(32)
        m.d.comb += [
            sine_r.addr.eq(phase[-address_bits:]),
            sine_r.en.eq(1),
            self.o.as_value().eq(sine_r.data),
        ]
        with m.If(~self.enable):
            m.d.sync += phase.eq(0)
        with m.Elif(self.advance):
            m.d.sync += phase.eq(phase + self.increment)
        return m


class TunerPeripheral(wiring.Component):
    """Measure pitch period and voltage level on one selected audio input.

    Pitch measurement deliberately uses a hysteretic positive crossing detector
    in this first proof of concept.  Rather than rounding each individual period,
    it counts complete cycles over a minimum observation interval.  This keeps
    the implementation small while giving oscillator waveforms good resolution.

    Level snapshots are independent of pitch snapshots. ``mean_square`` is in
    squared calibrated ADC counts; firmware uses the PMOD counts-per-volt value
    to convert its square root to Vrms.
    """

    class Control(csr.Register, access="rw"):
        channel: csr.Field(csr.action.RW, unsigned(2))

    class Info(csr.Register, access="r"):
        sample_rate: csr.Field(csr.action.R, unsigned(32))

    class PitchSequence(csr.Register, access="r"):
        sequence: csr.Field(csr.action.R, unsigned(16))

    class PeriodSamples(csr.Register, access="r"):
        samples: csr.Field(csr.action.R, unsigned(32))

    class PeriodCycles(csr.Register, access="r"):
        cycles: csr.Field(csr.action.R, unsigned(16))

    class PitchAge(csr.Register, access="r"):
        samples: csr.Field(csr.action.R, unsigned(32))

    class ReferenceControl(csr.Register, access="rw"):
        enable: csr.Field(csr.action.RW, unsigned(1))

    class ReferenceIncrement(csr.Register, access="rw"):
        value: csr.Field(csr.action.RW, unsigned(32))

    class LevelSequence(csr.Register, access="r"):
        sequence: csr.Field(csr.action.R, unsigned(16))

    class MeanSquare(csr.Register, access="r"):
        # ASQ samples are 16-bit. Averaging the square_sum back down by the
        # window length leaves at most a 32-bit squared-sample value. Keeping
        # this register native-width also avoids a non-atomic 64-bit MMIO read
        # on the 32-bit CPU.
        value: csr.Field(csr.action.R, unsigned(32))

    class SignedLevel(csr.Register, access="r"):
        value: csr.Field(csr.action.R, unsigned(32))

    class VerifyRequest(csr.Register, access="w"):
        lag_q8: csr.Field(csr.action.W, unsigned(24))

    class VerifyStatus(csr.Register, access="r"):
        busy: csr.Field(csr.action.R, unsigned(1))
        done: csr.Field(csr.action.R, unsigned(1))
        factor: csr.Field(csr.action.R, unsigned(3))

    class VerifyLag(csr.Register, access="r"):
        lag_q8: csr.Field(csr.action.R, unsigned(24))

    class VerifyInfo(csr.Register, access="r"):
        decimation: csr.Field(csr.action.R, unsigned(8))

    class VerifyCapture(csr.Register, access="rw"):
        mode: csr.Field(csr.action.RW, unsigned(2))

    class CaptureControl(csr.Register, access="rw"):
        address: csr.Field(csr.action.RW, unsigned(11))
        arm: csr.Field(csr.action.RW, unsigned(1))

    class CaptureData(csr.Register, access="r"):
        sample: csr.Field(csr.action.R, unsigned(16))
        frozen: csr.Field(csr.action.R, unsigned(1))
        ready: csr.Field(csr.action.R, unsigned(1))

    def __init__(self, *, sample_rate, min_pitch_window_s=0.05,
                 level_window_log2=13, hysteresis_counts=64,
                 dc_filter_shift=None, multichannel=False, with_reference=True,
                 with_legacy_pitch=True):
        self.with_legacy_pitch = with_legacy_pitch
        self.with_reference = with_reference
        self.multichannel = multichannel
        self.sample_rate = int(sample_rate)
        self.verifier_decimation = 1 << min(3, max(0, (self.sample_rate//24000).bit_length()-1))
        self.min_pitch_samples = max(1, round(sample_rate * min_pitch_window_s))
        # Match the firmware's existing half-second stale-pitch threshold.
        self.pitch_timeout_samples = max(1, self.sample_rate // 2)
        self.level_window_log2 = level_window_log2
        self.level_window_samples = 1 << level_window_log2
        self.hysteresis_counts = hysteresis_counts
        # Keep approximately the same 21 ms DC-filter time constant in both
        # codec modes (1024 samples at 48 kHz, 4096 at 192 kHz). An explicit
        # shift remains available for deterministic low-rate simulations.
        self.dc_filter_shift = (max(1, round(math.log2(self.sample_rate * 4096 / 192000)))
                                if dc_filter_shift is None else dc_filter_shift)

        regs = csr.Builder(addr_width=8, data_width=8)
        self._control = regs.add("control", self.Control(), offset=0x00)
        self._info = regs.add("info", self.Info(), offset=0x04)
        self._pitch_sequence = regs.add(
            "pitch_sequence", self.PitchSequence(), offset=0x08)
        self._period_samples = regs.add(
            "period_samples", self.PeriodSamples(), offset=0x0c)
        self._period_cycles = regs.add(
            "period_cycles", self.PeriodCycles(), offset=0x10)
        self._level_sequence = regs.add(
            "level_sequence", self.LevelSequence(), offset=0x14)
        self._mean_square = regs.add(
            "mean_square", self.MeanSquare(), offset=0x18)
        self._minimum = regs.add("minimum", self.SignedLevel(), offset=0x20)
        self._maximum = regs.add("maximum", self.SignedLevel(), offset=0x24)
        self._dc = regs.add("dc", self.SignedLevel(), offset=0x28)
        self._pitch_age = regs.add(
            "pitch_age", self.PitchAge(), offset=0x2c)
        self._reference_control = regs.add(
            "reference_control", self.ReferenceControl(), offset=0x30)
        self._reference_increment = regs.add(
            "reference_increment", self.ReferenceIncrement(), offset=0x34)
        self._verify_request = regs.add("verify_request", self.VerifyRequest(), offset=0x38)
        self._verify_status = regs.add("verify_status", self.VerifyStatus(), offset=0x3c)
        self._verify_lag = regs.add("verify_lag", self.VerifyLag(), offset=0x40)
        self._verify_info = regs.add("verify_info", self.VerifyInfo(), offset=0x44)
        self._verify_channel = regs.add("verify_channel", self.Control(), offset=0x48)
        self._pitch_end = regs.add("pitch_end", self.SignedLevel(), offset=0x4c)
        self._sample_clock = regs.add("sample_clock", self.SignedLevel(), offset=0x50)
        self._level_end = regs.add("level_end", self.SignedLevel(), offset=0x54)
        self._level_size = regs.add("level_size", self.SignedLevel(), offset=0x58)
        self._cal_command = regs.add("cal_command", self.ReferenceIncrement(), offset=0x5c)
        self._cal_status = regs.add("cal_status", self.SignedLevel(), offset=0x60)
        self._verify_capture = regs.add("verify_capture", self.VerifyCapture(), offset=0x64)
        self._verify_error = regs.add("verify_error", self.SignedLevel(), offset=0x68)
        self._verify_span = regs.add("verify_span", self.SignedLevel(), offset=0x6c)
        self._capture_control = regs.add("capture_control", self.CaptureControl(), offset=0x70)
        self._capture_data = regs.add("capture_data", self.CaptureData(), offset=0x74)
        self._cv_channel = regs.add("cv_channel", self.Control(), offset=0x78)
        self._cv_sample = regs.add("cv_sample", self.SignedLevel(), offset=0x7c)
        self._quant_cv = [regs.add(f"quant_cv{n}", self.SignedLevel(), offset=0x80+4*n) for n in range(4)]
        self._quant_command = [regs.add(f"quant_command{n}", self.ReferenceIncrement(), offset=0x90+4*n) for n in range(4)]
        self._quant_status = [regs.add(f"quant_status{n}", self.SignedLevel(), offset=0xa0+4*n) for n in range(4)]
        self._bridge = csr.Bridge(regs.as_memory_map())

        super().__init__({
            "i": In(stream.Signature(data.ArrayLayout(ASQ, 4))),
            # Advance once for every sample accepted by the calibrated DAC
            # stream. This keeps tone frequency independent of sync clock rate
            # and of temporary FIFO backpressure.
            "reference_advance": In(1),
            "reference": Out(ASQ),
            "reference_enabled": Out(1),
            "cal_value": Out(16), "cal_channel": Out(2),
            "cal_active": Out(1), "cal_fault": Out(1),
            "quant_value": Out(data.ArrayLayout(16, 4)),
            "bus": In(csr.Signature(
                addr_width=regs.addr_width, data_width=regs.data_width)),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)
        samples = Array(self.i.payload[n].as_value() for n in range(4))
        m.submodules.cv_snapshot = cv = CVSnapshot()
        cv_channel = self._cv_channel.f.channel.data
        previous_cv_channel = Signal(2)
        m.d.sync += previous_cv_channel.eq(cv_channel)
        m.d.comb += [cv.sample.eq(samples[cv_channel]), cv.accept.eq(self.i.valid),
                     cv.clear.eq((previous_cv_channel != cv_channel) | self._cv_channel.element.w_stb),
                     self._cv_sample.f.value.r_data.eq(cv.packed)]
        m.submodules.cal_output = cal = CalibrationOutput()
        m.d.comb += [cal.command.eq(self._cal_command.element.w_data),
                     cal.write.eq(self._cal_command.element.w_stb),
                     cal.advance.eq(self.reference_advance),
                     self.cal_value.eq(cal.value), self.cal_channel.eq(cal.channel),
                     self.cal_active.eq(cal.active), self.cal_fault.eq(cal.fault),
                     self._cal_status.f.value.r_data.eq(Cat(cal.token, cal.active, cal.fault))]
        # Each input is measured continuously, regardless of UI selection.
        # Each output owns its ACK/token/watchdog; CAL/PLAY has hard priority.
        for n in range(4):
            m.submodules[f"quant_cv{n}"] = snapshot = CVSnapshot()
            m.d.comb += [snapshot.sample.eq(samples[n]), snapshot.accept.eq(self.i.valid),
                         snapshot.clear.eq(0), self._quant_cv[n].f.value.r_data.eq(snapshot.packed)]
            m.submodules[f"quant_output{n}"] = lane = CalibrationOutput()
            inhibit = cal.active | cal.fault | self._cal_command.element.w_stb
            m.d.comb += [lane.command.eq(Mux(inhibit, 0, self._quant_command[n].element.w_data)),
                         lane.write.eq(inhibit | self._quant_command[n].element.w_stb),
                         lane.advance.eq(self.reference_advance),
                         self.quant_value[n].eq(Mux(inhibit, 0, lane.value)),
                         self._quant_status[n].f.value.r_data.eq(Cat(lane.token, lane.active, lane.fault))]
        selected = self._control.f.channel.data
        last_selected = Signal(2)
        m.d.sync += last_selected.eq(selected)
        m.d.comb += [self.i.ready.eq(1), self._info.f.sample_rate.r_data.eq(self.sample_rate)]
        lanes = []
        for index in range(4 if self.multichannel else 1):
            lane = MeasurementLane(self)
            m.submodules[f"lane{index}"] = lane
            lanes.append(lane)
            m.d.comb += [
                lane.sample.eq(samples[index] if self.multichannel else samples[selected]),
                lane.accept.eq(self.i.valid & self.i.ready),
                lane.clear.eq((cal.changed & (cal.input == index)) |
                              (0 if self.multichannel else last_selected != selected)),
            ]
        read_lane = selected if self.multichannel else Const(0)
        m.d.comb += [self._pitch_end.f.value.r_data.eq(Array(l.pitch_end for l in lanes)[read_lane]),
                     self._level_end.f.value.r_data.eq(Array(l.level_end for l in lanes)[read_lane]),
                     self._sample_clock.f.value.r_data.eq(lanes[0].sample_clock),
                     self._level_size.f.value.r_data.eq(self.level_window_samples)]
        m.d.comb += self._pitch_sequence.f.sequence.r_data.eq(Array(lane.pitch_sequence for lane in lanes)[read_lane])
        m.d.comb += self._period_samples.f.samples.r_data.eq(Array(lane.period_samples for lane in lanes)[read_lane])
        m.d.comb += self._period_cycles.f.cycles.r_data.eq(Array(lane.period_cycles for lane in lanes)[read_lane])
        m.d.comb += self._pitch_age.f.samples.r_data.eq(Array(lane.pitch_age for lane in lanes)[read_lane])
        m.d.comb += self._level_sequence.f.sequence.r_data.eq(Array(lane.level_sequence for lane in lanes)[read_lane])
        m.d.comb += self._mean_square.f.value.r_data.eq(Array(lane.mean_square for lane in lanes)[read_lane])
        m.d.comb += self._minimum.f.value.r_data.eq(Array(lane.minimum for lane in lanes)[read_lane])
        m.d.comb += self._maximum.f.value.r_data.eq(Array(lane.maximum for lane in lanes)[read_lane])
        m.d.comb += self._dc.f.value.r_data.eq(Array(lane.dc for lane in lanes)[read_lane])
        if self.with_legacy_pitch:

            verification_channel = self._verify_channel.f.channel.data if self.multichannel else selected
            last_verification_channel = Signal(2)
            m.d.sync += last_verification_channel.eq(verification_channel)
            verification_lane = verification_channel if self.multichannel else Const(0)
            m.submodules.period_verifier = verifier = PeriodVerifier(decimation=self.verifier_decimation, adaptive=True)
            m.d.comb += [
                verifier.sample.eq(samples[verification_channel]),
                verifier.accept.eq(self.i.valid & self.i.ready),
                # Disable is not cal.changed (which only describes enabled steps).
                # An armed diagnostic must freeze before disable returns the DAC
                # to zero, not at a later background channel switch.
                verifier.clear.eq((last_verification_channel != verification_channel) | cal.changed |
                                  (self._capture_control.f.arm.data &
                                   self._cal_command.element.w_stb &
                                   ~self._cal_command.element.w_data[18]) |
                                  Array(lane.expired for lane in lanes)[verification_lane]),
                verifier.request.eq(self._verify_request.element.w_stb),
                verifier.lag_q8.eq(self._verify_request.f.lag_q8.w_data),
                self._verify_status.f.busy.r_data.eq(verifier.busy),
                self._verify_status.f.done.r_data.eq(verifier.done),
                self._verify_status.f.factor.r_data.eq(verifier.factor),
                self._verify_lag.f.lag_q8.r_data.eq(verifier.result_lag_q8),
                verifier.capture_mode.eq(self._verify_capture.f.mode.data),
                self._verify_info.f.decimation.r_data.eq(verifier.capture_divisor),
                self._verify_error.f.value.r_data.eq(verifier.first_error),
                self._verify_span.f.value.r_data.eq(verifier.first_span),
                verifier.capture_arm.eq(self._capture_control.f.arm.data),
                verifier.capture_address.eq(self._capture_control.f.address.data),
                self._capture_data.f.sample.r_data.eq(verifier.capture_sample),
                self._capture_data.f.frozen.r_data.eq(verifier.capture_frozen),
                self._capture_data.f.ready.r_data.eq(verifier.capture_ready),
            ]
        if self.with_reference:
            m.submodules.reference_oscillator = reference = ReferenceOscillator()
            m.d.comb += [
                reference.advance.eq(self.reference_advance),
                reference.enable.eq(self._reference_control.f.enable.data),
                reference.increment.eq(self._reference_increment.f.value.data),
                self.reference.as_value().eq(reference.o.as_value()),
                self.reference_enabled.eq(self._reference_control.f.enable.data),
            ]
        else:
            m.d.comb += [self.reference.as_value().eq(0), self.reference_enabled.eq(0)]
        return m


class MeasurementLane(wiring.Component):
    """Independent small crossing/level state; no verifier or reference oscillator."""
    def __init__(self, config):
        self.with_legacy_pitch = config.with_legacy_pitch
        for name in ("sample_rate", "dc_filter_shift", "hysteresis_counts",
                     "pitch_timeout_samples", "min_pitch_samples",
                     "level_window_log2", "level_window_samples"):
            setattr(self, name, getattr(config, name))
        super().__init__({
            "sample": In(signed(16)), "accept": In(1), "clear": In(1),
            "expired": Out(1), "pitch_sequence": Out(16),
            "period_samples": Out(32), "period_cycles": Out(16),
            "pitch_age": Out(32), "level_sequence": Out(16),
            "mean_square": Out(32), "minimum": Out(32),
            "maximum": Out(32), "dc": Out(32),
            "pitch_end": Out(32), "level_end": Out(32), "sample_clock": Out(32),
        })

    def elaborate(self, platform):
        m = Module()

        sample_width = ASQ.as_shape().width
        sample = self.sample
        # Retain fractional counts in the DC filter. Shifting the correction
        # before accumulating rounds every negative fraction down while small
        # positive corrections become zero, biasing the crossing threshold.
        dc_accumulator = Signal(signed(sample_width + self.dc_filter_shift + 2))
        dc_estimate = Signal(signed(sample_width + 2))
        ac_sample = Signal(signed(sample_width + 3))

        m.d.comb += [
            dc_estimate.eq(dc_accumulator >> self.dc_filter_shift),
            ac_sample.eq(sample - dc_estimate),
        ]

        # Pitch measurement state. A crossing is accepted only after the
        # waveform has visited the negative hysteresis band.
        armed = Signal()
        sample_clock = Signal(32)
        m.d.comb += self.sample_clock.eq(sample_clock)
        first_crossing = Signal(32)
        interval_count = Signal(16)
        pitch_sequence = Signal(16)
        period_samples = Signal(32)
        period_cycles = Signal(16)
        have_crossing = Signal()
        pitch_age = Signal(32, init=(1 << 32) - 1)
        elapsed = Signal(32)
        crossing = Signal()
        expired = Signal()
        m.d.comb += [
            elapsed.eq(sample_clock - first_crossing),
            expired.eq(pitch_age >= self.pitch_timeout_samples),
            self.expired.eq(self.accept & have_crossing & expired if self.with_legacy_pitch else 0),
            crossing.eq(armed & (ac_sample >= self.hysteresis_counts)),
            self.pitch_sequence.eq(pitch_sequence if self.with_legacy_pitch else 0),
            self.period_samples.eq(period_samples if self.with_legacy_pitch else 0),
            self.period_cycles.eq(period_cycles if self.with_legacy_pitch else 0),
            self.pitch_age.eq(pitch_age if self.with_legacy_pitch else 0xffffffff),
        ]

        # Level measurement state. The power-of-two window avoids a divider;
        # the latched sum is shifted into a mean square.
        level_index = Signal(self.level_window_log2)
        square = Signal(unsigned(sample_width * 2))
        square_sum = Signal(unsigned(sample_width * 2 + self.level_window_log2))
        minimum = Signal(signed(sample_width))
        maximum = Signal(signed(sample_width))
        mean_square = Signal(32)
        level_minimum = Signal(signed(32))
        level_maximum = Signal(signed(32))
        level_dc = Signal(signed(32))
        level_sequence = Signal(16)
        m.d.comb += [
            square.eq(sample * sample),
            self.level_sequence.eq(level_sequence),
            self.mean_square.eq(mean_square),
            self.minimum.eq(level_minimum),
            self.maximum.eq(level_maximum),
            self.dc.eq(level_dc),
        ]

        with m.If(self.accept):
            m.d.sync += [
                sample_clock.eq(sample_clock + 1),
                pitch_age.eq(Mux(pitch_age.all(), pitch_age, pitch_age + 1)),
                dc_accumulator.eq(dc_accumulator + sample - dc_estimate),
            ]

            # Retire the unfinished observation as well as its published pitch.
            # Otherwise the first crossing after silence includes that silence
            # in elapsed time and publishes a spurious low frequency.
            with m.If(have_crossing & expired):
                m.d.sync += [have_crossing.eq(0), armed.eq(0),
                             interval_count.eq(0), period_samples.eq(0),
                             period_cycles.eq(0), pitch_sequence.eq(pitch_sequence + 1)]

            with m.If(ac_sample <= -self.hysteresis_counts):
                m.d.sync += armed.eq(1)
            with m.If(crossing):
                m.d.sync += [armed.eq(0), pitch_age.eq(0)]
                with m.If(~have_crossing | expired):
                    m.d.sync += [
                        have_crossing.eq(1),
                        first_crossing.eq(sample_clock),
                        interval_count.eq(0),
                    ]
                with m.Elif(elapsed >= self.min_pitch_samples):
                    m.d.sync += [
                        period_samples.eq(elapsed),
                        self.pitch_end.eq(sample_clock if self.with_legacy_pitch else 0),
                        period_cycles.eq(interval_count + 1),
                        pitch_sequence.eq(pitch_sequence + 1),
                        first_crossing.eq(sample_clock),
                        interval_count.eq(0),
                    ]
                with m.Else():
                    m.d.sync += interval_count.eq(interval_count + 1)

            # Use an explicit reduction instead of comparing against an
            # unsized zero literal. The latter becomes a zero-width operand in
            # RTLIL and can lose the accumulator-reset term during synthesis.
            with m.If(~level_index.any()):
                m.d.sync += [
                    minimum.eq(sample),
                    maximum.eq(sample),
                    square_sum.eq(square),
                ]
            with m.Else():
                m.d.sync += square_sum.eq(square_sum + square)
                with m.If(sample < minimum):
                    m.d.sync += minimum.eq(sample)
                with m.If(sample > maximum):
                    m.d.sync += maximum.eq(sample)

            with m.If(level_index == self.level_window_samples - 1):
                # Include the current sample: nonblocking assignments mean the
                # running values here still describe the preceding samples.
                m.d.sync += [
                    mean_square.eq((square_sum + square) >>
                                   self.level_window_log2),
                    level_minimum.eq(Mux(sample < minimum, sample, minimum)),
                    level_maximum.eq(Mux(sample > maximum, sample, maximum)),
                    level_dc.eq(dc_estimate),
                    level_sequence.eq(level_sequence + 1),
                    self.level_end.eq(sample_clock),
                ]
            m.d.sync += level_index.eq(level_index + 1)

        # Input changes invalidate BOTH measurement windows and their published
        # snapshots, even while the audio stream is paused. Keep this after the
        # sample-processing assignments: a coincident crossing/window completion
        # must not override reset and publish mixed-channel data. At most the
        # one sample coinciding with the handoff is discarded.
        with m.If(self.clear):
            m.d.sync += [
                dc_accumulator.eq(0), armed.eq(0), have_crossing.eq(0),
                first_crossing.eq(0), interval_count.eq(0),
                period_samples.eq(0), period_cycles.eq(0),
                pitch_age.eq((1 << 32) - 1),
                pitch_sequence.eq(pitch_sequence + 1),
                level_index.eq(0), square_sum.eq(0),
                minimum.eq(0), maximum.eq(0),
                mean_square.eq(0), level_minimum.eq(0),
                level_maximum.eq(0), level_dc.eq(0),
                level_sequence.eq(level_sequence + 1),
            ]

        return m
