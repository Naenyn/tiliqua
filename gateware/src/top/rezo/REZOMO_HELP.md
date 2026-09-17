# REZOMO built-in help

Condensed from REZOMO_USER_GUIDE.md. Topic headings are metadata. Displayed
text supports letters, digits, spaces and periods only.

<!-- HELP START -->
## START
GETTING STARTED

Turn to select a control. Click to edit it. Turn to adjust it. Click again to finish. Switches act on one click.

PAGE changes the operating page. On HELP use TOPIC to choose a page guide. Use SCROLL to read that topic. Changing topics returns to the start of the text.

Begin on INPUT and assign audio. Shape the sound on BANK. Tune resonators on BANDS. Use CLOCK for rhythmic movement. Assign bands on GROUPS. Set the loop on FEEDBACK. Route the sound on OUTPUT.

Help does not change the sound. Use SAVE DEFAULT to store sound edits.

## BANK
BANK PAGE

MODE switches between BANK and CLOCK. CLOCK adds temporary band modulation while keeping the BANK sound and routing.

PRESET loads a shape for all ten natural band levels. Click to choose a preset. Click again to apply it. This does not change frequencies or routing.

BANDS sets each natural band level. The center is zero. Either side adds that band with opposite polarity. FREQ shows the selected band frequency. Disabled bands cannot be adjusted here.

DRIVE sets input strength. RESONANCE extends ringing. FEEDBACK returns the mix selected on FEEDBACK to the resonator input. Raise these gradually at a safe listening level.

The CLOCK main page edits the same natural levels. Their markers remain visible while modulation moves around them. Reduce DEPTH on the CLOCK settings page to hear more of the natural shape.

## INPUT
INPUT PAGE

MODE assigns each jack to AUDIO or CV. Audio jacks sum into one mono input mix.

Audio VALUE sets gain. Fully down is mute. The tick marks unity gain. The activity line shows that jack after its gain.

CV VALUE chooses FB or RES or DRV or a group from G1 through G4. DEPTH sets amount and polarity. The center gives no modulation. Group CV changes enabled bands assigned to that group.

CV VALUE also assigns CLOCK roles. CLK accepts the clock. DAT supplies SHIFT samples. RST clears SHIFT and ROTATE and WALK. LCK locks a filled TURING loop. Use separate jacks for simultaneous roles.

On first entering CLOCK the default roles are IN1 RST and IN2 DAT and IN3 CLK unless clock roles already exist. IN0 remains available for audio.

The bottom IN meter shows the audio mix after VALUE but before DRIVE and feedback. 0 DB means a 5 V peak. The section beyond it is headroom. The accent cap shows input mix clipping.

## BANDS
BANDS PAGE

PRESET chooses LEGACY or OCTAVE or PERCEPT factory frequencies. Click again to load the chosen layout. This replaces all ten frequencies.

ENABLE turns a resonator on or off in both BANK and CLOCK. Disabled bands can still be tuned here.

SET FREQ tunes one band on a fine logarithmic grid. Slow turns give fine adjustment. Fast turns accelerate. Click again to apply it. A manual edit changes the layout to USER.

USER is the current layout and not a separate stored copy. Frequency edits do not erase natural levels or group routing.

Load OCTAVE to begin. Tune a few bands by ear before adding CLOCK movement or strong resonance.

## CLOCK
CLOCK SETTINGS

Choose CLOCK on the main MODE control to expose this page. These settings add modulation without rewriting natural BANK levels.

MODE chooses SHIFT or ROTATE or TURING or WALK. Changing it clears incompatible temporary modulation.

DIRECTION sets movement. SHIFT offers FORWARD or REVERSE or RANDOM. ROTATE offers FORWARD or REVERSE. TURING also offers PING PONG. WALK uses RANDOM and skips this control.

SOURCE selects AUTO or INTERNAL or EXTERNAL clock. AUTO uses the assigned CLK jack while patched and otherwise the internal clock. A patched but stopped clock stays external.

