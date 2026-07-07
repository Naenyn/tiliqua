#![no_std]
#![no_main]

use core::cell::RefCell;
use critical_section::Mutex;
use irq::handler;
use log::{info, warn};
use riscv_rt::entry;

use opts::persistence::*;
use opts::Options;
use tiliqua_fw::*;
use tiliqua_hal::dma_framebuffer::DMAFramebuffer;
use tiliqua_hal::embedded_graphics::prelude::*;
use tiliqua_hal::embedded_graphics::primitives::{PrimitiveStyle, Rectangle};
use tiliqua_hal::persist::Persist;
use tiliqua_lib::calibration::*;
use tiliqua_lib::color::HI8;
use tiliqua_lib::palette::ColorPalette;
use tiliqua_lib::*;

use options::*;
use pac::constants::*;

pub const TIMER0_ISR_PERIOD_MS: u32 = 5;
const FRAMEBUFFER_REGION_BYTES: usize = 0x0010_0000;

fn clear_framebuffer_region(base: usize) {
    let framebuffer_words = base as *mut u32;
    for offset in 0..(FRAMEBUFFER_REGION_BYTES / core::mem::size_of::<u32>()) {
        unsafe {
            core::ptr::write_volatile(framebuffer_words.add(offset), 0);
        }
    }
    riscv::asm::fence();
}

fn clear_3d_framebuffers() {
    clear_framebuffer_region(PSRAM_FB_BASE);
    clear_framebuffer_region(PSRAM_FB_BASE + FRAMEBUFFER_REGION_BYTES);
}

fn clear_help_text_window<D>(
    display: &mut D,
    h_active: u32,
    v_active: u32,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    let x = h_active / 2 - 292;
    let y = v_active / 2 - 172;
    Rectangle::new(
        Point::new(x as i32, y as i32),
        Size::new(584, 390),
    )
    .into_styled(PrimitiveStyle::with_fill(HI8::BLACK))
    .draw(display)
}

fn hash_menu_bytes(mut hash: u32, bytes: &[u8]) -> u32 {
    for byte in bytes {
        hash ^= *byte as u32;
        hash = hash.wrapping_mul(0x0100_0193);
    }
    hash
}

/// Compact identity for exactly what draw_options renders. This avoids
/// flooding the shared framebuffer plotter with identical menu redraws while
/// the encoder visibility timer remains active.
fn menu_fingerprint(opts: &Opts) -> u32 {
    let mut hash = 0x811c_9dc5;
    hash = hash_menu_bytes(hash, opts.page().value().as_bytes());
    hash = hash_menu_bytes(hash, &[opts.modify() as u8]);
    hash = hash_menu_bytes(
        hash,
        &[opts.selected().map(|index| index as u8).unwrap_or(0xff)],
    );
    for option in opts.view().options() {
        hash = hash_menu_bytes(hash, option.name().as_bytes());
        hash = hash_menu_bytes(hash, option.value().as_bytes());
    }
    hash
}

/// Rotate an RGB color around the HSV hue wheel in one of sixteen steps.
fn rotate_rgb_hue((r, g, b): (u8, u8, u8), shift: u8) -> (u8, u8, u8) {
    let r = r as i32;
    let g = g as i32;
    let b = b as i32;
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let delta = max - min;
    if delta == 0 {
        return (r as u8, g as u8, b as u8);
    }

    // Hue is represented as six 256-step sectors.
    let mut hue = if max == r {
        256 * (g - b) / delta
    } else if max == g {
        512 + 256 * (b - r) / delta
    } else {
        1024 + 256 * (r - g) / delta
    };
    if hue < 0 {
        hue += 1536;
    }
    hue = (hue + (shift as i32 * 96)) % 1536;

    let sector = hue / 256;
    let fraction = hue % 256;
    let rising = min + delta * fraction / 256;
    let falling = max - delta * fraction / 256;
    let (rr, gg, bb) = match sector {
        0 => (max, rising, min),
        1 => (falling, max, min),
        2 => (min, max, rising),
        3 => (min, falling, max),
        4 => (rising, min, max),
        _ => (max, min, falling),
    };
    (rr as u8, gg as u8, bb as u8)
}

