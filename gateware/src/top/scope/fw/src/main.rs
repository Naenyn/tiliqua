#![no_std]
#![no_main]

use critical_section::Mutex;
use log::info;
use riscv_rt::entry;
use irq::handler;
use core::cell::RefCell;

use midi_types::*;
use midi_convert::parse::MidiTryParseSlice;

use tiliqua_fw::*;
use tiliqua_lib::*;
use pac::constants::*;
use tiliqua_lib::calibration::*;

use tiliqua_hal::embedded_graphics::prelude::*;
use tiliqua_hal::embedded_graphics::primitives::{PrimitiveStyle, Rectangle};
use tiliqua_lib::color::HI8;

use options::*;
use opts::persistence::*;
use opts::{Options, OptionTrait};
use opts::cc_map::{MidiCcMapper, CcMapMode};
use hal::pca9635::Pca9635Driver;
use tiliqua_hal::dma_framebuffer::Rotate;
use tiliqua_lib::ui_layer::{UiLayer, UiLayerPort, words_psram};

pub const TIMER0_ISR_PERIOD_MS: u32 = 5;
/// How long the menu stays visible after the last encoder turn/press.
pub const MENU_HIDE_MS: u32 = 2000;

fn global_index(opts: &Opts, opt: &dyn OptionTrait) -> usize {
    let key = opt.key().value();
    opts.all().enumerate()
        .find(|(_, o)| o.key().value() == key)
        .expect("cc_map: option key not found").0
}

fn apply_cc_action(opts: &mut Opts, action: &opts::cc_map::CcAction) {
    if let Some(opt) = opts.all_mut().nth(action.global_index) {
        match action.mode {
            CcMapMode::Absolute => { opt.set_from_cc(action.cc_value); }
        }
    }
}

fn build_cc_mapper(opts: &Opts) -> MidiCcMapper {
    let mut m = MidiCcMapper::new();
    m.add(42, global_index(opts, &opts.display.ui_hue),   CcMapMode::Absolute);
    m.add(43, global_index(opts, &opts.display.palette),  CcMapMode::Absolute);
    m.add(44, global_index(opts, &opts.display.grid),     CcMapMode::Absolute);
    m.add(45, global_index(opts, &opts.display.grid_i),    CcMapMode::Absolute);
    m.add(52, global_index(opts, &opts.misc.rotation),    CcMapMode::Absolute);
    m.add(60, global_index(opts, &opts.scope1.ypos0),     CcMapMode::Absolute);
    m.add(61, global_index(opts, &opts.scope1.ypos1),     CcMapMode::Absolute);
    m.add(62, global_index(opts, &opts.scope1.ypos2),     CcMapMode::Absolute);
    m.add(63, global_index(opts, &opts.scope1.ypos3),     CcMapMode::Absolute);
    m.add(70, global_index(opts, &opts.scope1.yscale0),   CcMapMode::Absolute);
    m.add(71, global_index(opts, &opts.scope2.timebase),  CcMapMode::Absolute);
    m.add(73, global_index(opts, &opts.scope2.trig_mode), CcMapMode::Absolute);
    m.add(74, global_index(opts, &opts.scope2.trig_lvl),  CcMapMode::Absolute);
    m.add(75, global_index(opts, &opts.scope2.intensity), CcMapMode::Absolute);
    m.add(76, global_index(opts, &opts.scope2.hue),       CcMapMode::Absolute);
    m
}

/// Horizontal xscale so the ramp sweep spans the active display width.
///
/// At xscale ``S`` the sweep is approximately ``sppdx * 2^(9-S)`` pixels wide
/// (the old Normal 1x zoom used ``S=6``, i.e. ``8 * sppdx``).
fn xscale_for_full_width(h_active: u32, sppdx: u32) -> u8 {
    let margin = 16u32;
    let target = h_active.saturating_sub(2 * margin).max(1);
    let sppdx = sppdx.max(1);
    let ratio = (target + sppdx - 1) / sppdx;
    let exp = 32 - ratio.max(8).leading_zeros();
    let xscale = 9i32.saturating_sub(exp as i32);
    xscale.clamp(2, 8) as u8
}

