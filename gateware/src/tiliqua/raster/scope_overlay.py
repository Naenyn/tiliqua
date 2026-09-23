# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Atomic, beam-raced display of completed oscilloscope sweeps."""

from amaranth import *
from amaranth.lib import memory, wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out

from ..config_cdc import ConfigCDC
from ..video.types import Pixel, Rotation, ScanPixel
from .scope_capture import (
    MAX_CAPTURE_COLS,
    ENVELOPE_CHANNEL_BITS,
    ENVELOPE_COORD_BITS,
    ENVELOPE_SENTINEL,
    ENVELOPE_WORD_BITS,
)


class ScopeTraceOverlay(wiring.Component):

    """Double-buffered column envelopes composited during video scanout.

    The sync domain captures into the hidden bank. A completed sweep requests a
    bank swap; the dvi domain acknowledges it only at vertical sync, making the
    whole trace visible atomically. No framebuffer pixels are erased or redrawn.
    """

    def __init__(self, *, n_channels=4):
        assert n_channels == 4
        self.n_channels = n_channels
        super().__init__({
            "i": In(ScanPixel),
            "o": Out(ScanPixel),
            # Capture interface, sync domain.
            "enable": In(1),
            "invalidate": In(1),
            "flush_valid": In(1),
            "flush_col": In(range(MAX_CAPTURE_COLS)),
            "flush_word": In(unsigned(ENVELOPE_WORD_BITS)),
            "sweep_done": In(1),
            "progressive": In(1),
            "capture_max_col": In(range(MAX_CAPTURE_COLS)),
            "capture_progress_valid": In(1),
            "capture_active": Out(1),
            "capture_clear": Out(1),
            "swap_done": Out(1),
            # Display parameters, sync domain (CDC'd internally).
            "plot_x_lo": In(signed(16)),
            "h_active": In(unsigned(16)),
            "v_active": In(unsigned(16)),
            "rotation": In(Rotation),
            "hue": In(unsigned(4)).array(n_channels),
            "intensity": In(unsigned(4)).array(n_channels),
        })

    def elaborate(self, platform):
        m = Module()

        banks = []
        write_ports = []
        read_ports = []
        for bank in range(2):
            mem = memory.Memory(
                data=memory.MemoryData(
                    shape=unsigned(ENVELOPE_WORD_BITS),
                    depth=MAX_CAPTURE_COLS,
                    init=[ENVELOPE_SENTINEL] * MAX_CAPTURE_COLS,
                )
            )
            setattr(m.submodules, f"sweep_mem{bank}", mem)
            banks.append(mem)
            write_ports.append(mem.write_port(domain="sync"))
            read_ports.append(mem.read_port(domain="dvi"))

        # ---- sync-domain capture / swap request controller -----------------
        back_bank = Signal(init=1)
        clear_col = Signal(range(MAX_CAPTURE_COLS))
        swap_bank = Signal()
        capture_generation = Signal()
        swap_generation = Signal()
        swap_request = Signal()
        swap_ack_dvi = Signal()
        swap_ack_sync = Signal()
        m.submodules.swap_ack_ff = FFSynchronizer(
            swap_ack_dvi, swap_ack_sync, o_domain="sync")

        for bank, wp in enumerate(write_ports):
            with m.If(back_bank == bank):
                with m.If(self.flush_valid):
                    m.d.comb += [
                        wp.en.eq(1),
                        wp.addr.eq(self.flush_col),
                        wp.data.eq(self.flush_word),
                    ]

        with m.FSM(name="scope_trace_capture"):
            with m.State("DISABLED"):
                with m.If(self.enable):
                    m.d.sync += clear_col.eq(0)
                    m.next = "CLEAR"

            with m.State("CLEAR"):
                for bank, wp in enumerate(write_ports):
                    with m.If(back_bank == bank):
                        m.d.comb += [
                            wp.en.eq(1),
                            wp.addr.eq(clear_col),
                            wp.data.eq(ENVELOPE_SENTINEL),
                        ]
                with m.If(self.invalidate):
                    m.d.sync += clear_col.eq(0)
                with m.Elif(~self.enable):
                    m.next = "DISABLED"
                with m.Elif(clear_col == MAX_CAPTURE_COLS - 1):
                    m.next = "ARM"
                with m.Else():
                    m.d.sync += clear_col.eq(clear_col + 1)

            with m.State("ARM"):
                m.d.comb += self.capture_clear.eq(1)
                with m.If(self.invalidate):
                    m.d.sync += clear_col.eq(0)
                    m.next = "CLEAR"
                with m.Elif(~self.enable):
                    m.next = "DISABLED"
                with m.Else():
                    m.next = "CAPTURE"

            with m.State("CAPTURE"):
                m.d.comb += self.capture_active.eq(self.enable)
                with m.If(self.invalidate):
                    m.d.sync += clear_col.eq(0)
                    m.next = "CLEAR"
                with m.Elif(~self.enable):
                    m.next = "DISABLED"
                with m.Elif(self.sweep_done):
                    m.d.sync += [
                        swap_bank.eq(back_bank),
                        swap_generation.eq(capture_generation),
                    ]
                    m.next = "SETTLE_SWAP"

            with m.State("SETTLE_SWAP"):
                # Bundled-data CDC: publish the request only after its bank and
                # generation payload has been stable for two complete sync
                # clocks.  The DVI request synchronizer therefore cannot win
                # the race against the independently synchronized payload.
                m.next = "PUBLISH_SWAP"

            with m.State("PUBLISH_SWAP"):
                m.d.sync += swap_request.eq(~swap_request)
                m.next = "WAIT_SWAP"

            with m.State("WAIT_SWAP"):
                # Finish an outstanding swap even if display is disabled, so
                # capture never resumes into the bank that just became front.
                with m.If(swap_ack_sync == swap_request):
                    m.d.comb += self.swap_done.eq(1)
                    m.d.sync += [
                        back_bank.eq(~back_bank),
                        clear_col.eq(0),
                    ]
                    with m.If(self.enable):
                        m.next = "CLEAR"
                    with m.Else():
                        m.next = "DISABLED"

        # Tag completed sweeps with the configuration generation in which they
        # were captured. An old swap already pending during invalidation can
        # then be acknowledged without exposing stale trace data.
        with m.If(self.invalidate):
            m.d.sync += capture_generation.eq(~capture_generation)

        # ---- dvi-domain atomic bank selection ------------------------------
        swap_request_dvi = Signal()
        swap_bank_dvi = Signal()
        swap_generation_dvi = Signal()
        capture_generation_dvi = Signal()
        m.submodules.swap_request_ff = FFSynchronizer(
            swap_request, swap_request_dvi, o_domain="dvi")
        m.submodules.swap_bank_ff = FFSynchronizer(
            swap_bank, swap_bank_dvi, o_domain="dvi")
        m.submodules.swap_generation_ff = FFSynchronizer(
            swap_generation, swap_generation_dvi, o_domain="dvi")
        m.submodules.capture_generation_ff = FFSynchronizer(
            capture_generation, capture_generation_dvi, o_domain="dvi")

        front_bank = Signal()
        front_valid = Signal()
        generation_seen = Signal()
        # Any point in vertical blank is safe. Restricting swaps to the vsync
        # edge made a sweep completed just after that edge wait almost another
        # full frame, which was visible as inferior update responsiveness.
        with m.If(generation_seen != capture_generation_dvi):
            m.d.dvi += [
                generation_seen.eq(capture_generation_dvi),
                front_valid.eq(0),
            ]
        with m.Elif((self.i.y < 0) &
                    (swap_ack_dvi != swap_request_dvi)):
            m.d.dvi += [
                front_bank.eq(swap_bank_dvi),
                front_valid.eq(
                    swap_generation_dvi == capture_generation_dvi),
                swap_ack_dvi.eq(swap_request_dvi),
            ]

        # ---- display parameter CDC ----------------------------------------
        plot_x_lo_dvi = Signal(signed(16))
        enable_dvi = Signal()
        h_active_dvi = Signal(16)
        v_active_dvi = Signal(16)
        rotation_dvi = Signal(Rotation)
        hue_dvi = Array(Signal(4) for _ in range(self.n_channels))
        intensity_dvi = Array(Signal(4) for _ in range(self.n_channels))
        progressive_dvi = Signal()
        capture_max_col_dvi = Signal(range(MAX_CAPTURE_COLS))
        capture_progress_valid_dvi = Signal()
        back_bank_dvi = Signal()
        display_config = Cat(
            self.plot_x_lo,
            self.enable,
            self.progressive,
            self.h_active,
            self.v_active,
            self.rotation,
            *self.hue,
            *self.intensity,
        )
        m.submodules.display_config_cdc = display_config_cdc = ConfigCDC(
            len(display_config))
        m.d.comb += [
            display_config_cdc.i.eq(display_config),
            Cat(
                plot_x_lo_dvi,
                enable_dvi,
                progressive_dvi,
                h_active_dvi,
                v_active_dvi,
                rotation_dvi,
                *hue_dvi,
                *intensity_dvi,
            ).eq(display_config_cdc.o),
        ]

        # Capture progress can update while a progressive sweep is visible, so
        # transfer it independently from the slower display configuration.
        progress_config = Cat(
            self.capture_max_col,
            self.capture_progress_valid,
            back_bank,
        )
        m.submodules.progress_config_cdc = progress_config_cdc = ConfigCDC(
            len(progress_config))
        m.d.comb += [
            progress_config_cdc.i.eq(progress_config),
            Cat(
                capture_max_col_dvi,
                capture_progress_valid_dvi,
                back_bank_dvi,
            ).eq(progress_config_cdc.o),
        ]

        # Transform physical scan coordinates back into the center-relative
        # logical coordinates used by ColumnCapture and the former plotter.
        logical_x = Signal(signed(16))
        logical_y = Signal(signed(16))
        with m.Switch(rotation_dvi):
            with m.Case(Rotation.NORMAL):
                m.d.comb += [
                    logical_x.eq(self.i.x - (h_active_dvi >> 1)),
                    logical_y.eq(self.i.y - (v_active_dvi >> 1)),
                ]
            with m.Case(Rotation.INVERTED):
                m.d.comb += [
                    logical_x.eq((h_active_dvi - 1 - self.i.x) - (h_active_dvi >> 1)),
                    logical_y.eq((v_active_dvi - 1 - self.i.y) - (v_active_dvi >> 1)),
                ]
            with m.Case(Rotation.LEFT):
                m.d.comb += [
                    logical_x.eq(self.i.y - (v_active_dvi >> 1)),
                    logical_y.eq((h_active_dvi - 1 - self.i.x) - (h_active_dvi >> 1)),
                ]
            with m.Case(Rotation.RIGHT):
                m.d.comb += [
                    logical_x.eq((v_active_dvi - 1 - self.i.y) - (v_active_dvi >> 1)),
                    logical_y.eq(self.i.x - (h_active_dvi >> 1)),
                ]

        # Register the rotation result before subtracting the plot origin and
        # checking the capture-memory bounds.  The former single stage placed
        # both signed coordinate transforms on the same DVI path as the
        # 17-bit column arithmetic, leaving the routed 74.25 MHz domain with a
        # narrow margin.  ScanPixel takes the same extra stage so the visible
        # result remains pixel-aligned.
        scan_geometry = Signal(ScanPixel)
        logical_x_geometry = Signal(signed(16))
        logical_y_geometry = Signal(signed(16))
        plot_x_lo_geometry = Signal(signed(16))
        front_bank_geometry = Signal()
        front_valid_geometry = Signal()
        m.d.dvi += [
            scan_geometry.eq(self.i),
            logical_x_geometry.eq(logical_x),
            logical_y_geometry.eq(logical_y),
            plot_x_lo_geometry.eq(plot_x_lo_dvi),
            front_bank_geometry.eq(front_bank),
            front_valid_geometry.eq(front_valid),
        ]

        col_full = Signal(signed(17))
        in_plot = Signal()
        m.d.comb += [
            col_full.eq(logical_x_geometry - plot_x_lo_geometry),
            in_plot.eq(scan_geometry.de & (col_full >= 0) &
                       (col_full < MAX_CAPTURE_COLS)),
        ]

        # Pipeline the coordinate transform before the BRAM address. This keeps
        # the rotation/subtraction path out of the memory setup budget at the
        # 74.25 MHz pixel clock.
        scan_addr = Signal(ScanPixel)
        logical_y_addr = Signal(signed(16))
        col_addr = Signal(range(MAX_CAPTURE_COLS))
        in_plot_addr = Signal()
        front_bank_addr = Signal()
        front_valid_addr = Signal()
        m.d.dvi += [
            scan_addr.eq(scan_geometry),
            logical_y_addr.eq(logical_y_geometry),
            col_addr.eq(col_full),
            in_plot_addr.eq(in_plot),
            front_bank_addr.eq(front_bank_geometry),
            front_valid_addr.eq(front_valid_geometry),
        ]
        for rp in read_ports:
            m.d.comb += [
                rp.en.eq(in_plot_addr),
                rp.addr.eq(col_addr),
            ]

        # Align scan coordinates with the synchronous BRAM output.
        scan_data = Signal(ScanPixel)
        logical_y_data = Signal(signed(16))
        in_plot_data = Signal()
        front_bank_data = Signal()
        front_valid_data = Signal()
        back_bank_data = Signal()
        progressive_data = Signal()
        capture_max_col_data = Signal(range(MAX_CAPTURE_COLS))
        capture_progress_valid_data = Signal()
        col_data = Signal(range(MAX_CAPTURE_COLS))
        m.d.dvi += [
            scan_data.eq(scan_addr),
            logical_y_data.eq(logical_y_addr),
            in_plot_data.eq(in_plot_addr),
            front_bank_data.eq(front_bank_addr),
            front_valid_data.eq(front_valid_addr),
            back_bank_data.eq(back_bank_dvi),
            progressive_data.eq(progressive_dvi),
            capture_max_col_data.eq(capture_max_col_dvi),
            capture_progress_valid_data.eq(capture_progress_valid_dvi),
            col_data.eq(col_addr),
        ]

        # Register the bank mux immediately after BRAM. ECP5 block RAM has a
        # substantial clock-to-output delay, so comparisons need their own
        # cycle rather than sharing it with the wide bank selection.
        front_word = Signal(ENVELOPE_WORD_BITS)
        scan_compare = Signal(ScanPixel)
        logical_y_compare = Signal(signed(16))
        in_plot_compare = Signal()
        display_bank = Signal()
        display_word_valid = Signal()
        progressive_column = Signal()
        m.d.comb += [
            progressive_column.eq(
                progressive_data & capture_progress_valid_data &
                (col_data <= capture_max_col_data)),
            display_bank.eq(Mux(progressive_column,
                                back_bank_data, front_bank_data)),
            display_word_valid.eq(progressive_column | front_valid_data),
        ]
        display_word_valid_compare = Signal()
        m.d.dvi += [
            front_word.eq(Mux(display_bank,
                              read_ports[1].data,
                              read_ports[0].data)),
            scan_compare.eq(scan_data),
            logical_y_compare.eq(logical_y_data),
            in_plot_compare.eq(in_plot_data),
            display_word_valid_compare.eq(display_word_valid),
        ]

        channel_hits = Signal(self.n_channels)
        for ch in range(self.n_channels):
            lo = ENVELOPE_CHANNEL_BITS * ch
            valid = front_word[lo]
            ymin = front_word[
                lo + 1:lo + 1 + ENVELOPE_COORD_BITS].as_signed()
            ymax = front_word[
                lo + 1 + ENVELOPE_COORD_BITS:
                lo + 1 + 2 * ENVELOPE_COORD_BITS].as_signed()
            channel_hit = enable_dvi & in_plot_compare & \
                display_word_valid_compare & valid & \
                (logical_y_compare >= ymin) & \
                (logical_y_compare <= ymax) & \
                (intensity_dvi[ch] > 0)
            m.d.comb += channel_hits[ch].eq(channel_hit)

        # Register comparisons before the color-priority mux.
        scan_hit = Signal(ScanPixel)
        channel_hits_d = Signal(self.n_channels)
        m.d.dvi += [
            scan_hit.eq(scan_compare),
            channel_hits_d.eq(channel_hits),
        ]

        hit = Signal()
        hit_hue = Signal(4)
        hit_intensity = Signal(4)
        for ch in range(self.n_channels):
            with m.If(channel_hits_d[ch]):
                m.d.comb += [
                    hit.eq(1),
                    hit_hue.eq(hue_dvi[ch]),
                    hit_intensity.eq(intensity_dvi[ch]),
                ]

        m.d.dvi += [
            self.o.eq(scan_hit),
        ]
        with m.If(hit & scan_hit.de):
            m.d.dvi += [
                self.o.pixel.color.eq(hit_hue),
                self.o.pixel.intensity.eq(hit_intensity),
            ]

        return m
