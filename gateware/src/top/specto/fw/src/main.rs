#![no_std]
#![no_main]

use core::cell::RefCell;
use critical_section::Mutex;
use irq::handler;
use log::{info, warn};
use riscv_rt::entry;

use opts::persistence::*;
use tiliqua_fw::*;
use tiliqua_hal::dma_framebuffer::DMAFramebuffer;
use tiliqua_hal::embedded_graphics::prelude::*;
use tiliqua_hal::persist::Persist;
use tiliqua_lib::calibration::*;
use tiliqua_lib::palette::ColorPalette;
use tiliqua_lib::*;

use options::*;
use pac::constants::*;

pub const TIMER0_ISR_PERIOD_MS: u32 = 5;

const INFERNO_16: [(u8, u8, u8); 16] = [
    (0, 0, 4),
    (10, 7, 34),
    (32, 12, 74),
    (60, 9, 101),
    (87, 16, 110),
    (114, 25, 110),
    (140, 41, 99),
    (165, 62, 79),
    (187, 86, 57),
    (206, 114, 36),
    (222, 143, 17),
    (234, 176, 5),
    (242, 210, 37),
    (248, 238, 85),
    (252, 252, 139),
    (252, 255, 164),
];

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

/// Program SPECTO's palette. Inferno uses each hardware hue column for a
/// rotated version of the heatmap, making the plot hue control meaningful.
fn write_specto_palette(palette: ColorPalette, video: &mut impl DMAFramebuffer) {
    if palette != ColorPalette::Inferno {
        palette.write_to_hardware(video);
        return;
    }
    for intensity in 0..16u8 {
        for hue in 0..16u8 {
            let (r, g, b) = rotate_rgb_hue(INFERNO_16[intensity as usize], hue);
            video.set_palette_rgb(intensity, hue, r, g, b);
        }
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

    let mut last_palette = opts.display.palette.value;
    let app = Mutex::new(RefCell::new(App::new(opts)));
    handler!(timer0 = || timer0_handler(&app));

    irq::scope(|s| {
        s.register(handlers::Interrupt::TIMER0, timer0);
        timer.enable_tick_isr(TIMER0_ISR_PERIOD_MS, pac::Interrupt::TIMER0);

        let spectro = peripherals.SPECTROGRAM_PERIPH;
        let overlay = peripherals.OVERLAY_PERIPH;
        let mut first = true;

        loop {
            let h_active = display.size().width;
            let v_active = display.size().height;
            let (opts, draw_options, save_opts, wipe_opts) = critical_section::with(|cs| {
                let mut app = app.borrow_ref_mut(cs);
                let save_opts = app.ui.opts.misc.save_opts.poll();
                let wipe_opts = app.ui.opts.misc.wipe_opts.poll();
                (app.ui.opts.clone(), app.ui.draw(), save_opts, wipe_opts)
            });
            let on_help_page = opts.tracker.page.value == Page::Help;

            if opts.display.palette.value != last_palette || first {
                write_specto_palette(opts.display.palette.value, &mut display);
                last_palette = opts.display.palette.value;
            }

            if draw_options || on_help_page || first {
                let (x, y) = if on_help_page {
                    (h_active / 2 - 30, v_active - 100)
                } else {
                    (h_active - 200, v_active / 2)
                };
                draw::draw_options(&mut display, &opts, x, y, opts.display.ui_hue.value).ok();
                draw::draw_name(
                    &mut display,
                    h_active / 2,
                    v_active - 50,
                    opts.display.ui_hue.value,
                    &bootinfo.manifest.name,
                    &bootinfo.manifest.tag,
                    &modeline,
                )
                .ok();
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
                w.phosphor()
                    .bit(opts.spectro.style.value == RenderStyle::Phosphor);
                w.axes().bit(opts.display.axes.value == OnOff::On);
                w.input_ch().bits(opts.spectro.input.value.hw_index())
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
                w.v_active().bits(v_active as u16)
            });

            // SPECTO draws its own plot axes. Keep the general-purpose XBEAM
            // grid disabled for the MVP so the analytical display stays clean.
            overlay.flags().write(|w| unsafe {
                w.grid_style().bits(0);
                w.grid_pixel().bits(0)
            });

            // Persistence still clears transient framebuffer UI text. Spectral
            // history and its phosphor falloff live in the beam-raced overlay.
            persist.set_persistence(if on_help_page { 64 } else { 24 });
            display.rotate(&opts.misc.rotation.value);
            first = false;
        }
    })
}
