#![no_std]
#![no_main]

use core::cell::RefCell;
use critical_section::Mutex;
use irq::handler;
use log::{info, warn};
use riscv_rt::entry;

use tiliqua_fw::*;
use tiliqua_lib::*;
use tiliqua_lib::color::HI8;
use pac::constants::*;
use opts::persistence::*;

use tiliqua_hal::embedded_graphics::{
    mono_font::{ascii::FONT_9X15_BOLD, MonoTextStyle},
    prelude::*,
    primitives::{PrimitiveStyle, Rectangle},
    text::Text,
};
use tiliqua_hal::persist::Persist;
use hal::pca9635::Pca9635Driver;

use options::*;

pub const TIMER0_ISR_PERIOD_MS: u32 = 5;

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
        Self {
            ui: ui::UI::new(opts, TIMER0_ISR_PERIOD_MS, encoder, pca9635, pmod),
        }
    }
}

fn write_rezo_registers(opts: &Opts) {
    let rezo = unsafe { pac::REZO_PERIPH::steal() };
    let bands = [
        opts.bands1.hz29.value,
        opts.bands1.hz61.value,
        opts.bands1.hz115.value,
        opts.bands1.hz218.value,
        opts.bands1.hz411.value,
        opts.bands2.hz777.value,
        opts.bands2.hz1k5.value,
        opts.bands2.hz2k8.value,
        opts.bands2.hz5k2.value,
        opts.bands2.hz11k.value,
    ];

    rezo.level0().write(|w| unsafe { w.value().bits(bands[0] as u16) });
    rezo.level1().write(|w| unsafe { w.value().bits(bands[1] as u16) });
    rezo.level2().write(|w| unsafe { w.value().bits(bands[2] as u16) });
    rezo.level3().write(|w| unsafe { w.value().bits(bands[3] as u16) });
    rezo.level4().write(|w| unsafe { w.value().bits(bands[4] as u16) });
    rezo.level5().write(|w| unsafe { w.value().bits(bands[5] as u16) });
    rezo.level6().write(|w| unsafe { w.value().bits(bands[6] as u16) });
    rezo.level7().write(|w| unsafe { w.value().bits(bands[7] as u16) });
    rezo.level8().write(|w| unsafe { w.value().bits(bands[8] as u16) });
    rezo.level9().write(|w| unsafe { w.value().bits(bands[9] as u16) });
    rezo.dry().write(|w| unsafe { w.value().bits(opts.shape.dry.value) });
    rezo.resonance().write(|w| unsafe { w.value().bits(opts.shape.resonance.value) });
    rezo.feedback().write(|w| unsafe { w.value().bits(opts.shape.feedback.value as u16) });
}

fn timer0_handler(app: &Mutex<RefCell<App>>) {
    critical_section::with(|cs| {
        let mut app = app.borrow_ref_mut(cs);
        app.ui.update();
        write_rezo_registers(&app.ui.opts);
    });
}

fn draw_rezo_bars<D>(
    display: &mut D,
    opts: &Opts,
    x0: i32,
    y0: i32,
    hue: u8,
) where
    D: DrawTarget<Color = HI8>,
{
    let bands = [
        opts.bands1.hz29.value,
        opts.bands1.hz61.value,
        opts.bands1.hz115.value,
        opts.bands1.hz218.value,
        opts.bands1.hz411.value,
        opts.bands2.hz777.value,
        opts.bands2.hz1k5.value,
        opts.bands2.hz2k8.value,
        opts.bands2.hz5k2.value,
        opts.bands2.hz11k.value,
    ];
    let labels = ["29", "61", "115", "218", "411", "777", "1k5", "2k8", "5k2", "11k"];
    let font = MonoTextStyle::new(&FONT_9X15_BOLD, HI8::new(hue, 0xB));
    let bar_style = PrimitiveStyle::with_fill(HI8::new(hue, 0xC));
    let zero_style = PrimitiveStyle::with_fill(HI8::new(hue, 0x4));

    Text::new("REZO bands", Point::new(x0, y0 - 28), font)
        .draw(display).ok();

    for (n, band) in bands.iter().enumerate() {
        let x = x0 + (n as i32) * 42;
        Rectangle::new(Point::new(x + 13, y0 + 62), Size::new(22, 2))
            .into_styled(zero_style)
            .draw(display).ok();
        let h = ((*band as i32).abs() * 60 / 16384) as u32;
        let y = if *band >= 0 { y0 + 62 - h as i32 } else { y0 + 64 };
        Rectangle::new(Point::new(x + 15, y), Size::new(18, h.max(1)))
            .into_styled(bar_style)
            .draw(display).ok();
        Text::new(labels[n], Point::new(x, y0 + 92), font)
            .draw(display).ok();
    }

    let shape = [
        ("dry", opts.shape.dry.value as i32),
        ("res", opts.shape.resonance.value as i32),
        ("fb", opts.shape.feedback.value as i32),
    ];
    for (n, (label, value)) in shape.iter().enumerate() {
        let y = y0 + 130 + (n as i32) * 20;
        Text::new(label, Point::new(x0, y), font).draw(display).ok();
        let w = (value.abs() * 160 / 32768).max(1) as u32;
        Rectangle::new(Point::new(x0 + 70, y - 11), Size::new(w, 10))
            .into_styled(bar_style)
            .draw(display).ok();
    }
}