/// Program SPECTO's palette. Scalar heat maps use each hardware hue column
/// for a rotated version, keeping the plot hue control meaningful.
fn write_specto_palette(palette: ColorPalette, video: &mut impl DMAFramebuffer) {
    if palette.heatmap_color(0).is_none() {
        palette.write_to_hardware(video);
        return;
    }
    for intensity in 0..16u8 {
        for hue in 0..16u8 {
            let (r, g, b) = rotate_rgb_hue(
                palette.heatmap_color(intensity).unwrap(), hue);
            video.set_palette_rgb(intensity, hue, r, g, b);
        }
    }
}

/// Integer sine/cosine for the 15-degree camera steps, in Q8 format.
fn sin_cos_q8(angle: i8) -> (i32, i32) {
    let (sin, cos) = match angle.abs() {
        0 => (0, 256),
        15 => (66, 247),
        30 => (128, 222),
        45 => (181, 181),
        60 => (222, 128),
        75 => (247, 66),
        _ => (256, 0),
    };
    (if angle < 0 { -sin } else { sin }, cos)
}

fn mul_q8(a: i32, b: i32) -> i32 {
    (a * b) >> 8
}

/// Build two rows of an Euler-rotated orthographic camera matrix. The base
/// projection keeps frequency horizontal, amplitude vertical and sends time
/// away from the viewer toward the upper-right of the display.
fn projection_matrix(rot_x: i8, rot_y: i8, rot_z: i8) -> ([i16; 3], [i16; 3]) {
    let (sx, cx) = sin_cos_q8(rot_x);
    let (sy, cy) = sin_cos_q8(rot_y);
    let (sz, cz) = sin_cos_q8(rot_z);

    // R = Rz * Ry * Rx, Q8 throughout.
    let rotation = [
        [
            mul_q8(cz, cy),
            mul_q8(mul_q8(cz, sy), sx) - mul_q8(sz, cx),
            mul_q8(mul_q8(cz, sy), cx) + mul_q8(sz, sx),
        ],
        [
            mul_q8(sz, cy),
            mul_q8(mul_q8(sz, sy), sx) + mul_q8(cz, cx),
            mul_q8(mul_q8(sz, sy), cx) - mul_q8(cz, sx),
        ],
        [-sy, mul_q8(cy, sx), mul_q8(cy, cx)],
    ];
    let base_x = [384, 0, 90];
    let base_y = [0, -320, -96];
    let mut out_x = [0i16; 3];
    let mut out_y = [0i16; 3];
    for column in 0..3 {
        let mut x = 0;
        let mut y = 0;
        for row in 0..3 {
            x += mul_q8(base_x[row], rotation[row][column]);
            y += mul_q8(base_y[row], rotation[row][column]);
        }
        out_x[column] = x as i16;
        out_y[column] = y as i16;
    }
    (out_x, out_y)
}

struct App {
    ui: ui::UI<Encoder0, EurorackPmod0, I2c0, Opts>,
}

impl App {
    fn new(opts: Opts) -> Self {
        let peripherals = unsafe { pac::Peripherals::steal() };
        let encoder = Encoder0::new(peripherals.ENCODER0);
        let i2cdev = I2c0::new(peripherals.I2C0);
        let pca9635 = hal::pca9635::Pca9635Driver::new(i2cdev);
        let pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
        Self {
            ui: ui::UI::new(opts, TIMER0_ISR_PERIOD_MS, encoder, pca9635, pmod),
        }
    }
}

fn timer0_handler(app: &Mutex<RefCell<App>>) {
    critical_section::with(|cs| app.borrow_ref_mut(cs).ui.update());
}

