async def sample_video_rgb(ctx, dut, x, y, *, cycles=8):
    """Set one video coordinate and return its settled RGB value."""
    ctx.set(dut.x, x)
    ctx.set(dut.y, y)
    ctx.set(dut.de, 1)
    for _ in range(cycles):
        await ctx.tick("dvi")
    return ctx.get(dut.r), ctx.get(dut.g), ctx.get(dut.b)


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
        samples.append(await sample_video_rgb(
            ctx, dut, physical_x, physical_y, cycles=12))
    return samples


async def sample_panel_rgb(ctx, dut, panel_x, panel_y):
    """Sample an unrotated native-panel coordinate on standard video."""
    return await sample_video_rgb(
        ctx, dut, dut.x_offset + panel_x, panel_y)
