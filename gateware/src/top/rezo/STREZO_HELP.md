# STREZO built-in help

Condensed from STREZO_USER_GUIDE.md. The topic headings inside the markers
are metadata and are not displayed. Displayed text supports letters, digits,
spaces and periods only. Keep descriptions synchronized with the user guide.

<!-- HELP START -->
## START
GETTING STARTED

Turn to select a control. Click to edit it. Turn to adjust it. Click again to finish.

PAGE changes the operating page. On HELP use TOPIC to choose a page guide. Use SCROLL to read that topic. Changing topics returns to the start of the text.

Begin on INPUT. Assign audio to LEFT and RIGHT. Shape the sound on BANK and BANDS. Assign bands on GROUPS. Set feedback on FEEDBACK and CROSS. Route the sound on OUTPUT.

Help does not change the sound. Sound edits are only saved when you use SAVE DEFAULT.

## BANK
BANK PAGE

PRESET loads a shape for all ten band levels. Click to choose a preset. Click again to apply it. This does not change band frequencies.

BANDS sets each band level. The center is zero. Either side adds that band with opposite polarity. FREQ shows the selected band frequency. Disabled bands cannot be adjusted here.

DRIVE sets how strongly audio excites the bank. Raise it for more level and character.

RESONANCE extends ringing around each band frequency.

FEEDBACK sets the overall return from bands selected on FEEDBACK. Raise it gradually for resonant and unstable textures.

Start with low FEEDBACK. Shape the bands first. Then raise DRIVE and RESONANCE while listening at a safe level.

## INPUT
INPUT PAGE

MODE assigns each jack to LEFT audio or RIGHT audio or CV. Several audio jacks can feed the same side.

Audio VALUE sets gain. Fully down is mute. The tick marks unity gain. The activity line shows that jack after its gain.

CV VALUE chooses FB or RES or DRV or a group from G1 through G4.

DEPTH sets CV amount and polarity. The center gives no modulation. Group CV changes the enabled bands assigned to that group.

The bottom L IN R meters show summed audio after VALUE but before DRIVE and feedback. 0 DB means a 5 V peak. The short section beyond it is headroom. Accent lamps show input mix clipping.

Assign IN0 to LEFT and IN1 to RIGHT for stereo audio. Reduce VALUE if their mixed input clips.

## BANDS
BANDS PAGE

LAYOUT chooses LEGACY or OCTAVE or PERCEPT factory frequencies. Click again to load the chosen layout. This replaces all ten frequencies.

ENABLE turns each resonator on or off. Disabled bands can still be tuned before you enable them.

SET FREQ tunes one band on a fine logarithmic grid. Click again to apply it. A manual frequency edit changes LAYOUT to USER.

LFO SHAPE chooses OFF or TRIANGLE or RANDOM frequency motion shared by both sides.

RATE HZ sets motion speed from 0.0 to 20.0 Hz.

PHASE offsets the triangle source. It is not used for RANDOM.

DEPTH sets the motion amount. The line beneath it shows the resulting modulation.

Load OCTAVE to begin. Tune a few bands by ear. Then add slow motion with a small DEPTH.

## GROUPS
GROUPS PAGE

Each band column selects its membership in G1 through G4. Click the column and turn through the combinations. Lit cells show the groups receiving that band.

A band can feed several groups or none. Disabled bands cannot be edited here.

Groups feed output routing and cross feedback. They also choose which bands respond to group CV on INPUT. The groups are band buses and not input jack assignments.

Try placing low bands in G1 and high bands in G2. Route them separately on OUTPUT or couple them on CROSS.

## FEEDBACK
FEEDBACK PAGE

The ten band switches choose which enabled resonators feed the feedback tap. Click a switch to include or exclude that band. BANK sets the overall FEEDBACK amount.

KNEE sets where soft limiting starts. Signal below it is unchanged. Above it the limiter bends the return toward CEILING.

CEILING sets the final loop limit. Its highlighted span shows the soft region between KNEE and CEILING.

Lowering CEILING past KNEE lowers both. Raising KNEE past CEILING raises both. Equal values give hard limiting with no soft region.

DAMPING chooses OFF or LIGHT or MED or HEAVY or MAX resonance restraint as feedback rises.

Select a few bands before raising FEEDBACK. Lower FEEDBACK or DRIVE if the sound overloads. CROSS settings also affect loop buildup.

## CROSS
CROSS PAGE

LAYOUT chooses the feedback routing pattern. GLOBAL uses no editable matrix. DIAGONAL connects matching groups. ROTATE connects each group to the next. MIRROR connects opposite groups. ALL connects every group at reduced levels.

Click again to load a factory layout. Editing the matrix changes LAYOUT to USER.

Each matrix cell sets a send from its FROM group to its TO group. A FROM row edits all destinations for one source. A TO column edits that destination from all sources.

SAME returns feedback to the same stereo side. CROSS sends it to the opposite side. These are feedback controls and not an output crossfader.

Start with modest FEEDBACK and CROSS. Their effect depends on band levels and group routing and RESONANCE. Extreme settings can become unstable.

For a stronger shared center without more loop gain use MID on OUTPUT. OPTIONS selects the LINEAR or FINE CROSS response.

## OUTPUT
OUTPUT PAGE

Each OUT row mixes G1 through G4 and DRY. A zero send adds nothing. A full send gives unity gain.

The L or R chip chooses the stereo side supplying that row. Click it to switch sides. DRY adds that side of the unfiltered input.

An OUT row header adjusts the wet sends together. ROW DRY on OPTIONS decides if DRY follows. A column header adjusts that source across all outputs.

MID sets the shared center gain. SIDE sets the left and right difference gain. Their ticks mark unity at 64. Above 64 they boost up to twice unity at 128.

MID and SIDE affect wet groups only. They do not change feedback. DRY bypasses them. Lower SIDE for a narrower image. Raise MID to emphasize the shared center after CROSS.

The OUT meters show final output level. Accent caps show clipping. Lower sends if a mix or stereo boost overloads an output.

## OPTIONS
OPTIONS PAGE

PALETTE changes the display colors. It does not change audio.

ROW DRY sets OUTPUT row editing. INCLUDE adjusts DRY with the wet groups. EXCLUDE leaves DRY untouched. Column edits are not affected.

SAVE DEFAULT stores the sound and options in the current bitstream slot. SAVED confirms success. ERROR means the write failed. NO SLOT means saving is unavailable. Edits are not saved automatically.

CROSS CURVE is the advanced response option. LINEAR follows the CROSS position directly. FINE gives more room for low and middle coupling with the strongest return near the top. Both retain zero and maximum gain.

Audition the complete patch at a safe level before saving it. Startup restores saved feedback too.
<!-- HELP END -->