#[entry]
fn main() -> ! {
    let peripherals = pac::Peripherals::take().unwrap();
    let sysclk = pac::clock::sysclk();
    let serial = Serial0::new(peripherals.UART0);
    let mut timer = Timer0::new(peripherals.TIMER0, sysclk);
    let mut persist = Persist0::new(peripherals.PERSIST_PERIPH);
    let spiflash = SPIFlash0::new(peripherals.SPIFLASH_CTRL, SPIFLASH_BASE, SPIFLASH_SZ_BYTES);

    tiliqua_fw::handlers::logger_init(serial);
    info!("Hello from Tiliqua SPECTO!");

    let bootinfo = unsafe { bootinfo::BootInfo::from_addr(BOOTINFO_BASE) }.unwrap();
    let modeline = bootinfo
        .modeline
        .maybe_override_fixed(FIXED_MODELINE, CLOCK_DVI_HZ);

    // The 3D renderer alternates between two 1 MiB framebuffer regions. PSRAM
    // is not initialized at boot. Clear both regions before enabling video so
    // random power-on contents cannot flash as the buffers are exchanged.
    // Firmware begins at +0x200000, immediately after these two regions.
    // Use ordinary RV32 stores rather than the legacy VexRiscv cache-flush
    // custom instruction: SPECTO runs on VexiiRiscv, where that instruction
    // traps before the framebuffer/DVI peripheral can be enabled. Sequential
    // volatile writes naturally evict the visible portions of both buffers;
    // any final dirty cache lines lie in the unused padding after buffer 1.
    clear_3d_framebuffers();

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

    let mut i2cdev1 = I2c1::new(peripherals.I2C1);
    let mut pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
    CalibrationConstants::load_or_default(&mut i2cdev1, &mut pmod);

    let mut opts = Opts::default();
    opts.misc.rotation.value = modeline.rotate.clone();
    let mut flash_persist_opt =
        if let Some(storage_window) = bootinfo.manifest.get_option_storage_window() {
            let mut flash_persist = FlashOptionsPersistence::new(spiflash, storage_window);
            flash_persist.load_options(&mut opts).unwrap();
            Some(flash_persist)
        } else {
            warn!("No option storage region: disable persistent storage");
            None
        };
    // Low quality is no longer exposed because it loses too much spectral
    // structure. Migrate a previously saved Low selection to Medium while
    // preserving the enum discriminants used by existing saved High values.
    if opts.view_3d.quality.value == Quality3d::Low {
        opts.view_3d.quality.value = Quality3d::Medium;
    }
    // 3D renderer work should boot directly into the live 3D view regardless
    // of older saved SPECTO settings. Static remains available from the 3D
    // menu as a deterministic framebuffer diagnostic.
    opts.spectro.mode.value = DisplayMode::Spectrograph;
    opts.spectro.view.value = ViewMode::ThreeD;
    opts.view_3d.source.value = Source3d::Live;

    let mut last_palette = opts.display.palette.value;
    let app = Mutex::new(RefCell::new(App::new(opts)));
    handler!(timer0 = || timer0_handler(&app));

    irq::scope(|s| {
        s.register(handlers::Interrupt::TIMER0, timer0);
        timer.enable_tick_isr(TIMER0_ISR_PERIOD_MS, pac::Interrupt::TIMER0);

        let spectro = peripherals.SPECTROGRAM_PERIPH;
        let overlay = peripherals.OVERLAY_PERIPH;
        let mut first = true;
        let mut current_fb_base = PSRAM_FB_BASE as u32;
        let mut last_on_help_page = false;
        let mut last_view_3d = false;
        let mut last_help_scroll = 0;
        // Each physical framebuffer retains UI independently. Remember the
        // exact menu last drawn into each one so changed values, selection
        // markers, and timeout hiding can be erased without clearing a large
        // rectangle through the pixel plotter.
        let mut menu_fb0: Option<(Opts, u32, u32, u32)> = None;
        let mut menu_fb1: Option<(Opts, u32, u32, u32)> = None;

        loop {
            let h_active = display.size().width;
            let v_active = display.size().height;
            let (opts, draw_options, save_opts, wipe_opts) = critical_section::with(|cs| {
                let mut app = app.borrow_ref_mut(cs);
                let save_opts = app.ui.opts.misc.save_opts.poll();
                let wipe_opts = app.ui.opts.misc.wipe_opts.poll();
                (
                    app.ui.opts.clone(),
                    app.ui.draw(),
                    save_opts,
                    wipe_opts,
                )
            });
            let on_help_page = opts.tracker.page.value == Page::Help;
            let spectrum_mode = opts.spectro.mode.value == DisplayMode::Spectrum;
            let view_3d = !spectrum_mode && opts.spectro.view.value == ViewMode::ThreeD;
            let help_scroll = opts.help.scroll.value;
            let help_page_entered = on_help_page && !last_on_help_page;
            // In 3D, keep transient UI in the lower half of the palette. The
            // literal back-buffer renderer also uses low plot hues so the
            // legacy tagged cleanup path never touches visible 3D pixels.
            let ui_hue = if view_3d {
                opts.display.ui_hue.value & 7
            } else {
                opts.display.ui_hue.value
            };
            let surface_status = spectro.status().read();
            let display_buffer = view_3d
                && surface_status.surface_valid().bit()
                && surface_status.display_buffer().bit();
            let desired_fb_base = PSRAM_FB_BASE as u32
                + if display_buffer { 0x0010_0000 } else { 0 };
            let framebuffer_swapped = desired_fb_base != current_fb_base;
            if framebuffer_swapped {
                display.update_fb_base(desired_fb_base);
                current_fb_base = desired_fb_base;
            }

            // Help text and the 3D view are full-screen framebuffer layers.
            // Clear both physical buffers at mode boundaries, but do not do a
            // full clear for help scrolling; only the text viewport changes.
            let help_scroll_changed =
                on_help_page && (!last_on_help_page || help_scroll != last_help_scroll);
            let fullscreen_layer_changed =
                first || (view_3d != last_view_3d) ||
                (on_help_page != last_on_help_page);
            if fullscreen_layer_changed {
                if view_3d || last_view_3d || on_help_page || last_on_help_page {
                    clear_3d_framebuffers();
                    menu_fb0 = None;
                    menu_fb1 = None;
                    if current_fb_base != desired_fb_base {
                        display.update_fb_base(desired_fb_base);
                        current_fb_base = desired_fb_base;
                    }
                }
            }
            last_on_help_page = on_help_page;
            last_view_3d = view_3d;
            last_help_scroll = help_scroll;

            if opts.display.palette.value != last_palette || first {
                write_specto_palette(opts.display.palette.value, &mut display);
                last_palette = opts.display.palette.value;
            }

            let (menu_x, menu_y) = if on_help_page {
                (h_active / 2 - 30, v_active - 100)
            } else {
                (h_active - 200, v_active / 2)
            };
            let menu_visible = draw_options || on_help_page || first;
            let menu_hash = menu_fingerprint(&opts);
            let menu_slot = if display_buffer {
                &mut menu_fb1
            } else {
                &mut menu_fb0
            };
            let menu_changed = menu_slot.as_ref().map(
                |(_, old_x, old_y, old_hash)| {
                    *old_x != menu_x || *old_y != menu_y ||
                        *old_hash != menu_hash
                }).unwrap_or(menu_visible);
            // In 3D, each completed surface starts by clearing the back
            // buffer. After the swap, the current physical buffer may no
            // longer contain the cached menu even if its fingerprint matches.
            // Redraw visible menus on 3D swaps, but avoid the old unconditional
            // erase/redraw loop when no menu is visible.
            let menu_invalidated_by_3d_swap =
                view_3d && framebuffer_swapped && menu_visible;
            let menu_visibility_changed =
                menu_visible != menu_slot.is_some();
            if first || menu_changed || menu_visibility_changed ||
                    menu_invalidated_by_3d_swap {
                if let Some((old_opts, old_x, old_y, _)) = menu_slot.take() {
                    draw::erase_options(
                        &mut display, &old_opts, old_x, old_y).ok();
                }
                if menu_visible {
                    draw::draw_options(
                        &mut display, &opts, menu_x, menu_y, ui_hue).ok();
                    *menu_slot = Some((
                        opts.clone(), menu_x, menu_y, menu_hash));
                }
            } else if menu_visible && !view_3d {
                // In the beam-raced 2D modes, framebuffer persistence also
                // decays UI pixels. Refresh the unchanged visible menu as the
                // original renderer did; unlike a state change, this needs no
                // erase pass. In 3D, the menu is stable in the front buffer,
                // so redundant refresh traffic remains disabled.
                draw::draw_options(
                    &mut display, &opts, menu_x, menu_y, ui_hue).ok();
            }
            if draw_options || on_help_page || first || framebuffer_swapped {
                draw::draw_name(
                    &mut display,
                    h_active / 2,
                    v_active - 50,
                    ui_hue,
                    &bootinfo.manifest.name,
                    &bootinfo.manifest.tag,
                    &modeline,
                )
                .ok();
            }

            if on_help_page {
                if help_page_entered || help_scroll_changed || first {
                    clear_help_text_window(
                        &mut display,
                        h_active,
                        v_active,
                    )
                    .ok();
                    draw::draw_help(
                        &mut display,
                        h_active / 2 - 280,
                        v_active / 2 - 150,
                        opts.help.scroll.value,
                        MODULE_DOCSTRING,
                        ui_hue,
                    )
                    .ok();
                }
                if help_page_entered || first {
                    if let Some(help) = bootinfo.manifest.help.as_ref() {
                        draw::draw_tiliqua(
                            &mut display,
                            (h_active / 2 - 80) as i32,
                            (v_active / 2) as i32 - 330,
                            ui_hue,
                            help.io_left.each_ref().map(|s| s.as_str()),
                            help.io_right.each_ref().map(|s| s.as_str()),
                        )
                        .ok();
                    }
                }
            }

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
                    if let Some(ref mut flash_persist) = flash_persist_opt {
                        flash_persist.erase_all().unwrap();
                    }
                });
            }

            spectro.flags().write(|w| unsafe {
                w.enable().bit(!on_help_page);
                // Explicit history already provides the temporal dimension in
                // 3D. Keep its analyzer response stable and reserve phosphor
                // smoothing/persistence as a user-selectable 2D treatment.
                w.phosphor().bit(
                    !spectrum_mode
                        && opts.spectro.view.value == ViewMode::TwoD
                        && opts.spectro.style.value == RenderStyle::Phosphor,
                );
                w.axes().bit(opts.display.axes.value == OnOff::On);
                w.input_ch().bits(opts.spectro.input.value.hw_index());
                w.view_3d().bit(view_3d);
                w.spectrum_mode().bit(spectrum_mode);
                w.display_ack().bit(display_buffer)
            });
            spectro
                .gain()
                .write(|w| unsafe { w.value().bits(opts.spectro.gain.value) });
            spectro
                .range()
                .write(|w| unsafe { w.value().bits(opts.spectro.range.value.hw_index()) });
            spectro
                .rate()
                .write(|w| unsafe { w.value().bits(opts.spectro.rate.value.hw_index()) });
            spectro
                .persistence()
                .write(|w| unsafe { w.value().bits(opts.spectro.persist.value.hw_index()) });
            spectro
                .hue()
                .write(|w| unsafe { w.value().bits(opts.display.hue.value) });
            spectro.timings().write(|w| unsafe {
                w.h_active().bits(h_active as u16);
                w.v_active().bits(v_active as u16);
                w.menu_visible().bit(menu_visible)
            });
            let (projection_x, projection_y) = projection_matrix(
                opts.view_3d.rot_x.value,
                opts.view_3d.rot_y.value,
                opts.view_3d.rot_z.value,
            );
            spectro.projection_x().write(|w| unsafe {
                w.frequency().bits(projection_x[0] as u16);
                w.amplitude().bits(projection_x[1] as u16);
                w.time().bits(projection_x[2] as u16)
            });
            spectro.projection_y().write(|w| unsafe {
                w.frequency().bits(projection_y[0] as u16);
                w.amplitude().bits(projection_y[1] as u16);
                w.time().bits(projection_y[2] as u16)
            });
            spectro.config_3d().write(|w| unsafe {
                w.quality().bits(opts.view_3d.quality.value.hw_index());
                w.static_surface().bit(
                    opts.view_3d.source.value.hw_index() != 0)
            });
            spectro.spectrum_config().write(|w| unsafe {
                w.style().bit(opts.spectro.spectrum_style.value.hw_index() != 0);
                w.bands().bits(opts.spectro.bands.value.hw_index());
                w.fill().bits(opts.spectro.fill.value.hw_index());
                w.peaks().bits(opts.spectro.peaks.value.hw_index());
                w.smoothing().bits(opts.spectro.smoothing.value.hw_index());
                w.scale().bit(opts.spectro.scale.value.hw_index() != 0)
            });

            // SPECTO draws its own plot axes. Keep the general-purpose XBEAM
            // grid disabled for the MVP so the analytical display stays clean.
            overlay.flags().write(|w| unsafe {
                w.grid_style().bits(0);
                w.grid_pixel().bits(0)
            });

            if view_3d {
                // The 3D view uses explicit double-buffered surfaces. The
                // gateware pauses persistence in 3D; this write is kept benign
                // in case that pause is ever relaxed while debugging.
                persist.set_cleanup();
            } else {
                persist.set_persistence(if on_help_page { 64 } else { 24 });
            }
            display.rotate(&opts.misc.rotation.value);
            first = false;
        }
    })
}
