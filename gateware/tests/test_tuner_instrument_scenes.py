"""CPU-generated synthetic graphs through the actual production compositor.

These are integration fixtures, not implemented calibrator/quantizer modes.
"""
from collections import deque
from pathlib import Path
import shutil
import subprocess

import pytest
from amaranth import Module, unsigned
from amaranth.lib.memory import Memory
from amaranth.sim import Simulator

from top.intono.display import IntonoOverlay
from top.intono.renderer import TextPlane, Panel
from test_tuner_renderer import atlas, text_cells, reference_pixel


@pytest.fixture(scope="module")
def retained_scenes(tmp_path_factory):
    rustc = shutil.which("rustc") or str(Path.home()/".cargo/bin/rustc")
    executable = tmp_path_factory.mktemp("instrument-scenes")/"fixture"
    subprocess.run([rustc, "--edition=2021", "-Awarnings",
                    str(Path(__file__).with_name("tuner_scene_fixture.rs")),
                    "-o", str(executable)], check=True)
    result = {}
    for scene in ("tuner", "calibrator", "quantizer"):
        run = subprocess.run([str(executable),scene], check=True, capture_output=True)
        assert len(run.stdout) == 720*720
        print(run.stderr.decode().strip())
        result[scene] = run.stdout
    return result


@pytest.mark.parametrize("scene", ["tuner", "calibrator", "quantizer"])
@pytest.mark.parametrize("menu_enabled", [False, True])
def test_retained_instrument_graphics_with_production_text(scene, menu_enabled, retained_scenes):
    planes = [TextPlane(90,0,45,45,pitch_x=12,cell_color=True),
              TextPlane(IntonoOverlay.MENU_TEXT_X,IntonoOverlay.MENU_TEXT_Y,28,9,
                        pitch_x=9,pitch_y=18,color=0xA9)]
    panels = [None,Panel(IntonoOverlay.MENU_X,IntonoOverlay.MENU_Y,
                         IntonoOverlay.MENU_W,IntonoOverlay.MENU_H,
                         rule_x=85,rule_y=8,rule_height=54)]
    entries = [(8,8,"SYNTHETIC UI TEST",0xF9,True)]
    if scene == "tuner":
        entries += [(5,row,f"IN{ch}  A#3  +02.4c",color,False)
                    for ch,(row,color) in enumerate(zip((12,18,25,31),(0xF2,0xF5,0xF9,0xFC)))]
    elif scene == "calibrator":
        entries += [(5,11,"Profile: VCO North-01",0xD9,False),
                    (5,13,"Tracking error: +/-50c",0xF5,False),
                    (5,35,"Points: 9   Test data",0xD9,False)]
    else:
        entries += [(5,11,"Scale: Custom 19-EDO",0xD9,False),
                    (5,13,"Octaves 0-7 / 12 cells",0xF9,False),
                    (5,35,"Synthetic scale grid",0xD9,False)]
    contents = [text_cells(planes[0],entries),
                text_cells(planes[1],[(0,0,"SETTINGS",0,True),
                                      (10,0,"a4 ref 440",0,False)])]
    tiles = Memory(shape=unsigned(16),depth=4096,init=contents[0])
    menu = Memory(shape=unsigned(8),depth=512,init=contents[1])
    dut = IntonoOverlay(tiles,menu,h_active=1280,ascii_text=True,double_buffered=True)
    m = Module()
    m.submodules.dut,m.submodules.tiles,m.submodules.menu = dut,tiles,menu
    sim = Simulator(m)
    sim.add_clock(1e-6,domain="dvi")
    font = atlas()

    async def bench(ctx):
        ctx.set(dut.menu_active,menu_enabled)
        queue = deque()
        # Sample graph/text rows and menu borders with consecutive scanlines.
        # Compare delayed coordinates and pixels together.
        rows = sorted(set(range(256,513,8)) | {128,135,192,199,224,288,328,
                      341,342,343,349,350,355,360,400,432,496,500,501,502,536,560,567})
        for y in rows:
            for x in range(140,710):
                de = x != 140
                bg = retained_scenes[scene][y*720+x]
                expected = reference_pixel(x,y,bg,1 | (int(menu_enabled)<<1),
                                           planes,panels,contents,font) if de else 0
                ctx.set(dut.i.x,x+280)
                ctx.set(dut.i.y,y)
                ctx.set(dut.i.de,de)
                ctx.set(dut.i.pixel.as_value(),bg)
                queue.append((x+280,y,expected))
                await ctx.tick("dvi")
                if len(queue)>=dut.LATENCY:
                    assert (ctx.get(dut.o.x),ctx.get(dut.o.y),ctx.get(dut.o.pixel.as_value())) == queue.popleft()
        for _ in range(dut.LATENCY-1):
            await ctx.tick("dvi")
            assert (ctx.get(dut.o.x),ctx.get(dut.o.y),ctx.get(dut.o.pixel.as_value())) == queue.popleft()

    sim.add_testbench(bench)
    sim.run()
