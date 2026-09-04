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
use tiliqua_hal::embedded_graphics::primitives::{
    PrimitiveStyle, PrimitiveStyleBuilder, Rectangle,
};
use tiliqua_hal::embedded_graphics::{
    mono_font::{ascii::FONT_5X7, MonoTextStyle},
    text::Text,
};
use tiliqua_hal::persist::Persist;
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
const MENU_PANEL_HEIGHT: u32 = 156;
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

fn clear_help_text_window<D>(display: &mut D, h_active: u32, v_active: u32) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    let x = h_active / 2 - 292;
    let y = v_active / 2 - 172;
    Rectangle::new(Point::new(x as i32, y as i32), Size::new(584, 390))
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

fn erase_menu<D>(display: &mut D, opts: &Opts, pos_x: u32, pos_y: u32) -> Result<(), D::Error>
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

fn draw_axis_text<D>(
    display: &mut D,
    text: &str,
    x: i32,
    y: i32,
    color: HI8,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    // Text positions in the gateware used an 8-pixel cell with a 5x7 glyph.
    // The stock 5x7 framebuffer font has a six-pixel cell; preserving the
    // original anchor points keeps tick labels aligned while making them a
    // little less visually crowded.
    Text::new(
        text,
        Point::new(x, y + 7),
        MonoTextStyle::new(&FONT_5X7, color),
    )
    .draw(display)
    .map(|_| ())
}

fn axis_fingerprint(opts: &Opts, width: u32, height: u32) -> u32 {
    let frequency_ramp = opts.sonoro.mode.value == DisplayMode::Spectrum
        && matches!(
            opts.spectrum.fill.value,
            SpectrumFill::Freq | SpectrumFill::FreqReverse
        );
    width
        ^ height.rotate_left(12)
        ^ ((opts.display.axes.value == OnOff::On) as u32) << 24
        ^ ((opts.sonoro.mode.value == DisplayMode::Spectrum) as u32) << 25
        ^ ((opts.sonoro.range.value.hw_index() as u32) << 26)
        ^ ((opts.sonoro.rate.value.hw_index() as u32) << 28)
        ^ ((opts.spectrum.scale.value.hw_index() as u32) << 30)
        ^ ((frequency_ramp as u32) << 31)
        ^ ((opts.display.hue.value as u32) << 16)
}

