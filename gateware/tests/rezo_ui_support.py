def fast_click_ui(ui_type):
    """Return a UI subtype with production debounce reduced for simulation."""

    class FastClickUI(ui_type):
        CLICK_LOCKOUT_CYCLES = 1

    FastClickUI.__name__ = f"FastClick{ui_type.__name__}"
    return FastClickUI


async def hold(ctx, signal, value, cycles=4):
    ctx.set(signal, value)
    for _ in range(cycles):
        await ctx.tick()


async def click(ctx, dut):
    await hold(ctx, dut.button, 1, 5)
    await hold(ctx, dut.button, 0, 5)


async def turn(ctx, dut, endpoint, direction):
    """Emit one complete detent and return its new 00/11 endpoint."""
    if direction == 1:
        states = (0b10, 0b11) if endpoint == 0b00 else (0b01, 0b00)
    else:
        states = (0b01, 0b11) if endpoint == 0b00 else (0b10, 0b00)
    for state in states:
        ctx.set(dut.enc_i, state & 1)
        ctx.set(dut.enc_q, (state >> 1) & 1)
        for _ in range(4):
            await ctx.tick()
    return states[-1]
