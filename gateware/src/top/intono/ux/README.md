# Route flow experiment

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
