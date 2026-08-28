"""Small fixed REZO serializer floorplan, executed by nextpnr pre-placement."""

# The R5 board's four DVI outputs are fixed at the upper/right device edges.
# Keep only the 5x-clock shift registers and their local phase sources beside
# those pins; the rest of the 95%-utilized design remains unconstrained.
lane_x = (70, 49, 60, 65)
lane_names = (
    "tmds_ch0_shift",
    "tmds_ch1_shift",
    "tmds_ch2_shift",
    "tmds_clk_shift",
)
ff_bels = (
    "SLICEA.FF0",
    "SLICEA.FF1",
    "SLICEB.FF0",
    "SLICEB.FF1",
    "SLICEC.FF0",
    "SLICEC.FF1",
    "SLICED.FF0",
    "SLICED.FF1",
)

for lane, (x, lane_name) in enumerate(zip(lane_x, lane_names)):
    phase_name = f"dvi_gen.shift5_{lane}_0_TRELLIS_FF_Q"
    ctx.bindBel(  # noqa: F821 - nextpnr injects ctx/STRENGTH_USER
        f"X{x}/Y2/SLICEA.FF0", ctx.cells[phase_name], STRENGTH_USER)
    for bit in range(10):
        y = 3 if bit < 8 else 4
        bel = ff_bels[bit] if bit < 8 else ff_bels[bit - 8]
        cell_name = f"dvi_gen.{lane_name}[{bit}]_TRELLIS_FF_Q"
        # Constant clock-lane bits can disappear during synthesis.
        if cell_name in ctx.cells:
            ctx.bindBel(  # noqa: F821
                f"X{x}/Y{y}/{bel}", ctx.cells[cell_name], STRENGTH_USER)
