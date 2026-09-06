#![no_std]
#![no_main]

use core::{cell::RefCell, fmt::Write};
use critical_section::Mutex;
use heapless::String;
use irq::handler;
use log::{info, warn};
use riscv_rt::entry;

use opts::Options;
use opts::persistence::{FlashOptionsPersistence, OptionsPersistence};
use tiliqua_fw::*;
use tiliqua_hal::dma_framebuffer::DMAFramebuffer;
use tiliqua_hal::embedded_graphics::prelude::*;
use tiliqua_hal::embedded_graphics::primitives::{
    PrimitiveStyle, PrimitiveStyleBuilder, Rectangle,
};
use tiliqua_hal::embedded_graphics::{
    mono_font::{ascii::FONT_9X15_BOLD, MonoTextStyle},
    text::Text,
};
use tiliqua_lib::calibration::*;
use tiliqua_lib::color::HI8;
use tiliqua_lib::palette::ColorPalette;
use tiliqua_lib::*;

use options::*;
use pac::constants::*;

pub const TIMER0_ISR_PERIOD_MS: u32 = 5;
const FRAMEBUFFER_REGION_BYTES: usize = 0x0010_0000;
// This matches the gateware's protected menu region. Keep the normal panel
// fixed to the largest menu so its border and black analyzer cutout never
// jump as conditional options appear or disappear.
const MENU_PANEL_WIDTH: u32 = 264;
const MENU_PANEL_HEIGHT: u32 = 138;
const MENU_PANEL_X_OFFSET: i32 = -92;
const MENU_PANEL_Y_OFFSET: i32 = -18;

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

fn menu_panel_rect(pos_x: u32, pos_y: u32) -> Rectangle {
    Rectangle::new(
        Point::new(
            pos_x as i32 + MENU_PANEL_X_OFFSET,
            pos_y as i32 + MENU_PANEL_Y_OFFSET,
        ),
        Size::new(MENU_PANEL_WIDTH, MENU_PANEL_HEIGHT),
    )
}

fn draw_menu<D>(
    display: &mut D,
    opts: &Opts,
    pos_x: u32,
    pos_y: u32,
    hue: u8,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    if opts.tracker.page.value == Page::Help {
        return draw::draw_options(display, opts, pos_x, pos_y, hue);
    }
    let border = PrimitiveStyleBuilder::new()
        .stroke_color(HI8::new(hue, 10))
        .stroke_width(1)
        .build();
    menu_panel_rect(pos_x, pos_y)
        .into_styled(border)
        .draw(display)?;
    draw::draw_options(display, opts, pos_x, pos_y, hue)
}

fn erase_menu<D>(
    display: &mut D,
    opts: &Opts,
    pos_x: u32,
    pos_y: u32,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    draw::erase_options(display, opts, pos_x, pos_y)?;
    if opts.tracker.page.value == Page::Help {
        return Ok(());
    }
    menu_panel_rect(pos_x, pos_y)
        .into_styled(PrimitiveStyle::with_stroke(HI8::BLACK, 1))
        .draw(display)
}

