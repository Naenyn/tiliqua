"""Rounded scanline borders and firmware/layout agreement."""
import subprocess
from pathlib import Path

from amaranth.sim import Simulator
from top.intono.ui_shapes import RoundedBorders, ACTIONS, FIELDS, descriptors, column


def test_shape_positions_match_firmware_controls(tmp_path):
    root=Path(__file__).resolve().parents[1]
    module=root/'src/top/intono/fw/src/ui_controls.rs'
    source=tmp_path/'controls.rs'
    source.write_text(f'#[path="{module}"] mod controls;\n'+'''
fn main() {
    use controls::Surface::*;
    for (s,surface) in [Tuner,Calibration,Profiles,Check,Scales,Notes,Setups,Routes,Settings,Help,Midi].iter().enumerate() {
        for n in 0..16 {
            if s!=7 { if let Some(f)=controls::field(*surface,n) {
                println!("{} {} {} {} {}",s,n,f.column,f.row,f.width);
            } }
        }
    }
}
''')
    binary=tmp_path/'controls'
    subprocess.run(['rustc','--edition=2021',str(source),'-o',str(binary)],check=True,capture_output=True)
    actual={}
    for line in subprocess.check_output([str(binary)],text=True).splitlines():
        s,i,c,r,w=map(int,line.split());actual.setdefault(s,[]).append((i,c,r,w))
    # Routes now retain dynamic cards/flow shapes in the background banks.
    # Their common tabs/footer still come from this hardware border layer.
    assert ACTIONS[7]==[] and FIELDS[7]==[]
    assert {s:sorted(v) for s,v in actual.items()}=={s:sorted([*ACTIONS.get(s,()),*FIELDS.get(s,())]) for s in set(ACTIONS)|set(FIELDS) if s!=7}
    for surface in range(11):
        for row in range(22):
            boxes=descriptors(surface,row)
            for left,width,_ in boxes:
                for x in (left,left+width-1):
                    for y in (row*32-6,row*32+21):
                        assert (x-360)**2+(y-360)**2<=360**2
            for (left,width,_),(next_left,_,_) in zip(sorted(boxes),sorted(boxes)[1:]):
                assert left+width<=next_left


def inside(px,py,width,height,radius):
    if not (0<=px<width and 0<=py<height):return False
    dx=max(radius-px,px-(width-1-radius),0)
    dy=max(radius-py,py-(height-1-radius),0)
    return dx*dx+dy*dy<=radius*radius


def test_border_pixels_and_focus_match_rounded_reference():
    dut=RoundedBorders();sim=Simulator(dut);sim.add_clock(1e-6,domain='dvi')
    async def sample(ctx,x,y):
        ctx.set(dut.x,x);ctx.set(dut.y,y)
        await ctx.tick('dvi').repeat(5)
        return ctx.get(dut.hit),ctx.get(dut.color)
    async def bench(ctx):
        ctx.set(dut.active,1)
        for surface,row in [(0,3),(0,18),(1,5),(1,6),(1,16),(2,14),(3,19),(4,5),(4,6),(4,16),(4,18),(5,18),(7,9),(8,20),(10,3),(10,5),(10,7)]:
            ctx.set(dut.surface,surface)
            for left,width,index in descriptors(surface,row):
                ctx.set(dut.focus,index)
                selected= index==({0:0,1:1,2:1,3:1,4:2,5:2,6:3,7:3,10:3}.get(surface,-1)) if row==3 else (surface==8+index if row==20 else True)
                expected_color=(0xB9 if row in (3,20) else 0xF9) if selected else 0x49
                # All corner pixels, straight sides, centers, and outside rows.
                for yy in [-1,0,1,2,3,4,5,6,13,21,22,23,24,25,26,27,28]:
                    for xx in [-1,0,1,2,3,4,5,6,7,width//2,width-8,width-7,width-6,width-5,width-4,width-3,width-2,width-1,width]:
                        want=inside(xx,yy,width,28,6) and not inside(xx-2,yy-2,width-4,24,4)
                        hit,color=await sample(ctx,left+xx,row*32-6+yy)
                        # Adjacent boxes never overlap; sampled outside pixels
                        # are deliberately at most one pixel beyond this box.
                        assert hit==want,(surface,row,xx,yy,hit,want)
                        if want:assert color==expected_color
        ctx.set(dut.active,0)
        hit,_=await sample(ctx,174,506);assert hit==0
    sim.add_testbench(bench);sim.run()
