# Tiliqua

This is Naenyn's fork of [apf.audio's Tiliqua project](https://github.com/apfaudio/tiliqua),
with additional bitstreams and an Intono profile librarian. Development lives on
the [`naenyn` branch](https://github.com/Naenyn/tiliqua/tree/naenyn).

**Tiliqua is a powerful, open hardware FPGA-based audio multitool for Eurorack.** It looks like this:

![image](https://github.com/user-attachments/assets/1dbe8672-6f8d-4d33-b0d6-634b90801f7d)

# ⮕[Documentation](https://apfaudio.github.io/tiliqua/)⬅

## Bitstreams added in this fork

The bitstreams below are listed in development order. **REZO, REZOMO, and
STREZO form the REZO family**: three related bitstreams built around a shared
ten-band resonant filterbank.

| Bitstream | What it does | Documentation / source |
|---|---|---|
| **OSCIO** | Four-channel oscilloscope with a CV/LFO history view and signal measurements | [Overview and source](gateware/src/top/oscio/top.py) |
| **SONORO** | Spectrum analyzer and 2D spectrograph with selectable input and spectral history | [Overview and source](gateware/src/top/sonoro/top.py) |
| **CASCADO** | 3D spectrogram with filled terrain and wire ridge views | [Overview and source](gateware/src/top/cascado/top.py) |
| **REZO** | Ten-band mono resonant filterbank with shaped low-pass, high-pass, band-pass, and notch responses | [User guide](gateware/src/top/rezo/REZO_USER_GUIDE.md) |
| **REZOMO** | Clock-oriented mono resonant filterbank with generated modulation | [User guide](gateware/src/top/rezo/REZOMO_USER_GUIDE.md) |
| **STREZO** | Linked stereo resonant filterbank with frequency motion, feedback routing, and mid/side shaping | [User guide](gateware/src/top/rezo/STREZO_USER_GUIDE.md) |
| **INTONO** | Four-input tuner, oscillator calibration, and CV routing with per-output quantization, calibration correction, and MIDI transposition | [Intono documentation](gateware/src/top/intono/README.md) |

### Intono Profile Library

**[Open the Intono librarian](https://naenyn.github.io/tiliqua/intono/)** in desktop
Chrome or Edge to manage named calibration profiles, user scales, and route
configs. It supports Scala imports, whole-library backups, and verified writes
to the instrument through Tiliqua's USB debug serial connection. Profile data
stays in your browser and on the connected instrument; no local web server is
needed. Musical MIDI uses the separate 3.5 mm MIDI input.

See the [librarian guide](web/intono/README.md) for the connection and editing
workflow, supported formats, and limitations. Each category has eight saved slots.

The [REZO family documentation](gateware/src/top/rezo/README.md) covers its display
variants and build instructions. Intono build and hardware qualification details
are in its documentation linked above. Demo and tutorial videos will be linked
here as they become available.

# Updates / Community

For updates, subscribe to the [Crowd Supply page](https://www.crowdsupply.com/apfaudio/tiliqua), join the [matrix chatroom](https://matrix.to/#/#apfaudio:matrix.org), or my own [mailing list](https://apf.audio/).

`apfaudio` has a Matrix channel, [#apfaudio:matrix.org](https://matrix.to/#/#apfaudio:matrix.org). Feel free to join to ask questions or discuss ongoing development.

Participants in this project are expected to adhere to the [Berlin Code of Conduct](https://berlincodeofconduct.org/).

# Contributing

For contribution guidelines and our policy on AI/LLM usage, see [CONTRIBUTING.md](CONTRIBUTING.md).

# Acknowledgements

This project would be nothing without the hard work of many (awesome) open-source projects. An exhaustive list would take pages, here I mention only a crucial subset:

- Python-based HDL and SoC framework: The [Amaranth HDL](https://github.com/amaranth-lang/amaranth) and [Amaranth SoC](https://github.com/amaranth-lang/amaranth-soc) projects.
- USB and SoC gateware: The [LUNA and Cynthion](https://github.com/greatscottgadgets/luna/) projects.
- RISCV softcore: The [VexRiscv and SpinalHDL projects](https://github.com/SpinalHDL/VexRiscv)
- USB audio gateware and descriptors: The [adat-usb2-audio-interface](https://github.com/hansfbaier/adat-usb2-audio-interface) project.
- Some gateware (e.g. I2C state machines) are inherited from the [Glasgow](https://github.com/GlasgowEmbedded/glasgow) project.
- Audio interface and gateware: my existing [eurorack-pmod](https://github.com/apfaudio/eurorack-pmod) project.
- SID emulation gateware: [reDIP-SID](https://github.com/daglem/reDIP-SID)
- The "mi-plaits-dsp-rs" project: [mi-plaits-dsp](https://github.com/sourcebox/mi-plaits-dsp-rs)
- The "pico-dirtyJtag" project forms a big chunk of the RP2040 firmware [pico-dirtyJtag](https://github.com/phdussud/pico-dirtyJtag)

## Funding

We would like to acknowledge partial funding of the [Tiliqua project](https://nlnet.nl/project/Tiliqua/) from the [NGI Commons Fund](https://nlnet.nl/commonsfund), a fund established by [NLnet](https://nlnet.nl/) with financial support from the European Commission’s [Next Generation Internet](https://ngi.eu/) program.

![image](https://nlnet.nl/logo/banner-320x120.png)

# License

The hardware and gateware in this project is largely covered under the CERN Open-Hardware License V2 CERN-OHL-S, mirrored in the LICENSE text in this repository. Some gateware and software is covered under the BSD 3-clause license - check the header of the individual source files for specifics.

**Copyright (C) 2024 Sebastian Holzapfel**

The above LICENSE and copyright notice do NOT apply to imported artifacts in this repository (i.e datasheets, third-party footprints), or dependencies released under a different (but compatible) open-source license.

# Derivative works

As an addendum to the above license: if you create or manufacture your own derivative hardware, the name `apf.audio`, the names of any `apf.audio` products and the names of the authors, are *not to be used in derivative hardware or marketing materials*, except where obligated for attribution and for retaining the above copyright notice.

For example, your 3U adaptation of "apf.audio Tiliqua" could be called "Gizzard Modular - Lizardbobulator".
