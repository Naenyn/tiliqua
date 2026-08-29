# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Immutable display assets shared by the REZO family."""


# The font is stored as seven five-bit rows per glyph.  Keeping the packed
# source here avoids maintaining the same large Python dictionary in every
# bitstream while still producing the exact glyph initialization data used by
# the tile renderers.
_FONT_CHARS = " 0123456789.ABCDEFGHIKLMNOPQRSTUVWXYZ"
_FONT_ROWS = bytes.fromhex(
    "000000000000000e11131519110e040c040404040e0e11010204081f1e01010e01011e02"
    "060a121f02021f10101e01011e0608101e11110e1f0102040808080e11110e11110e0e11"
    "110f01020c00000000000c0c0e11111f1111111e11111e11111e0e11101010110e1e1111"
    "1111111e1f10101e10101f1f10101e1010100e11101711110e1111111f1111110e040404"
    "04040e111214181412111010101010101f111b1515111111111915131111110e11111111"
    "110e1e11111e1010100e11111115120d1e11111e1412110f10100e01011e1f0404040404"
    "041111111111110e11111111110a041111111515150a11110a040a111111110a04040404"
    "1f01020408101f"
)
FONT_5X7 = {
    char: tuple(_FONT_ROWS[index:index + 7])
    for index, char in ((index * 7, char)
                        for index, char in enumerate(_FONT_CHARS))
}

TILE_CHARS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
STEREO_TILE_CHARS = " 0123456789.ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Semantic palette roles are shared contracts.  Product renderers retain
# their local geometry and pixel equations because small structural changes to
# those expressions can materially alter ECP5 packing.
SEMANTIC_PALETTE = {
    "selected": 0xff,
    "text": 0xee,
    "control": 0xb8,
    "modulation": 0x78,
    "line": 0x88,
    "panel": 0x32,
    "background": 0x0A,
    "blank": 0x00,
    "surface": 0x14,
}
PALETTE_ROLES = (
    "selected", "text", "control", "modulation",
    "line", "panel", "background", "surface",
)
RGB_PALETTES = (
    (0xFFFFFF, 0xEEEEEE, 0xB8B8B8, 0x787878,
     0x888888, 0x323232, 0x0A0A0A, 0x141414),
    (0xFFF4CC, 0xFFD166, 0xC98A20, 0x4EA5D9,
     0x9A6A22, 0x35270F, 0x0C0803, 0x171006),
    (0xF4FFFF, 0xC8F7F8, 0x55CBCD, 0xFF7F6A,
     0x2A9D9F, 0x16383A, 0x040C0C, 0x071718),
    (0xF3FFF6, 0xD8F3DC, 0x74C69D, 0xE56BCE,
     0x40916C, 0x1B4332, 0x040E0B, 0x081C15),
    (0xFFF8DA, 0xE7DCF5, 0x9D7AD2, 0xF2C14E,
     0x6C4AA3, 0x2B1D3A, 0x08050C, 0x100A18),
    (0xFFF1C1, 0xFFD166, 0xE63946, 0xFF8C42,
     0xA92732, 0x47151A, 0x100405, 0x230A0D),
    (0xFFF0FF, 0xE9D5FF, 0x9B5DE5, 0x00E5FF,
     0x6D3CB7, 0x2A1747, 0x08040F, 0x140A24),
    (0xF5F1FF, 0xC9D6FF, 0x4361EE, 0xF72585,
     0x3A4AB8, 0x171D52, 0x040617, 0x0B0F2D),
)