BPM sets internal tempo from 15 to 300. It stays editable with an external clock. DEPTH scales modulation without erasing its pattern. Set it low to begin.

SHIFT captures DATA on each rising edge and moves older values through all ten positions. Disabled bands act as silent gaps. DATA chooses CV or RANDOM or AUTO. AUTO uses patched DAT and otherwise random values.

ROTATE circulates a copy of the natural level shape through enabled bands. It adds this moving copy without changing the original levels.

WALK reflects random motion at its limits. STYLE ALL walks every enabled band. STYLE BAND moves one cursor through enabled bands. DRUNK chooses one to four landings. CHANCE sets how often a stumble starts. Extra landings occur at quarter clock intervals.

TURING evolves a repeating random loop. LENGTH sets two to ten steps. CHANGE sets mutation probability. BANDS ALL repeats it across enabled bands. RANGE places one copy beginning at START. Other bands get no TURING modulation.

TURING fills its loop before LCK can lock it. After filling LCK high repeats the loop unchanged. LCK low permits CHANGE mutations. PING PONG reverses after a full traversal. TURING ignores RST. Changing MODE or LENGTH starts a fresh fill.

For a self running patch choose SHIFT and SOURCE AUTO with CLK unplugged. Choose DATA RANDOM. Set BPM and raise DEPTH gradually.

## GROUPS
GROUPS PAGE

Each band column selects its membership in G1 through G4. Click the column and turn through the combinations. Lit cells show groups receiving that band. A band can feed several groups or none.

Groups feed OUTPUT routing. They also choose the enabled bands affected by group CV on INPUT. They are band buses and not input jack assignments.

Disabled bands cannot be edited here. BANK and CLOCK share group membership and output routing.

Try low bands in G1 and high bands in G2. Route these groups to different outputs to hear related CLOCK patterns.

## FEEDBACK
FEEDBACK PAGE

The ten band switches choose enabled resonators for the feedback tap. Click a switch to include or exclude that band. The main FEEDBACK control sets the overall return in BANK and CLOCK.

KNEE sets where soft limiting starts. Signal below it is unchanged. Above it the limiter bends the return toward CEILING.

CEILING sets the final loop limit. Its highlighted span shows the soft region between KNEE and CEILING. Lowering CEILING past KNEE lowers both. Raising KNEE past CEILING raises both. Equal values give hard limiting.

DAMPING restrains resonance as feedback rises. Higher settings are more conservative.

Select a few bands before raising FEEDBACK. If the sound overloads reduce feedback or DRIVE or RESONANCE. CLOCK movement can change how strongly a patch feeds the loop. Limiting does not make extreme settings quiet.

## OUTPUT
OUTPUT PAGE

Each OUT row mixes G1 through G4 and DRY. A zero send adds nothing. A full send gives unity gain. DRY adds the unfiltered mono input mix.

An OUT row header adjusts wet sends together. ROW DRY on OPTIONS decides if DRY follows. A column header adjusts that source across all outputs. Column edits ignore ROW DRY.

BANK and CLOCK share these sends. The OUT meters show final output level. Accent caps show clipping. Lower sends if the output mix clips.

Route groups to separate outputs for related patterns. Add DRY only when you want some original input too.

## OPTIONS
OPTIONS PAGE

PALETTE changes display colors without changing audio.

ROW DRY sets output row editing. INCLUDE adjusts DRY with wet groups. EXCLUDE leaves DRY untouched. Individual cells and column edits remain available in either setting.

SAVE DEFAULT stores the static setup and CLOCK settings in the current bitstream slot. It does not store the temporary generated pattern. SAVING shows a write in progress. SAVED confirms success. ERROR means the write failed. NO SLOT means saving is unavailable.

Edits are not saved automatically. Audition the patch at a safe level before saving it. Startup restores saved feedback too.
<!-- HELP END -->
