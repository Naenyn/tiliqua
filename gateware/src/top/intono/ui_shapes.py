"""Scanline-rounded UI borders, aligned with the existing four-cycle overlay."""
from math import isqrt
from amaranth import Array, Cat, Const, Module, Mux, Signal, unsigned, signed
from amaranth.lib.memory import Memory
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out

# Surface IDs 0..10 match firmware ui_controls::Surface. IDs 11/12/13
# identify retained Configs/MIDI/Preferences views without legacy field borders.
# ID 10 identifies imported scales with retained body geometry. The old MIDI
# descriptors remain for layout compatibility; MIDI now publishes ID 12.
# ID 14 is the linear tuner, which omits the arc-only FOCUS control.
# Descriptors are (option, col, row, width).
ACTIONS = {
    0: [(2,15,18,12)],
    1: [(5,3,16,7),(6,12,16,7),(7,20,16,7),(8,8,18,14)],
    2: [(3,4,14,10),(4,16,14,10),(5,4,16,10),(6,16,16,10)],
    3: [(0,4,16,10),(1,16,16,10),(2,4,18,10),(3,16,18,10),(4,11,19,8)],
    4: [(5,15,16,12),(11,12,18,7),(12,20,18,7)],
    5: [(3,4,17,10),(4,16,17,10),(6,3,18,7),(7,12,18,7),(11,20,18,7),(5,16,16,10)],
    6: [(1,4,16,10),(2,16,16,10),(3,10,17,10)],
    10: [(3,16,7,10)],
    7: [], # Route cards/flow/editors use sparse retained PSRAM geometry.
    8: [(1,16,5,10),(2,4,7,10)],
}

# Compact editable fields share the action outline style. All route selectors,
# including profile selection, fit one row with room between the two columns.
FIELDS = {
    0: [(0,8,4,14),(1,3,18,10)],
    1: [(0,3,5,6),(1,10,5,6),(3,8,6,14),(4,17,5,10)],
    2: [(0,10,5,10),(1,4,10,10),(2,16,10,10)],
    4: [(0,3,5,9),(1,14,5,13),(9,3,16,10),(8,29,10,3),(10,3,18,7)],
    5: [(8,4,5,10),(9,16,5,10),(10,29,10,3),(0,4,16,10)],
    6: [(0,10,5,10)],
    7: [], # Route cards/flow/editors use sparse retained PSRAM geometry.
    8: [(0,4,5,10)],
    9: [(0,10,17,10)],
    10: [(0,4,5,10),(1,16,5,10),(2,4,7,10),(4,10,9,10)],
}

def column(c): return (c*4+1)//3

def descriptors(surface, row):
    if row == 3:
        return [(120+c*12+4,100,index) for index,c in enumerate((2,11,20,29))]
    if row == 20:
        return [(120+column(c)*12-4,(column(c+w)-column(c))*12+8,index)
                for index,c,w in ((0,8,7),(1,17,4))]
    return [(120+column(c)*12-4,(column(c+w)-column(c))*12+8,index)
            for index,c,r,w in (*ACTIONS.get(0 if surface==14 else surface,()),*(FIELDS[0][1:] if surface==14 else FIELDS.get(surface,()))) if r==row]

