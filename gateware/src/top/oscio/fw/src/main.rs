#![no_std]
#![no_main]

use critical_section::Mutex;
use riscv_rt::entry;
use irq::handler;
use core::cell::RefCell;

use tiliqua_fw::*;
use tiliqua_lib::*;
use pac::constants::*;
use tiliqua_lib::calibration::*;

use tiliqua_hal::embedded_graphics::prelude::*;
use tiliqua_hal::embedded_graphics::primitives::{PrimitiveStyle, Rectangle};
use tiliqua_lib::color::HI8;

use options::*;
use menu_draw::draw_scope_menu;
use opts::persistence::*;
use hal::pca9635::Pca9635Driver;
use tiliqua_hal::dma_framebuffer::Rotate;
use tiliqua_lib::ui_layer::{UiLayer, UiLayerPort, words_psram};

pub const TIMER0_ISR_PERIOD_MS: u32 = 5;

/// Maximum display width covered by the scope capture RAM. Wider modes still
/// render, but the waveform is limited to a centered viewport of this width.
const MAX_SCOPE_DISPLAY_WIDTH: u32 = 1280;
const WAVEFORM_MARGIN_X: u32 = 8;

fn scope_display_width(h_active: u32) -> u32 {
    h_active.min(MAX_SCOPE_DISPLAY_WIDTH)
}

/// The -1..+1 ramp reshaped to the plotter's 15 fractional bits spans 2^16
/// integer counts before the horizontal shift in ColumnCapture.
const RAMP_SPAN_BASE_PX: u32 = 1 << 16;

/// Select the largest horizontal shift whose ramp still covers the supported
/// waveform width. This calculation must not depend on ``px_div_x`` because
/// that value already contains the previous shift; feeding it back here makes
/// the main loop alternate between two scales.
fn xscale_for_full_width(h_active: u32) -> u8 {
    let target = scope_display_width(h_active)
        .saturating_sub(2 * WAVEFORM_MARGIN_X)
        .max(1);
    let mut scale = 8u8;
    while scale > 2 && (RAMP_SPAN_BASE_PX >> scale) < target {
        scale -= 1;
    }
    scale
}

/// Center-coordinate plot bounds for waveform erase/draw (full display width).
fn waveform_plot_bounds(h_active: u32, v_active: u32) -> (i16, i16, i16, i16) {
    let hx = (scope_display_width(h_active) / 2) as i16;
    let hy = (v_active / 2) as i16;
    let margin_x = WAVEFORM_MARGIN_X as i16;
    let margin_y = 16i16;
    (-hx + margin_x, hx - margin_x, -hy + margin_y, hy - margin_y)
}

const CLEAR_TILE_W: u32 = 128;
const CLEAR_TILE_H: u32 = 128;
const CLEAR_TILE_KEY: u32 = 0x5343_4c52; // "SCLR"
static CLEAR_TILE: [u8; (CLEAR_TILE_W * CLEAR_TILE_H / 8) as usize] =
    [0xff; (CLEAR_TILE_W * CLEAR_TILE_H / 8) as usize];

/// Fill a rectangle with a small all-ones 1bpp tile drawn in black.
///
/// A regular embedded-graphics rectangle falls back to one CSR plot command
/// per pixel on this target. Tiling through the hardware blitter reduces a
/// 1280x720 clear from 921,600 plot commands to only 60 blit commands.
fn clear_region<D>(display: &mut D, region: Rectangle)
where
    D: DrawTarget<Color = HI8> + OriginDimensions,
{
    let top_left = region.top_left;
    let size = region.size;
    if display.upload_spritesheet(
        CLEAR_TILE_KEY,
        &CLEAR_TILE,
        CLEAR_TILE_W,
        CLEAR_TILE_H,
        1,
    ) {
        let mut y = 0;
        while y < size.height {
            let tile_h = (size.height - y).min(CLEAR_TILE_H);
            let mut x = 0;
            while x < size.width {
                let tile_w = (size.width - x).min(CLEAR_TILE_W);
                display.blit_sprite(
                    CLEAR_TILE_KEY,
                    0,
                    0,
                    tile_w,
                    tile_h,
                    top_left.x + x as i32,
                    top_left.y + y as i32,
                    HI8::new(0, 0),
                );
                x += CLEAR_TILE_W;
            }
            y += CLEAR_TILE_H;
        }
    } else {
        region
            .into_styled(PrimitiveStyle::with_fill(HI8::new(0, 0)))
            .draw(display)
            .ok();
    }
}

