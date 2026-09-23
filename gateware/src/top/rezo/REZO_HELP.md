# REZO built-in help

Reviewed mixed-case prose. Topic headings are metadata. Displayed text
supports ASCII letters, digits, spaces, periods and basic punctuation:
commas, colons, semicolons, apostrophes, hyphens, parentheses, slashes,
plus and percent signs, exclamation and question marks.

<!-- HELP START -->
## START
GETTING STARTED

REZO is a ten band resonant filterbank. It offers two main modes: a core BANK mode that is shared with REZOMO, and a FILTER mode that allows for manipulating the filterbank using common filter shapes.

Turn to select a control. Click to edit it. Turn to adjust it. Click again to finish. Switches act on one click.

PAGE changes the operating page. On HELP, use TOPIC to choose a page guide. Use SCROLL to read that topic. Changing topics returns to the start of the text.

Begin on INPUT and assign audio. Shape the sound on BANK or FILTER. Tune resonators on BANDS. Assign bands on GROUPS. Set the loop on FEEDBACK. Route the sound on OUTPUT.

On OPTIONS, use SAVE DEFAULT to store edits.

## BANK
BANK PAGE

MODE switches between BANK and FILTER. BANK gives direct control over ten resonator levels. FILTER generates their levels from a filter shape.

PRESET loads a shape for all ten band levels. Click to choose a preset. Click again to apply it. This does not change frequencies or routing.

BANDS sets each band level. The center is zero. Either side adds that band with opposite polarity. FREQ shows the selected band frequency. Disabled bands cannot be adjusted here.

DRIVE sets input strength. RESONANCE extends ringing. FEEDBACK returns the mix selected on FEEDBACK to the resonator input. Raise these gradually at a safe listening level.

BANK and FILTER retain separate drive and feedback amounts. RESONANCE is shared. Returning to BANK restores its manual level shape.

## FILTER
FILTER PAGE

FILTER mode allows the bands to be controled by a common filter shape. The columns show generated gains rather than manual BANK levels. FILTER uses all ten resonators and ignores BANK enable switches. Frequencies and groups remain shared with BANK.

TYPE chooses from common filter shapes: LP or HP or BP or NOT. LP passes lower bands. HP passes higher bands. BP passes a region around FREQ. NOT reduces that region and passes bands outside it.

FREQ moves the transition or center through the resonators. SLOPE sets how gently or sharply the level shape changes. WIDTH sets the BP or NOT region size. It is only shown for those types.

DRIVE sets FILTER input strength. RESONANCE is shared with BANK. Set the FILTER feedback amount on FEEDBACK.

Use MATRIX to add CV movement to the shape. FILTER retains its own drive and feedback and output sends.

## INPUT
INPUT PAGE

MODE assigns each jack to AUDIO or CV. Audio jacks sum into one mono input mix.

Audio VALUE sets gain. Fully down is mute. The tick marks unity gain. The activity line shows that jack after its gain. Its accent cap shows individual clipping.

In BANK, CV VALUE chooses FB or RES or DRV or a group from G1 through G4. DEPTH sets amount and polarity. The center gives no modulation. Group CV modulates enabled bands assigned to that group.

In FILTER the CV signals from IN1 through IN3 feed MATRIX. Set their destination depths there. Changing a jack to AUDIO removes its CV from MATRIX without erasing depths.

The bottom IN meter shows the audio mix after VALUE but before DRIVE and feedback. 0 DB means a 5 V peak. The section beyond it is headroom. The accent cap shows input mix clipping.

Start with one AUDIO jack. Lower VALUE if the input mix clips.

## BANDS
BANDS PAGE

The BANDS page allows you to enable or disable bands as well as define each band's frequency.

PRESET chooses LEGACY, OCTAVE, or PERCEPT factory frequencies. Click again to load the chosen layout. This replaces all ten frequencies.

ENABLE turns a resonator on or off in BANK. FILTER ignores these switches and uses all ten bands. Disabled bands can still be tuned here.