class RoundedBorders(wiring.Component):
    def __init__(self):
        super().__init__({"x":In(signed(12)),
            "y":In(signed(12)),"active":In(1),"surface":In(4),"focus":In(5),"mode":In(2,init=1),
            "keyboard_second":In(1,init=1),"hit":Out(1),"color":Out(8)})

    def elaborate(self, platform):
        m=Module()
        words=[]
        for surface in range(11):
            for row in range(32):
                shapes=descriptors(surface,row)
                assert len(shapes)<=4
                word=0
                for n,(left,width,index) in enumerate(shapes):
                    assert 0<=left<720 and 0<width<256 and 0<=index<16
                    word|=(left|(width<<10)|(index<<18))<<(n*22)
                words.append(word)
        memory=Memory(shape=unsigned(88),depth=352,init=words,attrs={"ram_style":"block"})
        port=memory.read_port(domain="dvi");m.submodules.geometry=memory
        row=(self.y+6)[5:10]
        # Retained views reuse the common-only Routes geometry ROM entry.
        geometry_surface=Mux(self.surface==14,0,Mux((self.surface>=11)|(self.surface==10),7,self.surface))
        m.d.comb += [port.addr.eq(Cat(row,geometry_surface)),port.en.eq(self.active)]
        y1=Signal(signed(12));x1=Signal(10);ly1=Signal(5);row1=Signal(5);active1=Signal();surface1=Signal(4);focus1=Signal(5);mode1=Signal(2);second1=Signal()
        m.d.dvi += [y1.eq(self.y),x1.eq(self.x),ly1.eq((self.y+6)[:5]),row1.eq(row),active1.eq(self.active),
                    surface1.eq(self.surface),focus1.eq(self.focus),mode1.eq(self.mode),second1.eq(self.keyboard_second)]
        # Compute curve insets once per scanline before the per-box tests.
        outer=Array(Const(6-isqrt(36-(6-min(y,27-y))**2),4) if min(y,27-y)<6 else Const(0,4)
                    for y in range(28))
        inner=Array(Const(4-isqrt(16-(4-min(y,23-y))**2),4) if min(y,23-y)<4 else Const(0,4)
                    for y in range(24))
        off2=Signal(4);inner_off2=Signal(4)
        # Arc input text occupies y=128..142. A 21-pixel outline at
        # y=125..145 gives equal three-pixel padding and clears the rule.
        compact1=(surface1==0)&(row1==4)
        shape_y=Mux(compact1,ly1-3,ly1)
        compact_outer=Array(Const(4-isqrt(16-(4-min(y,20-y))**2),4) if min(y,20-y)<4 else Const(0,4)
                            for y in range(21))
        compact_inner=Array(Const(2-isqrt(4-(2-min(y,16-y))**2),4) if min(y,16-y)<2 else Const(0,4)
                            for y in range(17))
        compact2=Signal()
        m.d.dvi += [compact2.eq(compact1),
                    off2.eq(Mux(compact1,compact_outer[shape_y],outer[shape_y])),
                    inner_off2.eq(Mux(compact1,compact_inner[shape_y-2],inner[shape_y-2])+2)]
        hits=[];colors=[]
        for n in range(4):
            descriptor=port.data[n*22:(n+1)*22]
            left,width,index=descriptor[:10],descriptor[10:18],descriptor[18:22]
            # Negative relative coordinates wrap above 255, outside every box.
            rx2=Signal(10)
            width2=Signal(8);ly2=Signal(5);active2=Signal();selected2=Signal();tab2=Signal();mode2=Signal(2)
            category=Mux((surface1==0)|(surface1==14)|(surface1==15),0,Mux(surface1<=3,1,Mux((surface1<=5)|(surface1==10),2,3)))
            selected=Mux(row1==3,((surface1<8)|((surface1>=10)&(surface1<=12))|(surface1==14)|(surface1==15))&(index==category),
                         Mux(row1==20,((surface1==8+index)|((surface1==13)&(index==0))),index==focus1))
            m.d.dvi += [rx2.eq(x1-left),width2.eq(width),ly2.eq(shape_y),active2.eq(active1 & (width!=0) & ~((surface1==14)&(row1==4)&(index==0)) & ~(~second1 & (((surface1==4)&(index==8))|((surface1==5)&(index==10))) & (row1!=3) & (row1!=20))),
                        selected2.eq(selected),tab2.eq((row1==3)|(row1==20)),mode2.eq(mode1)]
            inside=(ly2<Mux(compact2,21,28))&(rx2>=off2)&(rx2<width2-off2)
            inset=(ly2>=2)&(ly2<Mux(compact2,19,26))&(rx2>=inner_off2)&(rx2<width2-inner_off2)
            hit3=Signal();color3=Signal(8)
            m.d.dvi += [hit3.eq(active2 & inside & (~inset | (selected2 & Mux(tab2,mode2==0,mode2==2)))),
                        color3.eq(Mux(selected2,Mux(tab2,Mux(mode2==0,0xB9,0x69),0xF9),0x49))]
            hits.append(hit3);colors.append(color3)
        # Six boxes follow the visible navigation order, including subpages.
        page=Mux((self.surface==0)|(self.surface==14)|(self.surface==15),0,Mux(self.surface<=3,1,Mux((self.surface<=5)|(self.surface==10),2,
             Mux((self.surface==8)|(self.surface==13),4,Mux(self.surface==9,5,3)))))
        # Constant spans replace a 2K-word ROM used for just six boxes.
        # Register the result to preserve the original ROM-read latency.
        word=Const(0,3)
        x=self.x[:8]
        for index in range(6):
            center=330+index*12-256
            selected=(page==index)
            left=page>index
            inside=Mux(left,(x>=center-9)&(x<=center+1),
                            (x>=center-1)&(x<=center+9))
            edge=Mux(left,(x<center-7)|(x>=center),
                          (x<center+1)|(x>=center+8))
            word=word | Mux(selected, Mux((x>=center-9)&(x<=center+9),4,0),
                           Mux(inside,Cat(Const(1,1),edge,Const(0,1)),0))
        pager_word=Signal(3)
        m.d.dvi += pager_word.eq(word)
        # Match the border layer's four-cycle latency.
        chrome_hit2=Signal();chrome_color2=Signal(8)
        current=pager_word[2]&(y1>=60)&(y1<81)
        other=pager_word[0]&(y1>=62)&(y1<78)&(pager_word[1]|(y1<64)|(y1>=76))
        pager_hit=(x1>=256)&(x1<512)&(current|other)
        separator=((y1==124)&(x1>=144)&(x1<576))|((y1==631)&(x1>=228)&(x1<492))
        m.d.dvi += [chrome_hit2.eq(active1&(pager_hit|separator)),
                    chrome_color2.eq(Mux(pager_hit&current,0xB9,0x49))]
        chrome_hit3=Signal();chrome_color3=Signal(8)
        m.d.dvi += [chrome_hit3.eq(chrome_hit2),chrome_color3.eq(chrome_color2)]
        hits.append(chrome_hit3);colors.append(chrome_color3)
        color=Signal(8);m.d.comb += color.eq(0x49)
        for hit,c in zip(hits,colors):
            with m.If(hit):m.d.comb += color.eq(c)
        m.d.dvi += [self.hit.eq(Cat(*hits).any()),self.color.eq(color)]
        return m
