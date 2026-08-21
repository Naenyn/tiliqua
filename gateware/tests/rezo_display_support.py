async def sample_native_rgb(ctx, dut, points, *, rotate_left=False):
    """Sample native-canvas points after mapping them to video coordinates."""
    samples = []
    for panel_x, panel_y in points:
        if rotate_left:
            physical_x = 719 - panel_y
            physical_y = panel_x
        else:
            physical_x = dut.x_offset + panel_x
            physical_y = panel_y
        ctx.set(dut.x, physical_x)
        ctx.set(dut.y, physical_y)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append((ctx.get(dut.r), ctx.get(dut.g), ctx.get(dut.b)))
    return samples