fn clear_framebuffer<D>(display: &mut D)
where
    D: DrawTarget<Color = HI8> + OriginDimensions,
{
    let size = display.size();
    clear_region(display, Rectangle::new(Point::new(0, 0), size));
}

struct OverlayUiPort<'a> {
    overlay: &'a pac::OVERLAY_PERIPH,
}

impl UiLayerPort for OverlayUiPort<'_> {
    fn set_mem_addr(&self, word: u16) {
        self.overlay.ui_mem_addr().write(|w| unsafe {
            w.addr().bits(word)
        });
    }

    fn write_mem_word(&self, data: u32) {
        self.overlay.ui_mem_data().write(|w| unsafe {
            w.data().bits(data)
        });
    }
}

/// Right margin from the active display edge to the menu bitmap.
const MENU_MARGIN_X: u32 = 16;

const MENU_DRAW_Y: u32 = 18;

fn ui_menu_origin(h_active: u32, v_active: u32, help_page: bool) -> (u32, u32) {
    if help_page {
        // draw_scope_menu's local geometry corresponds to draw_options() with
        // pos_x=84 and pos_y=18. Match XBEAM/SONORO's Help placement at
        // (h_active / 2 - 30, v_active - 100).
        (
            (h_active / 2).saturating_sub(114),
            v_active.saturating_sub(118),
        )
    } else {
        (
            h_active.saturating_sub(
                MENU_MARGIN_X + OVERLAY_UI_MENU_W as u32),
            (v_active / 2).saturating_sub(MENU_DRAW_Y),
        )
    }
}

fn clear_ui_menu(
    menu: &mut UiLayer<OVERLAY_UI_MENU_WORDS>,
    port: &impl UiLayerPort,
) {
    menu.clear();
    menu.flush(port);
}

fn redraw_ui_menu(
    menu: &mut UiLayer<OVERLAY_UI_MENU_WORDS>,
    port: &impl UiLayerPort,
    opts: &Opts,
    hue: u8,
) {
    menu.clear();
    Rectangle::new(
        Point::new(0, 0),
        Size::new(OVERLAY_UI_MENU_W as u32, OVERLAY_UI_MENU_H as u32),
    )
    .into_styled(PrimitiveStyle::with_fill(HI8::new(0, 0)))
    .draw(menu)
    .ok();
    draw_scope_menu(
        menu,
        opts,
        opts.tracker.page.value,
        hue,
        OVERLAY_UI_MENU_W as u32,
        OVERLAY_UI_MENU_H as u32,
    )
    .ok();
    menu.flush(port);
}

fn sync_ui_overlay_csrs(
    overlay: &pac::OVERLAY_PERIPH,
    dvi_w: u32,
    dvi_h: u32,
    logical_w: u32,
    logical_h: u32,
    rotation: Rotate,
    menu_shown: bool,
    help_page: bool,
    hue: u8,
) {
    let (origin_x, origin_y, transparent) = if menu_shown {
        let (x, y) = ui_menu_origin(logical_w, logical_h, help_page);
        // Keep the normal options panel opaque for readability over scope
        // traces, but do not cover the help content behind its small menu.
        (x, y, help_page)
    } else {
        (0, 0, false)
    };
    let menu_px = ((10u8) << 4) | hue;
    overlay.ui_timings().write(|w| unsafe {
        // The overlay rotates physical DVI scan coordinates into logical
        // framebuffer coordinates, so these must remain the unrotated mode
        // dimensions even when the framebuffer's reported size is swapped.
        w.h_active().bits(dvi_w as u16);
        w.v_active().bits(dvi_h as u16)
    });
    overlay.ui_menu_origin().write(|w| unsafe {
        w.origin_x().bits(origin_x as u16);
        w.origin_y().bits(origin_y as u16)
    });
    overlay.ui_menu_pixel().write(|w| unsafe {
        w.pixel().bits(menu_px)
    });
    overlay.ui_control().write(|w| unsafe {
        w.menu_enable().bit(menu_shown);
        w.menu_transparent().bit(transparent);
        w.rotation().bits(rotation as u8)
    });
}

struct App {
    ui: ui::UI<Encoder0, EurorackPmod0, I2c0, Opts>,
}