SET FREQ tunes one band on a fine logarithmic grid. Slow turns give fine adjustment. Fast turns accelerate. Click again to apply it. A manual edit changes the layout to USER.

USER is the current layout and not a separate stored copy. Frequency edits do not erase natural levels or group routing.

Frequencies are shared between BANK and FILTER.

Load OCTAVE to begin. Tune a few bands by ear before adding strong resonance.

## MATRIX
MATRIX PAGE

MATRIX is available in FILTER mode. Its columns are IN1 through IN3. Set a source jack to CV on INPUT to use it here.

The rows are FREQUENCY and RESONANCE and WIDTH and SLOPE and DRIVE. Each cell sets the depth from that input to that destination.

Click a cell and turn to adjust it. The center is zero modulation. The two directions give opposite CV polarity. One source can affect several destinations. Several sources can affect one destination.

WIDTH only affects BP and NOT. A source assigned AUDIO contributes no matrix CV. Its stored depths remain available if it returns to CV.

Begin with a small FREQUENCY depth from one slow CV. Add WIDTH or SLOPE modulation for more movement.

## GROUPS
GROUPS PAGE

This page allows you to assign bands to groups. BANK and FILTER share group membership.

To edit groups, first choose a band column. Then, click the column and turn through the combinations. Lit cells indicate the selected band has been assigned to that row's group. A band can be assigned to zero or up to all four groups.

Groups feed OUTPUT routing. In BANK, they also choose the enabled bands affected by group CV on INPUT. They are band buses and not input jack assignments.

Disabled BANK bands cannot be edited here. FILTER uses all ten columns. Group membership is shared between modes.

Try low bands in G1 and high bands in G2. Route these groups to different outputs.

## FEEDBACK
FEEDBACK PAGE

The ten band switches choose resonators for the feedback tap. Click a switch to include or exclude that band. Disabled BANK bands remain silent. FILTER uses all ten resonators.

FEEDBACK sets the overall return. BANK and FILTER retain independent amounts. BANK also exposes its amount on the main page.

KNEE sets where soft limiting starts. Signal below it is unchanged. Above it the limiter bends the return toward CEILING.

CEILING sets the final loop limit. Its highlighted span shows the soft region between KNEE and CEILING. Lowering CEILING past KNEE lowers both. Raising KNEE past CEILING raises both. Equal values give hard limiting.

DAMPING restrains resonance as feedback rises. Higher settings are more conservative.

Select a few bands before raising FEEDBACK. If the sound overloads reduce feedback or DRIVE or RESONANCE. Limiting does not make extreme settings quiet.

## OUTPUT
OUTPUT PAGE

This page allows you to control how much signal of each group is sent to each of Tiliqua's outputs. Each OUT row mixes G1 through G4 along with the DRY signal. A full send gives unity gain. DRY adds the unfiltered mono input mix.

An OUT row header adjusts levels for that output together. In BANK, ROW DRY on OPTIONS decides if DRY is included when editing a row or is ignored. A column header adjusts that source across all outputs.

FILTER has its own sends. Its row gesture adjusts wet groups only. The individual DRY sends remain editable.

The OUT meters show final output level. Accent caps show clipping. Lower the sends if the output mix clips.

Route groups to separate outputs for related sounds. Add DRY only when you want some original input too.

## OPTIONS
OPTIONS PAGE

PALETTE changes display colors without changing audio.

ROW DRY sets BANK output row editing. INCLUDE adjusts DRY with wet groups. EXCLUDE leaves DRY untouched. Individual cells and column edits remain available in either setting.

SAVE DEFAULT stores the complete setup of both modes in the current bitstream slot. SAVING shows a write in progress. SAVED confirms success. ERROR means the write failed. NO SLOT means saving is unavailable.

Edits are not saved automatically. Audition the patch at a safe level before saving it. Saved settings are restored at bitstream startup.
<!-- HELP END -->