fn draw_analyzer_axes<D>(
    display: &mut D,
    opts: &Opts,
    width: u32,
    height: u32,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    if opts.display.axes.value != OnOff::On {
        return Ok(());
    }

    let spectrum = opts.sonoro.mode.value == DisplayMode::Spectrum;
    let frequency_ramp = spectrum
        && matches!(
            opts.spectrum.fill.value,
            SpectrumFill::Freq | SpectrumFill::FreqReverse
        );
    let color = if frequency_ramp {
        HI8::new(15, 12)
    } else {
        HI8::new(opts.display.hue.value, 10)
    };
    let x_shift = if width >= 1024 { 2 } else { 1 };
    let y_shift = if height < 600 { 0 } else { 1 };
    let plot_w = 256i32 << x_shift;
    let plot_h = 256i32 << y_shift;
    let plot_x = (width as i32 - plot_w) / 2;
    let plot_y = (height as i32 - plot_h) / 2;
    let axis_pad = 3i32;

    let y_labels = if spectrum {
        ["    0", "  -24", "  -48", "  -72", "  -96"]
    } else {
        match opts.sonoro.range.value {
            FrequencyRange::Range24k => ["  24k", "  18k", "  12k", "   6k", "    0"],
            FrequencyRange::Range12k => ["  12k", "   9k", "   6k", "   3k", "    0"],
            FrequencyRange::Range6k => ["   6k", " 4.5k", "   3k", " 1.5k", "    0"],
            FrequencyRange::Range3k => ["   3k", "2.25k", " 1.5k", "  750", "    0"],
        }
    };
    let y_positions = [
        plot_y - 3,
        plot_y + plot_h / 4 - 3,
        plot_y + plot_h / 2 - 3,
        plot_y + plot_h - plot_h / 4 - 3,
        plot_y + plot_h - 8,
    ];
    for (label, y) in y_labels.iter().zip(y_positions) {
        draw_axis_text(display, label, plot_x - 48, y, color)?;
    }
    draw_axis_text(
        display,
        if spectrum { "AMP(dBFS)" } else { "FREQ (Hz)" },
        plot_x - 72,
        plot_y - 20,
        color,
    )?;

    let label_y = plot_y + plot_h + axis_pad + 5;
    if spectrum && opts.spectrum.scale.value == SpectrumScale::Log {
        let (col_100, col_1k, col_10k, end_label) = match opts.sonoro.range.value {
            FrequencyRange::Range24k => (75, 151, Some(226), " 20k"),
            FrequencyRange::Range12k => (83, 166, Some(248), " 12k"),
            FrequencyRange::Range6k => (92, 184, None, "  6k"),
            FrequencyRange::Range3k => (103, 206, None, "  3k"),
        };
        draw_axis_text(display, "  10", plot_x - axis_pad, label_y, color)?;
        draw_axis_text(
            display,
            " 100",
            plot_x + (col_100 << x_shift) - 12,
            label_y,
            color,
        )?;
        draw_axis_text(
            display,
            "  1k",
            plot_x + (col_1k << x_shift) - 12,
            label_y,
            color,
        )?;
        if let Some(column) = col_10k {
            draw_axis_text(
                display,
                " 10k",
                plot_x + (column << x_shift) - 12,
                label_y,
                color,
            )?;
        }
        draw_axis_text(display, end_label, plot_x + plot_w - 24, label_y, color)?;
    } else {
        let x_labels = if spectrum {
            match opts.sonoro.range.value {
                FrequencyRange::Range24k => ["  0", "  6k ", " 12k ", " 18k ", " 24k "],
                FrequencyRange::Range12k => ["  0", "  3k ", "  6k ", "  9k ", " 12k "],
                FrequencyRange::Range6k => ["  0", "1.5k ", "  3k ", "4.5k ", "  6k "],
                FrequencyRange::Range3k => ["  0", " 750 ", "1.5k ", "2.25k", "  3k "],
            }
        } else {
            match opts.sonoro.rate.value {
                ScrollRate::Fast => ["  0", "0.68s", "1.37s", "2.04s", "2.72s"],
                ScrollRate::Medium => ["  0", "1.36s", "2.73s", "4.08s", "5.44s"],
                ScrollRate::Slow => ["  0", "2.73s", "5.46s", "8.18s", "10.9s"],
                ScrollRate::VerySlow => ["  0", "5.45s", "10.9s", "16.4s", "21.8s"],
            }
        };
        let x_positions = [
            plot_x - axis_pad,
            plot_x + plot_w / 4 - 15,
            plot_x + plot_w / 2 - 15,
            plot_x + plot_w - plot_w / 4 - 15,
            plot_x + plot_w - 30,
        ];
        for (label, x) in x_labels.iter().zip(x_positions) {
            draw_axis_text(display, label, x, label_y, color)?;
        }
    }
    draw_axis_text(
        display,
        if spectrum { "FREQ(Hz)" } else { "AGE (s) " },
        plot_x + plot_w / 2 - 24,
        plot_y + plot_h + axis_pad + 21,
        color,
    )
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
    if ab > c {
        ab
    } else {
        c
    }
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

fn scale_rgb_like_palette(palette: ColorPalette, rgb: (u8, u8, u8), intensity: u8) -> (u8, u8, u8) {
    if let Some((r, g, b)) = palette.heatmap_color(intensity) {
        scale_rgb_to_level(rgb, max3(r, g, b))
    } else {
        scale_rgb_visible(rgb, intensity)
    }
}

/// Program SONORO's palette. Scalar heat maps use each hardware hue column
/// for a rotated version, keeping the plot hue control meaningful.
fn write_sonoro_palette(
    palette: ColorPalette,
    video: &mut impl DMAFramebuffer,
    frequency_ramp: bool,
) {
    if frequency_ramp {
        for intensity in 0..16u8 {
            for hue in 0..16u8 {
                // Frequency-ramp fills use hue for horizontal position, so the
                // palette color itself must stay legible. Keep true black at
                // intensity 0, but lift nonzero levels into the same bright
                // range used by the normal gradient fills.
                let bright_intensity = if intensity == 0 {
                    0
                } else {
                    4 + ((intensity as u16 * 11) / 15) as u8
                };
                let (r, g, b) =
                    scale_rgb_like_palette(palette, palette.frequency_color(hue), bright_intensity);
                video.set_palette_rgb(intensity, hue, r, g, b);
            }
        }
        return;
    }

    if palette.heatmap_color(0).is_none() {
        palette.write_to_hardware(video);
        return;
    }
    for intensity in 0..16u8 {
        for hue in 0..16u8 {
            let (r, g, b) = rotate_rgb_hue(palette.heatmap_color(intensity).unwrap(), hue);
            video.set_palette_rgb(intensity, hue, r, g, b);
        }
    }
}

fn sanitize_options(opts: &mut Opts, last_valid_page: &mut Page) {
    // DisplayOpts uses this hidden mirror to expose its grid option only in
    // spectrum mode. The actual mode remains owned by the SONORO page.
    opts.display.spectrum_mode.value = opts.sonoro.mode.value;

    // SPECTRUM and HISTO are alternate detail pages. The options framework
    // does not support conditional pages, so skip over the inactive page while
    // preserving navigation direction:
    //
    //   SONORO <--> SPECTRUM|HISTO <--> DISPLAY <--> MENU <--> MISC <--> HELP
    //
    // With the enum ordered as SONORO, SPECTRUM, HISTO, DISPLAY..., the
    // inactive page is an in-between sentinel. Use the last valid page to tell
    // whether the user was moving left or right through that sentinel.
    let mut page = opts.tracker.page.value;
    match (opts.sonoro.mode.value, page) {
        (DisplayMode::Spectrum, Page::Histo) => {
            page = if *last_valid_page == Page::Spectrum {
                Page::Display
            } else {
                Page::Spectrum
            };
        }
        (DisplayMode::Spectrograph, Page::Spectrum) => {
            page = if *last_valid_page == Page::Histo {
                Page::Sonoro
            } else {
                Page::Histo
            };
        }
        _ => {}
    }
    if page != opts.tracker.page.value {
        opts.tracker.page.value = page;
        opts.tracker.selected = None;
        opts.tracker.modify = true;
    }

    *last_valid_page = page;
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
        let mut ui =
            ui::UI::new_with_fade(opts, TIMER0_ISR_PERIOD_MS, hide_ms, encoder, pca9635, pmod);
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
    let mut persist = Persist0::new(peripherals.PERSIST_PERIPH);
    let spiflash = SPIFlash0::new(peripherals.SPIFLASH_CTRL, SPIFLASH_BASE, SPIFLASH_SZ_BYTES);

    tiliqua_fw::handlers::logger_init(serial);
    info!("Hello from Tiliqua SONORO!");

    let bootinfo = unsafe { bootinfo::BootInfo::from_addr(BOOTINFO_BASE) }.unwrap();
    let modeline = bootinfo
        .modeline
        .maybe_override_fixed(FIXED_MODELINE, CLOCK_DVI_HZ);

    // PSRAM is not initialized at boot. Clear SONORO's single framebuffer
    // before enabling video so random power-on contents cannot flash behind
    // the beam-raced spectrum and spectrograph overlays.
    clear_framebuffer_region(PSRAM_FB_BASE);

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
    // Boot into the analyzer view even when older saved SONORO settings came
    // from a renderer with a different mode set.
    opts.sonoro.mode.value = DisplayMode::Spectrum;
    opts.spectrum.spectrum_style.value = SpectrumStyle::Bars;
    opts.spectrum.scale.value = SpectrumScale::Log;
    // Freeze is a live transport state, not a startup preference. A toggle
    // button gives it direct encoder-click behavior, so explicitly clear a
    // previously saved value after loading the remaining options.
    opts.sonoro.freeze.value = false;
    let mut last_valid_page = opts.tracker.page.value;
    sanitize_options(&mut opts, &mut last_valid_page);

    let mut last_palette = opts.display.palette.value;
    let mut last_frequency_ramp_palette = false;
    let mut last_hide = opts.menu.hide.value;
    let mut last_edit_hide = opts.menu.edit_hide.value;
    let app = Mutex::new(RefCell::new(App::new(opts)));
    handler!(timer0 = || timer0_handler(&app));

    irq::scope(|s| {
        s.register(handlers::Interrupt::TIMER0, timer0);
        timer.enable_tick_isr(TIMER0_ISR_PERIOD_MS, pac::Interrupt::TIMER0);

        let spectro = peripherals.SPECTROGRAM_PERIPH;
        let overlay = peripherals.OVERLAY_PERIPH;
        let mut first = true;
        let mut last_on_help_page = false;
        let mut last_help_scroll = 0;
        let mut menu_cache: Option<(Opts, u32, u32, u32)> = None;
        let mut last_axis_fingerprint: Option<u32> = None;

        loop {
            let (opts, draw_options, save_opts, wipe_opts) = critical_section::with(|cs| {
                let mut app = app.borrow_ref_mut(cs);
                sanitize_options(&mut app.ui.opts, &mut last_valid_page);
                let save_opts = app.ui.opts.misc.save_opts.poll();
                let wipe_opts = app.ui.opts.misc.wipe_opts.poll();
                (app.ui.opts.clone(), app.ui.draw(), save_opts, wipe_opts)
            });
            // Apply the selected framebuffer rotation before asking for the
            // logical drawing dimensions. The direct spectrum/2D overlay is
            // told about the same rotation below so both renderers agree in
            // the first iteration after an encoder change.
            display.rotate(&opts.misc.rotation.value);
            let h_active = display.size().width;
            let v_active = display.size().height;
            let on_help_page = opts.tracker.page.value == Page::Help;
            let spectrum_mode = opts.sonoro.mode.value == DisplayMode::Spectrum;
            let help_scroll = opts.help.scroll.value;
            let help_page_entered = on_help_page && !last_on_help_page;
            let help_page_left = !on_help_page && last_on_help_page;
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
                    app.borrow_ref_mut(cs)
                        .ui
                        .set_hide_while_editing(opts.menu.edit_hide.value == EditHide::On);
                });
                last_edit_hide = opts.menu.edit_hide.value;
            }
            let help_scroll_changed =
                on_help_page && (!last_on_help_page || help_scroll != last_help_scroll);
            if help_page_entered || help_page_left {
                clear_framebuffer_region(PSRAM_FB_BASE);
                menu_cache = None;
            }
            last_on_help_page = on_help_page;
            last_help_scroll = help_scroll;

            let frequency_ramp_palette = spectrum_mode
                && (opts.spectrum.fill.value == SpectrumFill::Freq
                    || opts.spectrum.fill.value == SpectrumFill::FreqReverse);
            if opts.display.palette.value != last_palette
                || frequency_ramp_palette != last_frequency_ramp_palette
                || first
            {
                write_sonoro_palette(
                    opts.display.palette.value,
                    &mut display,
                    frequency_ramp_palette,
                );
                last_palette = opts.display.palette.value;
                last_frequency_ramp_palette = frequency_ramp_palette;
            }

            if on_help_page {
                last_axis_fingerprint = None;
            } else {
                let fingerprint = axis_fingerprint(&opts, h_active, v_active);
                // Axis text lives in the persistent framebuffer. Clear stale
                // labels only when their layout/content changes, then refresh
                // the small glyph set every loop so persistence never dims it.
                if !first && !help_page_left && last_axis_fingerprint != Some(fingerprint) {
                    clear_framebuffer_region(PSRAM_FB_BASE);
                    menu_cache = None;
                }
                draw_analyzer_axes(&mut display, &opts, h_active, v_active).ok();
                last_axis_fingerprint = Some(fingerprint);
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
            let ui_hue = opts.menu.ui_hue.value;
            let menu_hash = menu_fingerprint(&opts);
            let menu_changed = menu_cache
                .as_ref()
                .map(|(_, old_x, old_y, old_hash)| {
                    *old_x != menu_x || *old_y != menu_y || *old_hash != menu_hash
                })
                .unwrap_or(menu_visible);
            let menu_visibility_changed = menu_visible != menu_cache.is_some();
            if first || menu_changed || menu_visibility_changed {
                if let Some((old_opts, old_x, old_y, _)) = menu_cache.take() {
                    erase_menu(&mut display, &old_opts, old_x, old_y).ok();
                }
                if menu_visible {
                    draw_menu(&mut display, &opts, menu_x, menu_y, ui_hue).ok();
                    menu_cache = Some((opts.clone(), menu_x, menu_y, menu_hash));
                }
            } else if menu_visible {
                // Framebuffer persistence also decays UI pixels in the direct
                // display modes, so refresh an unchanged visible menu without an
                // unnecessary erase pass.
                draw_menu(&mut display, &opts, menu_x, menu_y, ui_hue).ok();
            }
            if draw_options || on_help_page || first {
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
                    clear_help_text_window(&mut display, h_active, v_active).ok();
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
                    last_valid_page = Page::Sonoro;
                    sanitize_options(&mut app.ui.opts, &mut last_valid_page);
                    if let Some(ref mut flash_persist) = flash_persist_opt {
                        flash_persist.erase_all().unwrap();
                    }
                });
            }

            spectro.flags().write(|w| unsafe {
                w.enable().bit(!on_help_page);
                w.phosphor()
                    .bit(!spectrum_mode && opts.histo.style.value == RenderStyle::Phosphor);
                w.axes().bit(opts.display.axes.value == OnOff::On);
                w.input_ch().bits(opts.sonoro.input.value.hw_index());
                w.spectrum_mode().bit(spectrum_mode);
                w.freeze().bit(opts.sonoro.freeze.value)
            });
            spectro
                .gain()
                .write(|w| unsafe { w.value().bits(opts.sonoro.gain.value) });
            spectro
                .range()
                .write(|w| unsafe { w.value().bits(opts.sonoro.range.value.hw_index()) });
            spectro
                .rate()
                .write(|w| unsafe { w.value().bits(opts.sonoro.rate.value.hw_index()) });
            spectro
                .persistence()
                .write(|w| unsafe { w.value().bits(opts.histo.persist.value.hw_index()) });
            spectro
                .hue()
                .write(|w| unsafe { w.value().bits(opts.display.hue.value) });
            spectro
                .noise_floor()
                .write(|w| unsafe { w.value().bits(opts.sonoro.noise_floor.value.hw_index()) });
            spectro.timings().write(|w| unsafe {
                w.h_active().bits(h_active as u16);
                w.v_active().bits(v_active as u16);
                w.menu_visible().bit(menu_visible);
                w.rotation().bits(opts.misc.rotation.value as u8)
            });
            spectro.spectrum_config().write(|w| unsafe {
                w.style()
                    .bit(opts.spectrum.spectrum_style.value.hw_index() != 0);
                w.bands().bits(opts.spectrum.bands.value.hw_index());
                w.fill().bits(opts.spectrum.fill.value.hw_index());
                w.peaks().bits(opts.spectrum.peaks.value.hw_index());
                w.scale().bit(opts.spectrum.scale.value.hw_index() != 0);
                w.highlight()
                    .bit(opts.spectrum.highlight.value.hw_index() != 0);
                w.grid().bit(opts.display.grid.value == OnOff::On)
            });

            // SONORO draws its own plot axes. Keep the general-purpose XBEAM
            // grid disabled for the MVP so the analytical display stays clean.
            overlay.flags().write(|w| unsafe {
                w.grid_style().bits(0);
                w.grid_pixel().bits(0)
            });

            // Help is a static framebuffer page. Keep decay as slow as the
            // persistence controller allows so it remains readable until
            // software clears/redraws it on scroll.
            persist.set_persistence(if on_help_page { 80 } else { 24 });
            first = false;
        }
    })
}
