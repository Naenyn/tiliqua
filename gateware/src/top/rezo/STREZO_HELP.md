# STREZO built-in help

Reviewed mixed-case prose. Topic headings are metadata. Displayed text
supports ASCII letters, digits, spaces, periods and basic punctuation:
commas, colons, semicolons, apostrophes, hyphens, parentheses, slashes,
plus and percent signs, exclamation and question marks.

<!-- HELP START -->
## START
GETTING STARTED

STREZO is a stereo resonant filterbank. It offers stereo I/O, modulation animation similar to REZOMO, and highly configurable feedback routing.

Turn to select a control. Click to edit it. Turn to adjust it. Click again to finish. Switches act on one click.

PAGE changes the operating page. On HELP, use TOPIC to choose a page guide. Use SCROLL to read that topic. Changing topics returns to the start of the text.

Begin on INPUT and assign LEFT and RIGHT audio. Shape the sound on BANK. Tune resonators on BANDS. Assign bands on GROUPS. Set the loop on FEEDBACK and CROSS. Route the sound on OUTPUT.

On OPTIONS, use SAVE DEFAULT to store edits.

## BANK
BANK PAGE

PRESET loads a shape for all ten band levels. Click to choose a preset. Click again to apply it. This does not change frequencies or routing.

BANDS sets each band level. The center is zero. Either side adds that band with opposite polarity. FREQ shows the selected band frequency. Disabled bands cannot be adjusted here.

DRIVE sets input strength. RESONANCE extends ringing. FEEDBACK returns the mix selected on FEEDBACK to the resonator input. Raise these gradually at a safe listening level.

Start with low FEEDBACK. Shape the bands first. Then raise DRIVE and RESONANCE while listening at a safe level.

## INPUT
INPUT PAGE

MODE assigns each jack to LEFT audio or RIGHT audio or CV. Several audio jacks can feed the same side.

Audio VALUE sets gain. Fully down is mute. The tick marks unity gain. The activity line shows that jack after its gain.

CV VALUE chooses FB or RES or DRV or a group from G1 through G4. DEPTH sets amount and polarity. The center gives no modulation. Group CV modulates enabled bands assigned to that group.

The bottom L IN R meters show summed audio after VALUE but before DRIVE and feedback. 0 DB means a 5 V peak. The short section beyond it is headroom. Accent lamps show input mix clipping.

Assign IN0 to LEFT and IN1 to RIGHT for stereo audio. Reduce VALUE if their mixed input clips.

## BANDS
BANDS PAGE

The BANDS page allows you to enable or disable bands as well as define each band's frequency.

PRESET chooses LEGACY, OCTAVE, or PERCEPT factory frequencies. Click again to load the chosen layout. This replaces all ten frequencies.

ENABLE turns a resonator on or off. Disabled bands can still be tuned here.

SET FREQ tunes one band on a fine logarithmic grid. Click again to apply it. A manual frequency edit changes PRESET to USER.

USER is the current layout and not a separate stored copy. Frequency edits do not erase natural levels or group routing.

LFO SHAPE chooses OFF, TRIANGLE, or RANDOM frequency motion shared by both sides.

RATE HZ sets motion speed from 0.0 to 20.0 Hz.

PHASE offsets the triangle source. It is not used for RANDOM.

DEPTH sets the motion amount. The line beneath it shows the resulting modulation.

Load OCTAVE to begin. Tune a few bands by ear. Then add slow motion with a small DEPTH.

## GROUPS
GROUPS PAGE

This page allows you to assign bands to groups.

To edit groups, first choose a band column. Then, click the column and turn through the combinations. Lit cells indicate the selected band has been assigned to that row's group. A band can be assigned to zero or up to all four groups.

Disabled bands cannot be edited here.

Groups feed OUTPUT routing and CROSS feedback. They also choose the enabled bands affected by group CV on INPUT. They are band buses and not input jack assignments.

Try placing low bands in G1 and high bands in G2. Route them separately on OUTPUT or couple them on CROSS.

## FEEDBACK
FEEDBACK PAGE

The ten band switches choose enabled resonators for the feedback tap. Click a switch to include or exclude that band. The main FEEDBACK control sets the overall return.

KNEE sets where soft limiting starts. Signal below it is unchanged. Above it the limiter bends the return toward CEILING.

CEILING sets the final loop limit. Its highlighted span shows the soft region between KNEE and CEILING. Lowering CEILING past KNEE lowers both. Raising KNEE past CEILING raises both. Equal values give hard limiting.

DAMPING chooses OFF or LIGHT or MED or HEAVY or MAX resonance restraint as feedback rises.

Select a few bands before raising FEEDBACK. If the sound overloads reduce feedback or DRIVE or RESONANCE. CROSS settings also affect loop buildup. Limiting does not make extreme settings quiet.

## CROSS
CROSS PAGE

This is the heart of the bitstream. It allows you to define feedback routing and can greatly influence the resulting stereo image.

LAYOUT chooses the feedback routing pattern. GLOBAL bypasses the group routing matrix, using only SAME, CROSS, and FEEDBACK. DIAGONAL connects matching groups. ROTATE connects each group to the next. MIRROR connects opposite groups. ALL connects every group at reduced levels. Click to load a factory layout. Editing the matrix changes LAYOUT to USER.

Each matrix cell sets a send from its FROM group to its TO group. A FROM row edits all destinations for one source. A TO column edits that destination from all sources.

SAME returns feedback to the same stereo side. CROSS sends it to the opposite side. These are feedback controls and not an output crossfader.

Start with modest FEEDBACK and CROSS. Their effect depends on band levels and group routing and RESONANCE. Extreme settings can become unstable.

For a stronger shared center without more loop gain use MID on OUTPUT. OPTIONS selects the LINEAR or FINE CROSS response.

## OUTPUT
OUTPUT PAGE

This page allows you to control how much signal of each group is sent to each of Tiliqua's outputs. Each OUT row mixes G1 through G4 along with the DRY signal. A full send gives unity gain.

The L or R chip chooses the stereo side supplying that row. Click it to switch sides. DRY adds that side of the unfiltered input.

An OUT row header adjusts levels for that output together. ROW DRY on OPTIONS decides if DRY is included when editing a row or is ignored. A column header adjusts that source across all outputs.

MID sets the shared center gain. SIDE sets the left and right difference gain. Their ticks mark unity at 64. Above 64 they boost up to twice unity at 128.

MID and SIDE affect wet groups only. They do not change feedback. DRY bypasses them. Lower SIDE for a narrower image. Raise MID to emphasize the shared center after CROSS.

The OUT meters show final output level. Accent caps show clipping. Lower sends if a mix or stereo boost overloads an output.

## OPTIONS
OPTIONS PAGE

PALETTE changes display colors without changing audio.

ROW DRY sets output row editing. INCLUDE adjusts DRY with wet groups. EXCLUDE leaves DRY untouched. Individual cells and column edits remain available in either setting.

SAVE DEFAULT stores the sound and options in the current bitstream slot. SAVING shows a write in progress. SAVED confirms success. ERROR means the write failed. NO SLOT means saving is unavailable.

CROSS CURVE is the advanced response option. LINEAR follows the CROSS position directly. FINE gives more room for low and middle coupling with the strongest return near the top. Both retain zero and maximum gain.

Edits are not saved automatically. Audition the patch at a safe level before saving it. Saved settings are restored at bitstream startup.
<!-- HELP END -->
