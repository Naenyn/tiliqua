# Route flow experiment

## Firmware integration (2026-10-02)

The branch now implements the layout in Intono itself. Routes opens a four-card
overview; turning expands the selected route and clicking opens its flow.
Two output branches fit at once, with an explicit View control for the others.
Each output has a Pitch group (scale, key, mapping, shifts) and an Output group
(jack, calibration profile, 0V tuning, live note). Each group opens a centered
editor, and Done returns to that group. A single visible branch is vertically
centered; two branches are stacked with wider arrow connections. Back returns
to the overview; turning backward past the first card returns to page selection.

The CV input and MIDI settings belong to the route. Each output retains its own
scale, key, mapping, shift, and calibration profile. Applying a profile and loading
a saved user scale remain explicit actions. Running routes lock their output
configuration; MIDI settings and Stop remain available. Active jack assignments
are still enforced by the existing reservation system.

Green bars sample actual output pitch at 8 Hz, oldest on the left, showing about
one second of history. Held pitches give steady bars. The renderer retains bounded
shape lists in the existing double-buffered background banks and publishes shapes
with their text. It adds no framebuffer or FPGA block RAM.

Code: `fw/src/route_ui.rs`, `fw/src/route_render.rs`, and `fw/src/ui_route.rs`.
The browser prototype below remains a design reference with simulated data.

Branch: `codex/intono-route-flow`. Firmware baseline: `ad9498a9`.

Open `index.html` in a browser for an interactive design prototype. `route-flow.html`
is its editable source; the standalone page is generated with the visualize
renderer. This prototype does not connect to the rack or change firmware.

## Interaction

- Turn selects a route; click opens it. Clicking a different card selects and
  expands that card. Clicking the selected card opens its flow.
- Each output has quantization, transpose, calibration, and output stages.
  Click a stage to open a centered editor. Done or Escape returns to the flow.
- Scale, root key, mapping, and manual transpose are independent per output.
  The route's MIDI channel, zero note, and release behavior are shared.
- Assigned jacks are dimmed and unavailable. Start locks output configuration;
  Stop makes it editable. MIDI configuration remains editable.
- Add Output uses a free jack. Two branches appear at once; a pager exposes
  branches three and four. Remove an output from Route 2 to try all four on Route 1.
- Native keyboard controls work in editors. Left/right move focus through flow
  stages; Enter activates a focused stage. The preview buttons approximate the
  encoder's navigation, rather than reproducing firmware value editing.

## Scope and follow-up

Data is simulated, with demo oscillator profiles and user scale slots. There is
no MIDI stream, calibration measurement, save/load implementation, or CV output.
Configuration changes in the preview apply immediately. Profile selection is a
visual stand-in for the firmware's explicit load/apply operation. The other top
pages are labels for context, not functional navigation.

The circular layout represents the display at approximately 720 pixels. Narrow
browser previews reflow into a taller surface to preserve legibility; that is not
a proposed change to the hardware display.

Before firmware integration, settle stage layout and encoder behavior, then map
the view state onto existing route/output options. Keep overlay storage bounded,
retain calibration timing logs, and verify stack margin and video timing. No DSP,
calibration, routing, or FPGA implementation has changed in this experiment.

Validation: local browser interaction checks covered scale/key edits, running
locks, assigned-jack disabling, removal/addition, four-output paging, and MIDI
settings. Desktop and narrow layouts were visually inspected.

New route layouts start empty. A route's source becomes reserved with its first output; stopping preserves assignments, removing the final output frees the source. Whole-setup slots replace all four route definitions together after validation. Rejected loads use a centered warning with a route jump for running-route blockers, cancel/return navigation, and explicit duplicate-jack diagnostics for invalid saved configurations.

MIDI route controls use Base note and Transpose terminology. Learn base note captures any exact note on the selected channel; it does not round to an octave. Release can Latch the latest offset or Reset on release. Reset transpose clears the live offset and the popup displays it. The learned base remains part of the saved route setup.

The route overview no longer has an Edit route button: clicking a card opens it. Encoder navigation presents Start/Stop for the highlighted card before moving to another route. Configs (formerly Setups) saves the complete four-route configuration; its summary lists current assignments rather than live running state. Both Configs and its MIDI Transpose screen have Back buttons. The MIDI screen selects Route 1–4 explicitly and shows the current offset shared by its outputs. Config loading does not automatically start outputs; live MIDI offsets are not saved.