/// Center-coordinate plot bounds for waveform erase/draw (full display width).
fn waveform_plot_bounds(h_active: u32, v_active: u32) -> (i16, i16, i16, i16) {
    let hx = (h_active / 2) as i16;
    let hy = (v_active / 2) as i16;
    let margin_x = 8i16;
    let margin_y = 16i16;
    (-hx + margin_x, hx - margin_x, -hy + margin_y, hy - margin_y)
}

fn clear_framebuffer<D>(display: &mut D)
where
    D: DrawTarget<Color = HI8> + OriginDimensions,
{
    let size = display.size();
    Rectangle::new(Point::new(0, 0), size)
        .into_styled(PrimitiveStyle::with_fill(HI8::new(0, 0)))
        .draw(display)
        .ok();
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

/// Horizontal inset inside the menu layer for draw_options (page title is
/// right-aligned at pos_x - 12; needs ~80px of headroom to the layer edge).
const MENU_DRAW_X: u32 = 88;
const MENU_DRAW_Y: u32 = 24;

fn ui_menu_origin(h_active: u32, v_active: u32) -> (u32, u32) {
    let opts_x = h_active - 200;
    let opts_y = v_active / 2;
    let menu_x = opts_x.saturating_sub(MENU_DRAW_X);
    let menu_y = opts_y.saturating_sub(MENU_DRAW_Y);
    (menu_x, menu_y)
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
    h_active: u32,
    v_active: u32,
    hue: u8,
) {
    let opts_x = h_active - 200;
    let opts_y = v_active / 2;
    let (menu_x, menu_y) = ui_menu_origin(h_active, v_active);

    menu.clear();
    Rectangle::new(
        Point::new(0, 0),
        Size::new(OVERLAY_UI_MENU_W as u32, OVERLAY_UI_MENU_H as u32),
    )
    .into_styled(PrimitiveStyle::with_fill(HI8::new(0, 0)))
    .draw(menu)
    .ok();
    draw::draw_options(
        menu,
        opts,
        opts_x - menu_x,
        opts_y - menu_y,
        hue,
    )
    .ok();
    menu.flush(port);
}

fn sync_ui_overlay_csrs(
    overlay: &pac::OVERLAY_PERIPH,
    h_active: u32,
    v_active: u32,
    rotation: Rotate,
    menu_shown: bool,
    hue: u8,
) {
    let (menu_x, menu_y) = ui_menu_origin(h_active, v_active);
    let menu_px = ((10u8) << 4) | hue;
    overlay.ui_timings().write(|w| unsafe {
        w.h_active().bits(h_active as u16);
        w.v_active().bits(v_active as u16)
    });
    overlay.ui_menu_origin().write(|w| unsafe {
        w.origin_x().bits(menu_x as u16);
        w.origin_y().bits(menu_y as u16)
    });
    overlay.ui_menu_pixel().write(|w| unsafe {
        w.pixel().bits(menu_px)
    });
    overlay.ui_control().write(|w| unsafe {
        w.menu_enable().bit(menu_shown);
        w.rotation().bits(rotation as u8)
    });
}

struct App {
    ui: ui::UI<Encoder0, EurorackPmod0, I2c0, Opts>,
    cc_mapper: MidiCcMapper,
}

impl App {
    pub fn new(opts: Opts) -> Self {
        let peripherals = unsafe { pac::Peripherals::steal() };
        let encoder = Encoder0::new(peripherals.ENCODER0);
        let i2cdev = I2c0::new(peripherals.I2C0);
        let pca9635 = Pca9635Driver::new(i2cdev);
        let pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
        let cc_mapper = build_cc_mapper(&opts);
        Self {
            ui: ui::UI::new_with_fade(opts, TIMER0_ISR_PERIOD_MS, MENU_HIDE_MS,
                            encoder, pca9635, pmod),
            cc_mapper,
        }
    }
}

fn timer0_handler(app: &Mutex<RefCell<App>>) {
    critical_section::with(|cs| {
        let mut app = app.borrow_ref_mut(cs);
        app.ui.update_encoder(options::scope_consume_ticks);

        let scope_ctrl = unsafe { pac::SCOPE_CTRL_PERIPH::steal() };
        let midi_word = scope_ctrl.midi_read().read().bits();
        if midi_word != 0 {
            app.ui.midi_activity();
            let bytes = [
                (midi_word & 0xFF) as u8,
                ((midi_word >> 8) & 0xFF) as u8,
                ((midi_word >> 16) & 0xFF) as u8,
            ];
            if let Ok(msg) = MidiMessage::try_parse_slice(&bytes) {
                if let MidiMessage::ControlChange(_, cc, val) = msg {
                    if let Some(action) = app.cc_mapper.process(cc.into(), val.into()) {
                        if app.ui.opts.misc.cc_highlight.value == CcHighlight::On {
                            app.ui.opts.select_global(action.global_index);
                            app.ui.external_modify();
                        }
                        apply_cc_action(&mut app.ui.opts, &action);
                        app.ui.external_modify();
                    }
                }
            }
        }

        if app.ui.opts.misc.help.value == HelpPage::Off
            && app.ui.opts.tracker.page.value == Page::Help {
            app.ui.opts.tracker.page.value = Page::Scope1;
        }
    });
}

#[entry]
fn main() -> ! {
    let peripherals = pac::Peripherals::take().unwrap();
    let sysclk = pac::clock::sysclk();
    let serial = Serial0::new(peripherals.UART0);
    let mut timer = Timer0::new(peripherals.TIMER0, sysclk);
    let spiflash = SPIFlash0::new(
        peripherals.SPIFLASH_CTRL,
        SPIFLASH_BASE,
        SPIFLASH_SZ_BYTES
    );

    tiliqua_fw::handlers::logger_init(serial);

    info!("Hello from Tiliqua SCOPE!");

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
    opts.tracker.page.value = Page::Scope1;

    let mut last_palette = opts.display.palette.value;
    let boot_ui_hue = opts.display.ui_hue.value;
    let app = Mutex::new(RefCell::new(App::new(opts)));
    critical_section::with(|cs| {
        app.borrow_ref_mut(cs).ui.clear_draw();
    });

    handler!(timer0 = || timer0_handler(&app));

    irq::scope(|s| {

        s.register(handlers::Interrupt::TIMER0, timer0);

        timer.enable_tick_isr(TIMER0_ISR_PERIOD_MS,
                              pac::Interrupt::TIMER0);

        let mut scope = Scope0::new(peripherals.SCOPE_PERIPH, 6);
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
        let mut last_menu_page = Page::Scope1;
        let mut debug_frame: u32 = 0;

        let dvi_w = modeline.h_active as u32;
        let dvi_h = modeline.v_active as u32;
        overlay_periph.grid_offset().write(|w| unsafe {
            w.offset_x().bits((dvi_w / 2) as u16);
            w.offset_y().bits((dvi_h / 2) as u16)
        });
        sync_ui_overlay_csrs(
            &overlay_periph,
            dvi_w,
            dvi_h,
            modeline.rotate.clone(),
            false,
            boot_ui_hue,
        );

        loop {

            let h_active = display.size().width;
            let v_active = display.size().height;

            let (opts, draw_options, menu_dirty, save_opts, wipe_opts) = critical_section::with(|cs| {
                let mut app = app.borrow_ref_mut(cs);
                let save_opts = app.ui.opts.misc.save_opts.poll();
                let wipe_opts = app.ui.opts.misc.wipe_opts.poll();
                let menu_dirty = app.ui.take_menu_dirty();
                (app.ui.opts.clone(), app.ui.draw(), menu_dirty, save_opts, wipe_opts)
            });

            let on_help_page = opts.tracker.page.value == Page::Help;

            if opts.display.palette.value != last_palette || first {
                opts.display.palette.value.write_to_hardware(&mut display);
                last_palette = opts.display.palette.value;
            }

            if draw_options || on_help_page {
                if !menu_shown {
                    critical_section::with(|cs| {
                        let mut app = app.borrow_ref_mut(cs);
                        app.ui.opts.set_selected(None);
                        app.ui.opts.modify_mut(false);
                    });
                }
                let page_changed = opts.tracker.page.value != last_menu_page;
                if menu_dirty || !menu_shown || page_changed {
                    redraw_ui_menu(
                        &mut ui_menu,
                        &ui_port,
                        &opts,
                        h_active,
                        v_active,
                        opts.display.ui_hue.value,
                    );
                    last_menu_page = opts.tracker.page.value;
                }
                menu_shown = true;
            } else if menu_shown {
                clear_ui_menu(&mut ui_menu, &ui_port);
                menu_shown = false;
            }

            if on_help_page {
                draw::draw_help_page(
                    &mut display,
                    MODULE_DOCSTRING,
                    bootinfo.manifest.help.as_ref(),
                    h_active,
                    v_active,
                    opts.help.scroll.value,
                    opts.display.ui_hue.value,
                )
                .ok();
            }

            sync_ui_overlay_csrs(
                &overlay_periph,
                h_active,
                v_active,
                opts.misc.rotation.value.clone(),
                menu_shown,
                opts.display.ui_hue.value,
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
                    app.ui.opts.tracker.page.value = Page::Scope1;
                    app.ui.external_modify();
                    if let Some(ref mut flash_persist) = flash_persist_opt {
                        flash_persist.erase_all().unwrap();
                    }
                });
            }

            scope.set_hue(opts.scope2.hue.value);
            scope.set_intensity(opts.scope2.intensity.value);
            scope.set_trigger_level(opts.scope2.trig_lvl.value);
            let (sppd_x, sppd) = scope.pixels_per_div();
            let xscale = xscale_for_full_width(h_active, sppd_x);
            scope.set_xscale(xscale);
            scope.set_timebase(opts.scope2.timebase.value);
            let (plot_x_lo, plot_x_hi, plot_y_lo, plot_y_hi) =
                waveform_plot_bounds(h_active, v_active);
            scope.set_plot_region(plot_x_lo, plot_x_hi, plot_y_lo, plot_y_hi);

            let ypos = [opts.scope1.ypos0.value, opts.scope1.ypos1.value,
                         opts.scope1.ypos2.value, opts.scope1.ypos3.value];
            let yscale = [opts.scope1.yscale0.value, opts.scope1.yscale1.value,
                          opts.scope1.yscale2.value, opts.scope1.yscale3.value];
            let vis = [opts.scope1.vis0.value, opts.scope1.vis1.value,
                       opts.scope1.vis2.value, opts.scope1.vis3.value];
            for ch in 0..4usize {
                scope.set_yscale_ch(ch, yscale[ch]);
                scope.set_ypos_px(ch, ypos[ch] * (sppd / 4) as i16);
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
                w.grid_style().bits(grid_style);
                w.grid_pixel().bits(((opts.display.grid_i.value as u8) << 4) | opts.display.ui_hue.value)
            });

            display.rotate(&opts.misc.rotation.value);

            scope.set_enabled(
                true,
                opts.scope2.trig_mode.value == TriggerMode::Always,
            );

            debug_frame = debug_frame.wrapping_add(1);
            if debug_frame % 600 == 0 {
                let st = scope.debug_status();
                let ct = scope.debug_counts();
                let (ix, iy) = scope.debug_probe();
                info!(
                    "scope dbg st={:#010x} ct={:#010x} ncols={:#06x} td={:#010x} ix={} iy={}",
                    st,
                    ct,
                    scope.debug_ncols(),
                    scope.debug_timebase(),
                    ix,
                    iy,
                );
            }

            first = false;
        }
    })
}
