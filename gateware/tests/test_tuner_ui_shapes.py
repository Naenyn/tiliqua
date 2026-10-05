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
            if s!=6 && s!=7 && !(s==9 && n==1) { if let Some(f)=controls::field(*surface,n) {
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
    # Help TOPIC also uses a firmware-owned outline; SCROLL remains hardware-owned.
    # Routes and Configs now use firmware-owned sparse shapes in the background
    # banks (covered by intono_route_render). The qualified FPGA retains the
    # legacy Configs descriptors, but they are disabled for those views.
    # Their common tabs/footer still come from this hardware border layer.
    assert ACTIONS[7]==[] and FIELDS[7]==[]
    assert {s:sorted(v) for s,v in actual.items()}=={s:sorted([*ACTIONS.get(s,()),*FIELDS.get(s,())]) for s in set(ACTIONS)|set(FIELDS) if s not in (6,7)}
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
        for surface,row in [(0,3),(0,4),(0,18),(1,5),(1,6),(1,16),(2,14),(3,19),(4,5),(4,6),(4,16),(4,18),(5,18),(7,9),(8,20),(10,3),(10,5),(10,7),(11,3),(12,3),(13,20),(14,3),(14,18)]:
            ctx.set(dut.surface,surface)
            for left,width,index in descriptors(surface,row):
                ctx.set(dut.focus,index)
                selected= index==({0:0,1:1,2:1,3:1,4:2,5:2,6:3,7:3,10:3,11:3,12:3,14:0}.get(surface,-1)) if row==3 else ((surface==8+index or (surface==13 and index==0)) if row==20 else True)
                expected_color=(0x69 if row in (3,20) else 0xF9) if selected else 0x49
                # All corner pixels, straight sides, centers, and outside rows.
                for yy in [-1,0,1,2,3,4,5,6,13,21,22,23,24,25,26,27,28]:
                    for xx in [-1,0,1,2,3,4,5,6,7,width//2,width-8,width-7,width-6,width-5,width-4,width-3,width-2,width-1,width]:
                        compact=surface==0 and row==4
                        height,radius=(21,4) if compact else (28,6)
                        if compact and yy==-1:
                            continue  # y=124 belongs to the separately tested header rule.
                        want=inside(xx,yy,width,height,radius) and not inside(xx-2,yy-2,width-4,height-4,radius-2)
                        hit,color=await sample(ctx,left+xx,row*32-6+yy+(3 if compact else 0))
                        # Adjacent boxes never overlap; sampled outside pixels
                        # are deliberately at most one pixel beyond this box.
                        assert hit==want,(surface,row,xx,yy,hit,want)
                        if want:assert color==expected_color
        ctx.set(dut.active,0)
        hit,_=await sample(ctx,174,506);assert hit==0
    sim.add_testbench(bench);sim.run()


def test_page_indicators_and_separators_follow_parent_page():
    dut=RoundedBorders();sim=Simulator(dut);sim.add_clock(1e-6,domain='dvi')
    async def bench(ctx):
        ctx.set(dut.active,1)
        for surface,page in enumerate([0,1,1,1,2,2,3,3,4,5,3,3,3,4,0]):
            ctx.set(dut.surface,surface)
            for index in range(6):
                center=330+index*12
                if index!=page:center+=-4 if index<page else 4
                ctx.set(dut.x,center);ctx.set(dut.y,70)
                await ctx.tick('dvi').repeat(4)
                assert ctx.get(dut.hit)==(index==page),(surface,index)
                if index==page:assert ctx.get(dut.color)==0xB9
                ctx.set(dut.y,62)
                await ctx.tick('dvi').repeat(4)
                assert ctx.get(dut.hit)==1
            for y,left,right in [(124,144,576),(631,228,492)]:
                for x in [left-1,left,(left+right)//2,right-1,right]:
                    ctx.set(dut.x,x);ctx.set(dut.y,y)
                    await ctx.tick('dvi').repeat(4)
                    assert ctx.get(dut.hit)==(left<=x<right)
            ctx.set(dut.active,0);ctx.set(dut.x,330+page*12);ctx.set(dut.y,70)
            await ctx.tick('dvi').repeat(4)
            assert ctx.get(dut.hit)==0
            ctx.set(dut.active,1)
    sim.add_testbench(bench);sim.run()


def test_linear_focus_outline_is_hidden_but_view_remains():
    dut=RoundedBorders();sim=Simulator(dut);sim.add_clock(1e-6,domain='dvi')
    async def bench(ctx):
        ctx.set(dut.active,1)
        for surface,focus_visible in [(0,True),(14,False)]:
            ctx.set(dut.surface,surface)
            ctx.set(dut.y,126);ctx.set(dut.x,300);await ctx.tick('dvi').repeat(4)
            assert ctx.get(dut.hit)==focus_visible
            ctx.set(dut.y,570);ctx.set(dut.x,300);await ctx.tick('dvi').repeat(4)
            assert ctx.get(dut.hit)==1
    sim.add_testbench(bench);sim.run()


def test_page_navigation_and_value_edit_have_distinct_fills():
    dut=RoundedBorders();sim=Simulator(dut);sim.add_clock(1e-6,domain="dvi")
    async def sample(ctx,x,y):
        ctx.set(dut.x,x);ctx.set(dut.y,y)
        await ctx.tick("dvi").repeat(5)
        return ctx.get(dut.hit),ctx.get(dut.color)
    async def bench(ctx):
        ctx.set(dut.active,1);ctx.set(dut.surface,0);ctx.set(dut.focus,1)
        for mode in range(3):
            ctx.set(dut.mode,mode)
            hit,color=await sample(ctx,198,103)
            assert hit==(mode==0)
            if hit:assert color==0xB9
            hit,color=await sample(ctx,198,90)
            assert hit and color==(0xB9 if mode==0 else 0x69)
            hit,color=await sample(ctx,248,580)
            assert hit==(mode==2)
            if hit:assert color==0xF9
        ctx.set(dut.surface,13);ctx.set(dut.mode,0)
        assert (await sample(ctx,300,647))==(1,0xB9)
    sim.add_testbench(bench);sim.run()


def test_reference_panel_keeps_tuner_chrome_without_body_controls():
    dut=RoundedBorders();sim=Simulator(dut);sim.add_clock(1e-6,domain="dvi")
    async def bench(ctx):
        ctx.set(dut.active,1);ctx.set(dut.surface,15);ctx.set(dut.mode,0)
        for x,y,hit,color in [(198,103,1,0xB9),(300,126,0,0),(248,570,0,0),(330,60,1,0xB9)]:
            ctx.set(dut.x,x);ctx.set(dut.y,y);await ctx.tick("dvi").repeat(5)
            assert ctx.get(dut.hit)==hit
            if hit:assert ctx.get(dut.color)==color
    sim.add_testbench(bench);sim.run()