impl App {
    pub fn new(opts: Opts) -> Self {
        let peripherals = unsafe { pac::Peripherals::steal() };
        let encoder = Encoder0::new(peripherals.ENCODER0);
        let i2cdev = I2c0::new(peripherals.I2C0);
        let pca9635 = Pca9635Driver::new(i2cdev);
        let pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
        let hide_ms = menu_hide_ms(opts.menu.hide.value);
        let hide_while_editing = opts.menu.edit_hide.value == EditHide::On;
        let mut ui = ui::UI::new_with_fade(
            opts,
            TIMER0_ISR_PERIOD_MS,
            hide_ms,
            encoder,
            pca9635,
            pmod,
        );
        ui.set_hide_while_editing(hide_while_editing);
        Self { ui }
    }
}

fn timer0_handler(app: &Mutex<RefCell<App>>) {
    critical_section::with(|cs| {
        let mut app = app.borrow_ref_mut(cs);
        app.ui.update_encoder(options::scope_consume_ticks);
    });
}

#[entry]
fn main() -> ! {
    let peripherals = pac::Peripherals::take().unwrap();
    let sysclk = pac::clock::sysclk();
    let mut timer = Timer0::new(peripherals.TIMER0, sysclk);
    let spiflash = SPIFlash0::new(
        peripherals.SPIFLASH_CTRL,
        SPIFLASH_BASE,
        SPIFLASH_SZ_BYTES
    );

    let bootinfo = unsafe { bootinfo::BootInfo::from_addr(BOOTINFO_BASE) }.unwrap();
    let modeline = bootinfo.modeline.maybe_override_fixed(
        FIXED_MODELINE, CLOCK_DVI_HZ);
    let mut display = DMAFramebuffer0::new(
        peripherals.FRAMEBUFFER_PERIPH,
        peripherals.PALETTE_PERIPH,
        peripherals.BLIT,
        peripherals.PIXEL_PLOT,
        peripherals.LINE,
        PSRAM_FB_BASE,
        modeline.clone(),
        BLIT_MEM_BASE,
    );
    clear_framebuffer(&mut display);

    let mut i2cdev1 = I2c1::new(peripherals.I2C1);
    let mut pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
    CalibrationConstants::load_or_default(&mut i2cdev1, &mut pmod);

    let mut opts = Opts::default();
    opts.misc.rotation.value = modeline.rotate.clone();
    let mut flash_persist_opt = if let Some(storage_window) = bootinfo.manifest.get_option_storage_window() {
        let mut flash_persist = FlashOptionsPersistence::new(spiflash, storage_window);
        flash_persist.load_options(&mut opts).unwrap();
        Some(flash_persist)
    } else {
        None
    };
    // Boot straight into the scope; ignore a saved Help-page selection.
    opts.tracker.page.value = Page::Chan12;
    // Older builds allowed the persisted help position to reach 125. Keep an
    // existing option store from restoring a now-invalid blank viewport.
    opts.help.scroll.value = opts.help.scroll.value.min(5);

    let mut last_palette = opts.display.palette.value;
    let mut last_hide = opts.menu.hide.value;
    let mut last_edit_hide = opts.menu.edit_hide.value;
    let boot_ui_hue = opts.menu.ui_hue.value;
    let app = Mutex::new(RefCell::new(App::new(opts)));
    critical_section::with(|cs| {
        let mut app = app.borrow_ref_mut(cs);
        app.ui.clear_draw();
        app.ui.set_menu_visible(false);
    });

    handler!(timer0 = || timer0_handler(&app));

    irq::scope(|s| {

        s.register(handlers::Interrupt::TIMER0, timer0);

        timer.enable_tick_isr(TIMER0_ISR_PERIOD_MS,
                              pac::Interrupt::TIMER0);

        let mut scope = Scope0::new(peripherals.SCOPE_PERIPH, 6);
        scope.set_timebase_frac_bits(28);
        let overlay_periph = peripherals.OVERLAY_PERIPH;
        let ui_port = OverlayUiPort { overlay: &overlay_periph };
        let mut ui_menu = unsafe {
            UiLayer::new_in(
                words_psram(OVERLAY_UI_SCRATCH_BASE),
                0,
                OVERLAY_UI_MENU_W as u32,
                OVERLAY_UI_MENU_H as u32,
            )
        };
        let mut first = true;
        let mut menu_shown = false;
        let mut last_menu_page = Page::Chan12;
        let mut overlay_active = false;
        let mut was_help_page = false;
        let mut last_help_scroll = 0u8;

        let dvi_w = modeline.h_active as u32;
        let dvi_h = modeline.v_active as u32;
        let logical_w = display.size().width;
        let logical_h = display.size().height;
        overlay_periph.grid_offset().write(|w| unsafe {
            w.offset_x().bits((dvi_w / 2) as u16);
            w.offset_y().bits((dvi_h / 2) as u16)
        });
        sync_ui_overlay_csrs(
            &overlay_periph,
            dvi_w,
            dvi_h,
            logical_w,
            logical_h,
            modeline.rotate.clone(),
            false,
            false,
            boot_ui_hue,
        );

        loop {

            let h_active = display.size().width;
            let v_active = display.size().height;

            let (opts, draw_options, menu_dirty, save_opts, wipe_opts) = critical_section::with(|cs| {
                let mut app = app.borrow_ref_mut(cs);
                let save_opts = app.ui.opts.misc.save_settings.poll();
                let wipe_opts = app.ui.opts.misc.reset_settings.poll();
                let menu_dirty = app.ui.take_menu_dirty();
                (app.ui.opts.clone(), app.ui.draw(), menu_dirty, save_opts, wipe_opts)
            });

            let on_help_page = opts.tracker.page.value == Page::Help;
            let entering_help = on_help_page && !was_help_page;
            let help_scrolled = on_help_page
                && was_help_page
                && opts.help.scroll.value != last_help_scroll;

            if on_help_page != was_help_page {
                clear_framebuffer(&mut display);
            }

            if opts.display.palette.value != last_palette || first {
                opts.display.palette.value.write_to_hardware(&mut display);
                last_palette = opts.display.palette.value;
            }

            if opts.menu.hide.value != last_hide || first {
                critical_section::with(|cs| {
                    let mut app = app.borrow_ref_mut(cs);
                    app.ui.set_encoder_fade_ms(menu_hide_ms(opts.menu.hide.value));
                });
                last_hide = opts.menu.hide.value;
            }

            if opts.menu.edit_hide.value != last_edit_hide || first {
                critical_section::with(|cs| {
                    app.borrow_ref_mut(cs).ui.set_hide_while_editing(
                        opts.menu.edit_hide.value == EditHide::On,
                    );
                });
                last_edit_hide = opts.menu.edit_hide.value;
            }

            if draw_options || on_help_page {
                let page_changed = opts.tracker.page.value != last_menu_page;
                if menu_dirty || !menu_shown || page_changed {
                    redraw_ui_menu(
                        &mut ui_menu,
                        &ui_port,
                        &opts,
                        opts.menu.ui_hue.value,
                    );
                    last_menu_page = opts.tracker.page.value;
                }
                menu_shown = true;
            } else {
                if menu_shown {
                    clear_ui_menu(&mut ui_menu, &ui_port);
                    menu_shown = false;
                }
            }

            let want_overlay = menu_shown;
            if !want_overlay && overlay_active {
                clear_ui_menu(&mut ui_menu, &ui_port);
            }
            overlay_active = want_overlay;

            critical_section::with(|cs| {
                app.borrow_ref_mut(cs).ui.set_menu_visible(menu_shown);
            });

            if entering_help {
                draw::draw_help_page(
                    &mut display,
                    MODULE_DOCSTRING,
                    bootinfo.manifest.help.as_ref(),
                    h_active,
                    v_active,
                    opts.help.scroll.value,
                    opts.menu.ui_hue.value,
                )
                .ok();
            } else if help_scrolled {
                let help_x = (h_active / 2).saturating_sub(280);
                let help_y = (v_active / 2).saturating_sub(150);
                // Erase only pixels belonging to the previous text view. A
                // full 560x380 clear costs 212,800 writes and is especially
                // expensive when rotation maps rows to reverse-strided PSRAM.
                draw::erase_help(
                    &mut display,
                    help_x,
                    help_y,
                    last_help_scroll,
                    MODULE_DOCSTRING,
                )
                .ok();
                draw::draw_help(
                    &mut display,
                    help_x,
                    help_y,
                    opts.help.scroll.value,
                    MODULE_DOCSTRING,
                    opts.menu.ui_hue.value,
                )
                .ok();
            }

            sync_ui_overlay_csrs(
                &overlay_periph,
                dvi_w,
                dvi_h,
                h_active,
                v_active,
                opts.misc.rotation.value.clone(),
                menu_shown,
                on_help_page,
                opts.menu.ui_hue.value,
            );

            if save_opts {
                if let Some(ref mut flash_persist) = flash_persist_opt {
                    flash_persist.save_options(&opts).unwrap();
                }
            }

            if wipe_opts {
                critical_section::with(|cs| {
                    let mut app = app.borrow_ref_mut(cs);
                    app.ui.opts = Opts::default();
                    app.ui.opts.misc.rotation.value = modeline.rotate.clone();
                    app.ui.opts.tracker.page.value = Page::Chan12;
                    app.ui.external_modify();
                    if let Some(ref mut flash_persist) = flash_persist_opt {
                        flash_persist.erase_all().unwrap();
                    }
                });
            }

            scope.set_hue(opts.display.hue.value);
            scope.set_intensity(opts.display.intensity.value);
            scope.set_trigger_level(opts.scope.trig_lvl.value);
            let (sppd_x, sppd) = scope.pixels_per_div();
            let xscale = xscale_for_full_width(h_active);
            scope.set_xscale(xscale);
            let t_div_us = opts.scope.timebase.value.t_div_us();
            scope.set_timebase_us(t_div_us);
            // A full-width sweep spans roughly ten divisions. Atomic swaps feel
            // fluid through 20 ms/div (~5 completed sweeps/s), but fall to only
            // ~2 sweeps/s at 50 ms/div. Use progressive column replacement from
            // 50 ms/div onward so slower acquisitions remain visibly live.
            scope.set_display_mode(
                t_div_us >= 50_000,
                opts.scope.acquisition.value == AcquisitionMode::Clean,
            );
            let (plot_x_lo, plot_x_hi, plot_y_lo, plot_y_hi) =
                waveform_plot_bounds(h_active, v_active);
            scope.set_plot_region(plot_x_lo, plot_x_hi, plot_y_lo, plot_y_hi);

            let ypos = [
                opts.chan12.ch1_y_offset.value,
                opts.chan12.ch2_y_offset.value,
                opts.chan34.ch3_y_offset.value,
                opts.chan34.ch4_y_offset.value,
            ];
            let yscale = [
                opts.chan12.ch1_scale.value,
                opts.chan12.ch2_scale.value,
                opts.chan34.ch3_scale.value,
                opts.chan34.ch4_scale.value,
            ];
            let vis = [
                opts.chan12.ch1_enabled.value,
                opts.chan12.ch2_enabled.value,
                opts.chan34.ch3_enabled.value,
                opts.chan34.ch4_enabled.value,
            ];
            for ch in 0..4usize {
                scope.set_yscale_index(ch, yscale[ch].to_hw_index());
                // Plot coordinates grow downward, while the user-facing
                // offset follows the normal graph convention: positive is
                // up and negative is down.
                // Multiply before dividing so four quarter-division steps land
                // exactly on the 62-pixel grid. Dividing ``sppd`` first made a
                // displayed 1.00 d offset move only 60 pixels.
                scope.set_ypos_px(ch, -(ypos[ch] * sppd as i16 / 4));
            }
            scope.set_channel_mask([
                vis[0] == ChannelVis::On,
                vis[1] == ChannelVis::On,
                vis[2] == ChannelVis::On,
                vis[3] == ChannelVis::On,
            ]);

            let is_portrait = matches!(opts.misc.rotation.value, Rotate::Left | Rotate::Right);
            let (dvi_ppd_x, dvi_ppd_y) = if is_portrait {
                (sppd, sppd_x)
            } else {
                (sppd_x, sppd)
            };
            overlay_periph.grid_spacing().write(|w| unsafe {
                w.spacing_x().bits(dvi_ppd_x as u8);
                w.spacing_y().bits(dvi_ppd_y as u8)
            });
            overlay_periph.grid_start().write(|w| unsafe {
                w.start_x().bits(((dvi_w / 2) % dvi_ppd_x) as u8);
                w.start_y().bits((((dvi_h / 2) + 1) % dvi_ppd_y) as u8)
            });

            let grid_style: u8 = match opts.display.grid.value {
                GridOverlay::Off => 0,
                GridOverlay::Grid => 1,
                GridOverlay::Cross => 2,
            };
            overlay_periph.flags().write(|w| unsafe {
                w.grid_style().bits(if on_help_page { 0 } else { grid_style });
                w.grid_pixel().bits(((opts.display.grid_i.value as u8) << 4) | opts.menu.ui_hue.value)
            });

            display.rotate(&opts.misc.rotation.value);

            let trigger = opts.scope.trigger.value;
            scope.set_trigger(
                !on_help_page,
                trigger == TriggerMode::Free,
                matches!(trigger, TriggerMode::AutoRising | TriggerMode::AutoFalling),
                matches!(trigger, TriggerMode::Falling | TriggerMode::AutoFalling),
                opts.scope.trigger_ch.value.hw_index(),
                opts.scope.trig_filter.value.hw_index(),
            );

            last_help_scroll = opts.help.scroll.value;
            was_help_page = on_help_page;
            first = false;
        }
    })
}