#[entry]
fn main() -> ! {
    let peripherals = pac::Peripherals::take().unwrap();

    let sysclk = pac::clock::sysclk();
    let serial = Serial0::new(peripherals.UART0);
    let mut timer = Timer0::new(peripherals.TIMER0, sysclk);
    let mut persist = Persist0::new(peripherals.PERSIST_PERIPH);
    let spiflash = SPIFlash0::new(
        peripherals.SPIFLASH_CTRL,
        SPIFLASH_BASE,
        SPIFLASH_SZ_BYTES,
    );

    tiliqua_fw::handlers::logger_init(serial);
    info!("Hello from Tiliqua REZO!");

    let bootinfo = unsafe { bootinfo::BootInfo::from_addr(BOOTINFO_BASE) }.unwrap();
    let modeline = bootinfo.modeline.maybe_override_fixed(FIXED_MODELINE, CLOCK_DVI_HZ);
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
    calibration::CalibrationConstants::load_or_default(&mut i2cdev1, &mut pmod);

    let mut opts = Opts::default();
    let mut flash_persist_opt = if let Some(storage_window) = bootinfo.manifest.get_option_storage_window() {
        let mut flash_persist = FlashOptionsPersistence::new(spiflash, storage_window);
        flash_persist.load_options(&mut opts).unwrap();
        Some(flash_persist)
    } else {
        warn!("No option storage region: disable persistent storage");
        None
    };

    opts.beam.palette.value.write_to_hardware(&mut display);
    let mut last_palette = opts.beam.palette.value;

    let app = Mutex::new(RefCell::new(App::new(opts)));

    handler!(timer0 = || timer0_handler(&app));

    irq::scope(|s| {
        s.register(handlers::Interrupt::TIMER0, timer0);
        timer.enable_tick_isr(TIMER0_ISR_PERIOD_MS, pac::Interrupt::TIMER0);

        let mut vscope = Vector0::new(peripherals.VECTOR_PERIPH);
        let mut scope = Scope0::new(peripherals.SCOPE_PERIPH, 6);

        loop {
            let h_active = display.size().width;
            let v_active = display.size().height;

            let (opts, draw_options, save_opts, wipe_opts) = critical_section::with(|cs| {
                let mut app = app.borrow_ref_mut(cs);
                let save_opts = app.ui.opts.misc.save_opts.poll();
                let wipe_opts = app.ui.opts.misc.wipe_opts.poll();
                (app.ui.opts.clone(), app.ui.draw(), save_opts, wipe_opts)
            });

            if opts.beam.palette.value != last_palette {
                opts.beam.palette.value.write_to_hardware(&mut display);
                last_palette = opts.beam.palette.value;
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
                    if let Some(ref mut flash_persist) = flash_persist_opt {
                        flash_persist.erase_all().unwrap();
                    }
                });
            }

            let on_help_page = opts.tracker.page.value == Page::Help;
            if draw_options || on_help_page {
                let (x, y) = if on_help_page {
                    (h_active / 2 - 30, v_active - 100)
                } else {
                    (h_active - 210, v_active / 2)
                };
                draw::draw_options(&mut display, &opts, x, y, opts.beam.hue.value).ok();
                draw::draw_name(&mut display, h_active / 2, v_active - 50, opts.beam.hue.value,
                                &bootinfo.manifest.name, &bootinfo.manifest.tag, &modeline).ok();
            }

            if on_help_page {
                persist.set_persistence(64);
                draw::draw_help_page(
                    &mut display,
                    MODULE_DOCSTRING,
                    bootinfo.manifest.help.as_ref(),
                    h_active,
                    v_active,
                    opts.help.scroll.value,
                    opts.beam.hue.value,
                ).ok();
            } else {
                persist.set_persistence(opts.beam.persist.value);
                draw_rezo_bars(&mut display, &opts, 90, 90, opts.beam.hue.value);
            }

            scope.set_hue(opts.beam.hue.value);
            scope.set_intensity(opts.beam.intensity.value);
            scope.set_trigger_level(opts.scope.trig_lvl.value);
            scope.set_yscale(opts.scope.yscale.value);
            scope.set_timebase(opts.scope.timebase.value);
            let (_, sppd) = scope.pixels_per_div();
            let ypos = [opts.scope.ypos0.value, opts.scope.ypos1.value,
                        opts.scope.ypos2.value, opts.scope.ypos3.value];
            for ch in 0..4u8 {
                scope.set_ypos_px(ch.into(), ypos[ch as usize] * (sppd / 4) as i16);
            }

            if on_help_page {
                scope.set_enabled(false, false);
                vscope.set_enabled(false);
            } else {
                scope.set_enabled(true, opts.scope.trig_mode.value == TriggerMode::Always);
                vscope.set_enabled(false);
            }
        }
    })
}
