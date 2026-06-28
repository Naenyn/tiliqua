//! Scope trigger / sweep diagnostics (gateware CSRs + optional on-screen HUD).

use core::fmt::Write;

use tiliqua_hal::embedded_graphics::mono_font::ascii::FONT_9X15;
use tiliqua_hal::embedded_graphics::mono_font::MonoTextStyle;
use tiliqua_hal::embedded_graphics::prelude::{DrawTarget, Drawable, Point};
use tiliqua_hal::embedded_graphics::text::Text;
use heapless::String;
use log::info;

use tiliqua_fw::Scope0;
use tiliqua_lib::color::HI8;

/// Live status bits from ``debug_status`` (see gateware ``DebugStatus``).
pub struct ScopeDebugStatus {
    pub armed: bool,
    pub pending_trig: bool,
    pub ramp_at_top: bool,
    pub in_plot: bool,
    pub sweeping: bool,
    pub at_end: bool,
    pub sweep_end: bool,
    pub sample_valid: bool,
}

impl ScopeDebugStatus {
    pub fn from_raw(st: u32) -> Self {
        Self {
            in_plot: (st >> 5) & 1 != 0,
            at_end: (st >> 6) & 1 != 0,
            sweeping: (st >> 7) & 1 != 0,
            sweep_end: (st >> 9) & 1 != 0,
            sample_valid: (st >> 4) & 1 != 0,
            ramp_at_top: (st >> 12) & 1 != 0,
            armed: (st >> 13) & 1 != 0,
            pending_trig: (st >> 14) & 1 != 0,
        }
    }
}

/// Per-sweep event counts (reset when ``capture_done`` increments).
pub struct ScopeDebugSweep {
    pub trig: u8,
    pub ramp_restart: u8,
    pub pen_lift: u8,
    pub end_reached: u8,
    pub flush: u8,
    pub render: u8,
    pub drop: u8,
}

impl ScopeDebugSweep {
    pub fn from_regs(ct: u32, tr: u32) -> Self {
        Self {
            render: ((ct >> 8) & 0xff) as u8,
            flush: ((ct >> 16) & 0xff) as u8,
            drop: ((ct >> 24) & 0xff) as u8,
            trig: (tr & 0xff) as u8,
            ramp_restart: ((tr >> 8) & 0xff) as u8,
            pen_lift: ((tr >> 16) & 0xff) as u8,
            end_reached: ((tr >> 24) & 0xff) as u8,
        }
    }
}

pub fn log_scope_debug(scope: &Scope0) {
    let st = ScopeDebugStatus::from_raw(scope.debug_status());
    let sw = ScopeDebugSweep::from_regs(scope.debug_counts(), scope.debug_trig());
    let (ix, iy) = scope.debug_probe();
    info!(
        "scope dbg sweeps={} arm={} pend={} top={} plot={} swp={} \
         trig={} rr={} pen={} end={} flush={} rend={} drop={} ix={} iy={} td={:#x}",
        scope.debug_counts() & 0xff,
        st.armed as u8,
        st.pending_trig as u8,
        st.ramp_at_top as u8,
        st.in_plot as u8,
        st.sweeping as u8,
        sw.trig,
        sw.ramp_restart,
        sw.pen_lift,
        sw.end_reached,
        sw.flush,
        sw.render,
        sw.drop,
        ix,
        iy,
        scope.debug_timebase(),
    );
}

pub fn draw_scope_debug_hud<D>(display: &mut D, scope: &Scope0, hue: u8, origin: Point)
where
    D: DrawTarget<Color = HI8>,
    D::Error: core::fmt::Debug,
{
    let st = ScopeDebugStatus::from_raw(scope.debug_status());
    let sw = ScopeDebugSweep::from_regs(scope.debug_counts(), scope.debug_trig());
    let (ix, iy) = scope.debug_probe();
    let sweeps = (scope.debug_counts() & 0xff) as u8;

    let style = MonoTextStyle::new(&FONT_9X15, HI8::new(hue, 11));
    let mut line = String::<44>::new();

    let _ = write!(
        line,
        "A{} P{} T{} I{} S{}",
        st.armed as u8,
        st.pending_trig as u8,
        st.ramp_at_top as u8,
        st.in_plot as u8,
        st.sweeping as u8,
    );
    let _ = Text::new(line.as_str(), origin, style).draw(display);

    line.clear();
    let _ = write!(
        line,
        "tg{} rr{} pn{} en{}",
        sw.trig, sw.ramp_restart, sw.pen_lift, sw.end_reached,
    );
    let _ = Text::new(
        line.as_str(),
        origin + Point::new(0, 14),
        style,
    )
    .draw(display);

    line.clear();
    let _ = write!(
        line,
        "fl{} rd{} dr{} #{}",
        sw.flush, sw.render, sw.drop, sweeps,
    );
    let _ = Text::new(
        line.as_str(),
        origin + Point::new(0, 28),
        style,
    )
    .draw(display);

    line.clear();
    let _ = write!(line, "ix{} iy{}", ix, iy);
    let _ = Text::new(
        line.as_str(),
        origin + Point::new(0, 42),
        style,
    )
    .draw(display);
}