fn draw_fps<D>(
    display: &mut D,
    fps_tenths: u32,
    hue: u8,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    let mut label: String<16> = String::new();
    write!(label, "{}.{:01} FPS", fps_tenths / 10, fps_tenths % 10).ok();
    Text::new(
        &label,
        Point::new(16, 24),
        MonoTextStyle::new(&FONT_9X15_BOLD, HI8::new(hue, 15)),
    )
    .draw(display)
    .map(|_| ())
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

fn scale_rgb_visible((r, g, b): (u8, u8, u8), intensity: u8) -> (u8, u8, u8) {
    let scale = if intensity == 0 {
        0
    } else {
        4 + ((intensity as u16 * 11) / 15)
    };
    (
        ((r as u16 * scale) / 15) as u8,
        ((g as u16 * scale) / 15) as u8,
        ((b as u16 * scale) / 15) as u8,
    )
}

fn max3(a: u8, b: u8, c: u8) -> u8 {
    let ab = if a > b { a } else { b };
    if ab > c { ab } else { c }
}

fn scale_rgb_to_level((r, g, b): (u8, u8, u8), target_level: u8) -> (u8, u8, u8) {
    let source_level = max3(r, g, b);
    if target_level == 0 || source_level == 0 {
        return (0, 0, 0);
    }
    (
        ((r as u16 * target_level as u16) / source_level as u16) as u8,
        ((g as u16 * target_level as u16) / source_level as u16) as u8,
        ((b as u16 * target_level as u16) / source_level as u16) as u8,
    )
}

fn scale_rgb_like_palette(
    palette: ColorPalette,
    rgb: (u8, u8, u8),
    intensity: u8,
) -> (u8, u8, u8) {
    if let Some((r, g, b)) = palette.heatmap_color(intensity) {
        scale_rgb_to_level(rgb, max3(r, g, b))
    } else {
        scale_rgb_visible(rgb, intensity)
    }
}

/// Program CASCADO's shared palette. Physical hue zero belongs to UI and
/// axes; terrain uses the remaining entries for level/age or frequency/level.
fn write_cascado_palette(
    palette: ColorPalette,
    video: &mut impl DMAFramebuffer,
    frequency_ramp: bool,
    age_fade: bool,
    hue_shift: u8,
    ui_hue: u8,
) {
    // Framebuffer UI and renderer pixels share one 8-bit hardware palette.
    // Reserve physical hue column zero for UI, axes and erase pixels. The
    // selected UI hue is baked into that column, leaving the other fifteen
    // columns exclusively available to the surface renderer.
    for intensity in 0..16u8 {
        let (r, g, b) = ColorPalette::Linear.color(intensity, ui_hue);
        video.set_palette_rgb(intensity, 0, r, g, b);
    }

    if frequency_ramp {
        for intensity in 0..16u8 {
            for hue in 1..16u8 {
                let bright_intensity = if intensity == 0 {
                    0
                } else {
                    4 + ((intensity as u16 * 11) / 15) as u8
                };
                // Fifteen renderer columns span the complete frequency
                // palette while column zero remains reserved for the UI.
                let position = (((hue - 1) as u16 * 15 + 7) / 14) as u8;
                let (r, g, b) = scale_rgb_like_palette(
                    palette,
                    palette.frequency_color(position),
                    bright_intensity,
                );
                video.set_palette_rgb(intensity, hue, r, g, b);
            }
        }
        return;
    }

    if age_fade {
        // The 240 renderer entries provide 30 amplitude colors x 8 age-
        // brightness steps. Age scales RGB uniformly across almost the full
        // brightness range, so an old surface keeps the same amplitude color
        // rather than sliding through the heat map while depth remains clear.
        for intensity in 0..16u8 {
            for hue in 1..16u8 {
                let level = (intensity & 1) * 15 + (hue - 1);
                let age = intensity >> 1;
                let position = level as u16 * 15;
                let lower = (position / 29) as u8;
                let fraction = position % 29;
                let upper = core::cmp::min(lower + 1, 15);
                let (lo, hi, rotate) = match palette.heatmap_color(lower) {
                    Some(lo) => (lo, palette.heatmap_color(upper).unwrap(), true),
                    None => (
                        palette.color(lower, hue_shift),
                        palette.color(upper, hue_shift),
                        false,
                    ),
                };
                let interpolate = |a: u8, b: u8| -> u8 {
                    (((a as u32 * (29 - fraction) as u32)
                        + (b as u32 * fraction as u32) + 14) / 29) as u8
                };
                let rgb = (
                    interpolate(lo.0, hi.0),
                    interpolate(lo.1, hi.1),
                    interpolate(lo.2, hi.2),
                );
                let (r, g, b) = if rotate {
                    rotate_rgb_hue(rgb, hue_shift)
                } else {
                    rgb
                };
                let brightness = 15 - age * 2;
                video.set_palette_rgb(
                    intensity,
                    hue,
                    ((r as u16 * brightness as u16 + 7) / 15) as u8,
                    ((g as u16 * brightness as u16 + 7) / 15) as u8,
                    ((b as u16 * brightness as u16 + 7) / 15) as u8,
                );
            }
        }
        return;
    }

    // Without age fading, the renderer uses 60 amplitude colors. Four groups
    // occupy intensity rows 0..3, with fifteen colors per row; physical hue
    // column zero remains reserved for the UI.
    for intensity in 0..16u8 {
        for hue in 1..16u8 {
            let group = intensity & 3;
            let level = group * 15 + (hue - 1);
            let position = level as u16 * 15;
            let lower = (position / 59) as u8;
            let fraction = position % 59;
            let upper = core::cmp::min(lower + 1, 15);
            let (lo, hi, rotate) = match palette.heatmap_color(lower) {
                Some(lo) => (lo, palette.heatmap_color(upper).unwrap(), true),
                None => (
                    palette.color(lower, hue_shift),
                    palette.color(upper, hue_shift),
                    false,
                ),
            };
            let interpolate = |a: u8, b: u8| -> u8 {
                (((a as u32 * (59 - fraction) as u32)
                    + (b as u32 * fraction as u32) + 29) / 59) as u8
            };
            let rgb = (
                interpolate(lo.0, hi.0),
                interpolate(lo.1, hi.1),
                interpolate(lo.2, hi.2),
            );
            let (r, g, b) = if rotate {
                rotate_rgb_hue(rgb, hue_shift)
            } else {
                rgb
            };
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
    let product = a * b;
    // Arithmetic right shift floors negative products. Round both signs to
    // the nearest Q8 value instead so rotations do not acquire a directional
    // bias from repeated matrix multiplies.
    let correction = if product < 0 { 127 } else { 128 };
    (product + correction) >> 8
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

fn sanitize_options(opts: &mut Opts) {
    if opts.style.quality.value == Quality3d::Low {
        opts.style.quality.value = Quality3d::Medium;
    }
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
    critical_section::with(|cs| app.borrow_ref_mut(cs).ui.update());
}

#[entry]
fn main() -> ! {
    let peripherals = pac::Peripherals::take().unwrap();
    let sysclk = pac::clock::sysclk();
    let serial = Serial0::new(peripherals.UART0);
    let mut timer = Timer0::new(peripherals.TIMER0, sysclk);
    let spiflash = SPIFlash0::new(peripherals.SPIFLASH_CTRL, SPIFLASH_BASE, SPIFLASH_SZ_BYTES);

    tiliqua_fw::handlers::logger_init(serial);
    info!("Hello from Tiliqua CASCADO!");

    let bootinfo = unsafe { bootinfo::BootInfo::from_addr(BOOTINFO_BASE) }.unwrap();
    let modeline = bootinfo
        .modeline
        .maybe_override_fixed(FIXED_MODELINE, CLOCK_DVI_HZ);

    // The 3D renderer alternates between two 1 MiB framebuffer regions. PSRAM
    // is not initialized at boot. Clear both regions before enabling video so
    // random power-on contents cannot flash as the buffers are exchanged.
    // Firmware begins at +0x200000, immediately after these two regions.
    // Use ordinary RV32 stores rather than the legacy VexRiscv cache-flush
    // custom instruction: CASCADO runs on VexiiRiscv, where that instruction
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
    sanitize_options(&mut opts);
    // Page selection is navigation state, not a sound/display preference.
    // Always open CASCADO on its first page even if options were saved from
    // another page, and never resume an in-progress edit across a reboot.
    opts.tracker.page.value = Page::Cascado;
    opts.tracker.selected = None;
    opts.tracker.modify = false;

    let mut last_palette = opts.display.palette.value;
    let mut last_color_by = opts.style.color_by.value;
    let mut last_age_fade = opts.style.age_fade.value;
    let mut last_plot_hue = opts.display.hue.value;
    let mut last_ui_hue = opts.menu.ui_hue.value;
    let mut last_hide = opts.menu.hide.value;
    let mut last_edit_hide = opts.menu.edit_hide.value;
    let app = Mutex::new(RefCell::new(App::new(opts)));
    handler!(timer0 = || timer0_handler(&app));

    irq::scope(|s| {
        s.register(handlers::Interrupt::TIMER0, timer0);
        timer.enable_tick_isr(TIMER0_ISR_PERIOD_MS, pac::Interrupt::TIMER0);

        let spectro = peripherals.SPECTROGRAM_PERIPH;
        let mut first = true;
        let mut current_fb_base = PSRAM_FB_BASE as u32;
        let mut last_on_help_page = false;
        let mut last_help_scroll = 0;
        let mut help_waiting_for_renderer = false;
        // Count completed 3D surface swaps, rather than HDMI scan frames. This
        // is the user-visible CASCADO update rate and includes the small cost
        // of drawing this diagnostic into each newly completed framebuffer.
        let mut fps_window_start_ms = 0u32;
        let mut fps_window_frames = 0u32;
        let mut fps_tenths = 0u32;
        // Each physical framebuffer retains UI independently. Remember the
        // exact menu last drawn into each one so changed values, selection
        // markers, and timeout hiding can be erased without clearing a large
        // rectangle through the pixel plotter.
        let mut menu_fb0: Option<(Opts, u32, u32, u32)> = None;
        let mut menu_fb1: Option<(Opts, u32, u32, u32)> = None;

        loop {
            let (opts, draw_options, save_opts, wipe_opts, uptime_ms) = critical_section::with(|cs| {
                let mut app = app.borrow_ref_mut(cs);
                sanitize_options(&mut app.ui.opts);
                let save_opts = app.ui.opts.misc.save_opts.poll();
                let wipe_opts = app.ui.opts.misc.wipe_opts.poll();
                (
                    app.ui.opts.clone(),
                    app.ui.draw(),
                    save_opts,
                    wipe_opts,
                    app.ui.uptime_ms,
                )
            });
            // Apply the selected framebuffer rotation before asking for the
            // logical drawing dimensions. Gateware receives the same rotation
            // below so the projected surface and software UI remain aligned.
            display.rotate(&opts.misc.rotation.value);
            let h_active = display.size().width;
            let v_active = display.size().height;
            let on_help_page = opts.tracker.page.value == Page::Help;
            let help_scroll = opts.help.scroll.value;
            let help_page_entered = on_help_page && !last_on_help_page;
            if opts.menu.hide.value != last_hide {
                critical_section::with(|cs| {
                    app.borrow_ref_mut(cs)
                        .ui
                        .set_encoder_fade_ms(menu_hide_ms(opts.menu.hide.value));
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
            if help_page_entered {
                help_waiting_for_renderer = true;
            }
            // Physical hue zero is reserved by write_cascado_palette for
            // all software UI. The user's selected hue is baked into that
            // palette column rather than encoded into framebuffer pixels.
            let ui_hue = 0;
            let surface_status = spectro.status().read();
            // Help is a static framebuffer page. Suspend the autonomous 3D
            // renderer before clearing or drawing it, and keep scanning the
            // physical buffer that was visible on entry. Otherwise the 3D
            // state machine can clear/swap underneath the freshly drawn help
            // text even though analyzer capture itself is disabled.
            let help_renderer_ready =
                !help_waiting_for_renderer || surface_status.renderer_idle().bit();
            let help_page_became_ready =
                on_help_page && help_waiting_for_renderer && help_renderer_ready;
            let display_buffer = if on_help_page {
                current_fb_base != PSRAM_FB_BASE as u32
            } else {
                surface_status.surface_valid().bit()
                    && surface_status.display_buffer().bit()
            };
            // Publish a Help stop request before touching either framebuffer.
            // Normal 3D display acknowledgements remain below, after menu
            // drawing, so scanout can never reveal a half-drawn menu.
            if on_help_page {
                spectro.flags().write(|w| unsafe {
                    w.enable().bit(false);
                    w.axes().bit(opts.display.axes.value == OnOff::On);
                    w.input_ch().bits(opts.cascado.input.value.hw_index());
                    w.display_ack().bit(display_buffer)
                });
            }
            let desired_fb_base = PSRAM_FB_BASE as u32
                + if display_buffer { 0x0010_0000 } else { 0 };
            let framebuffer_swapped = desired_fb_base != current_fb_base;
            if framebuffer_swapped {
                display.update_fb_base(desired_fb_base);
                current_fb_base = desired_fb_base;
                if !on_help_page {
                    fps_window_frames = fps_window_frames.saturating_add(1);
                    let elapsed_ms = uptime_ms.wrapping_sub(fps_window_start_ms);
                    if elapsed_ms >= 1000 {
                        fps_tenths = fps_window_frames
                            .saturating_mul(10_000)
                            .saturating_add(elapsed_ms / 2)
                            / elapsed_ms;
                        fps_window_start_ms = uptime_ms;
                        fps_window_frames = 0;
                    }
                }
            }

            // Help text and the 3D view are full-screen framebuffer layers.
            // Clear both physical buffers at mode boundaries, but do not do a
            // full clear for help scrolling; only the text viewport changes.
            let help_scroll_changed =
                on_help_page && (!last_on_help_page || help_scroll != last_help_scroll);
            let fullscreen_layer_changed =
                first ||
                ((on_help_page != last_on_help_page) &&
                    (!on_help_page || help_renderer_ready)) ||
                help_page_became_ready;
            if fullscreen_layer_changed {
                clear_3d_framebuffers();
                menu_fb0 = None;
                menu_fb1 = None;
                if current_fb_base != desired_fb_base {
                    display.update_fb_base(desired_fb_base);
                    current_fb_base = desired_fb_base;
                }
            }
            last_on_help_page = on_help_page;
            last_help_scroll = help_scroll;

            if opts.display.palette.value != last_palette
                || opts.style.color_by.value != last_color_by
                || opts.style.age_fade.value != last_age_fade
                || opts.display.hue.value != last_plot_hue
                || opts.menu.ui_hue.value != last_ui_hue
                || first
            {
                write_cascado_palette(
                    opts.display.palette.value,
                    &mut display,
                    opts.style.color_by.value == ColorBy::Frequency,
                    opts.style.age_fade.value == OnOff::On,
                    opts.display.hue.value,
                    opts.menu.ui_hue.value,
                );
                last_palette = opts.display.palette.value;
                last_color_by = opts.style.color_by.value;
                last_age_fade = opts.style.age_fade.value;
                last_plot_hue = opts.display.hue.value;
                last_ui_hue = opts.menu.ui_hue.value;
            }

            let (menu_x, menu_y) = if on_help_page {
                (h_active / 2 - 30, v_active - 100)
            } else {
                (h_active - 200, v_active / 2)
            };
            let menu_visible = draw_options || on_help_page || first;
            critical_section::with(|cs| {
                app.borrow_ref_mut(cs).ui.set_menu_visible(menu_visible);
            });
            let ui_render_ready = !on_help_page || help_renderer_ready;
            if ui_render_ready {
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
                    framebuffer_swapped && menu_visible;
                let menu_visibility_changed =
                    menu_visible != menu_slot.is_some();
                if first || menu_changed || menu_visibility_changed ||
                        menu_invalidated_by_3d_swap {
                    if let Some((old_opts, old_x, old_y, _)) = menu_slot.take() {
                        erase_menu(
                            &mut display, &old_opts, old_x, old_y).ok();
                    }
                    if menu_visible {
                        draw_menu(
                            &mut display, &opts, menu_x, menu_y, ui_hue).ok();
                        *menu_slot = Some((
                            opts.clone(), menu_x, menu_y, menu_hash));
                    }
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
                if framebuffer_swapped && !on_help_page {
                    draw_fps(&mut display, fps_tenths, ui_hue).ok();
                }

                if on_help_page {
                    if help_page_entered || help_page_became_ready ||
                            help_scroll_changed || first {
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
                    if help_page_entered || help_page_became_ready || first {
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
            }
            if help_page_became_ready {
                help_waiting_for_renderer = false;
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
                    sanitize_options(&mut app.ui.opts);
                    if let Some(ref mut flash_persist) = flash_persist_opt {
                        flash_persist.erase_all().unwrap();
                    }
                });
            }

            // In normal 3D operation this acknowledgement deliberately comes
            // after menu drawing. The renderer waits for it before swapping at
            // VSync, so the next front buffer always contains a complete menu.
            spectro.flags().write(|w| unsafe {
                w.enable().bit(!on_help_page);
                w.axes().bit(opts.display.axes.value == OnOff::On);
                w.input_ch().bits(opts.cascado.input.value.hw_index());
                w.display_ack().bit(display_buffer)
            });
            spectro
                .gain()
                .write(|w| unsafe { w.value().bits(opts.cascado.gain.value) });
            spectro
                .range()
                .write(|w| unsafe { w.value().bits(opts.cascado.range.value.hw_index()) });
            spectro
                .rate()
                .write(|w| unsafe { w.value().bits(opts.cascado.rate.value.hw_index()) });
            spectro
                .hue()
                .write(|w| unsafe { w.value().bits(opts.display.hue.value) });
            spectro.noise_floor().write(|w| unsafe {
                w.value().bits(opts.display.noise_floor.value.hw_index())
            });
            spectro.timings().write(|w| unsafe {
                w.h_active().bits(h_active as u16);
                w.v_active().bits(v_active as u16)
            });
            let (projection_x, projection_y) = projection_matrix(
                opts.cascado.rot_x.value,
                opts.cascado.rot_y.value,
                opts.cascado.rot_z.value,
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
                w.quality().bits(opts.style.quality.value.hw_index());
                w.style().bit(opts.style.style.value == SurfaceStyle::Terrain);
                w.log_scale().bit(opts.style.scale.value == FrequencyScale::Log);
                w.age_fade().bit(opts.style.age_fade.value == OnOff::On);
                w.frequency_color().bit(opts.style.color_by.value == ColorBy::Frequency);
                w.ridges().bit(opts.style.ridges.value == OnOff::On)
            });

            first = false;
        }
    })
}
