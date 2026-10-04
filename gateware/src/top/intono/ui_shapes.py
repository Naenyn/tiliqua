"""Scanline-rounded UI borders, aligned with the existing four-cycle overlay."""
from math import isqrt
from amaranth import Array, Cat, Const, Module, Mux, Signal, unsigned, signed
from amaranth.lib.memory import Memory
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out

# Surface IDs 0..10 match firmware ui_controls::Surface. IDs 11/12/13
# identify retained Configs/MIDI/Preferences views without legacy field borders.
# ID 14 is the linear tuner, which omits the arc-only FOCUS control.
# Descriptors are (option, col, row, width).
ACTIONS = {
    1: [(5,3,16,7),(6,11,16,8),(7,20,16,8),(8,8,18,14)],
    2: [(3,4,14,10),(4,16,14,10),(5,4,16,10),(6,16,16,10)],
    3: [(0,4,16,10),(1,16,16,10),(2,4,18,10),(3,16,18,10),(4,11,19,8)],
    4: [(5,16,16,12),(11,16,18,6),(12,24,18,6)],
    5: [(3,4,17,10),(4,16,17,10),(6,4,18,7),(7,12,18,7),(5,16,16,10)],
    6: [(1,4,16,10),(2,16,16,10),(3,10,17,10)],
    10: [(3,16,7,10)],
    7: [], # Route cards/flow/editors use sparse retained PSRAM geometry.
    8: [(1,16,5,10),(2,4,7,10)],
}

# Compact editable fields share the action outline style. All route selectors,
# including profile selection, fit one row with room between the two columns.
FIELDS = {
    0: [(0,8,4,15),(1,10,18,10)],
    1: [(0,4,5,6),(1,11,5,6),(3,9,6,14),(4,18,5,12)],
    2: [(0,10,5,10),(1,4,10,10),(2,16,10,10)],
    4: [(0,4,5,10),(1,16,5,14),(9,4,6,10),(8,29,10,3),(10,4,18,10)],
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
            for index,c,r,w in (*ACTIONS.get(surface,()),*(FIELDS[0][1:] if surface==14 else FIELDS.get(surface,()))) if r==row]

class RoundedBorders(wiring.Component):
    def __init__(self):
        super().__init__({"x":In(signed(12)),
            "y":In(signed(12)),"active":In(1),"surface":In(4),"focus":In(5),
            "hit":Out(1),"color":Out(8)})

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
        geometry_surface=Mux(self.surface==14,0,Mux(self.surface>=11,7,self.surface))
        m.d.comb += [port.addr.eq(Cat(row,geometry_surface)),port.en.eq(self.active)]
        y1=Signal(signed(12));x1=Signal(10);ly1=Signal(5);row1=Signal(5);active1=Signal();surface1=Signal(4);focus1=Signal(5)
        m.d.dvi += [y1.eq(self.y),x1.eq(self.x),ly1.eq((self.y+6)[:5]),row1.eq(row),active1.eq(self.active & (self.surface<15)),
                    surface1.eq(self.surface),focus1.eq(self.focus)]
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
            width2=Signal(8);ly2=Signal(5);active2=Signal();selected2=Signal();tab2=Signal()
            category=Mux((surface1==0)|(surface1==14),0,Mux(surface1<=3,1,Mux(surface1<=5,2,3)))
            selected=Mux(row1==3,((surface1<8)|((surface1>=10)&(surface1<=12))|(surface1==14))&(index==category),
                         Mux(row1==20,((surface1==8+index)|((surface1==13)&(index==0))),index==focus1))
            m.d.dvi += [rx2.eq(x1-left),width2.eq(width),ly2.eq(shape_y),active2.eq(active1 & (width!=0) & ~((surface1==14)&(row1==4)&(index==0))),
                        selected2.eq(selected),tab2.eq((row1==3)|(row1==20))]
            inside=(ly2<Mux(compact2,21,28))&(rx2>=off2)&(rx2<width2-off2)
            inset=(ly2>=2)&(ly2<Mux(compact2,19,26))&(rx2>=inner_off2)&(rx2<width2-inner_off2)
            hit3=Signal();color3=Signal(8)
            m.d.dvi += [hit3.eq(active2 & inside & ~inset),
                        color3.eq(Mux(selected2,Mux(tab2,0xB9,0xF9),0x49))]
            hits.append(hit3);colors.append(color3)
        # Six boxes follow the visible navigation order, including subpages.
        page=Mux((self.surface==0)|(self.surface==14),0,Mux(self.surface<=3,1,Mux(self.surface<=5,2,
             Mux((self.surface==8)|(self.surface==13),4,Mux(self.surface==9,5,3)))))
        pager_words=[0]*(8*256)
        for current in range(6):
            for index in range(6):
                center=360-5*6+index*12
                if index==current:
                    for x in range(center-9,center+10):pager_words[current*256+(x&255)]|=4
                else:
                    center+=-4 if index<current else 4
                    for x in range(center-5,center+6):
                        pager_words[current*256+(x&255)]|=1 | (2 if x<center-3 or x>=center+4 else 0)
        pager=Memory(shape=unsigned(3),depth=len(pager_words),init=pager_words,attrs={"ram_style":"block"})
        pager_port=pager.read_port(domain="dvi");m.submodules.pager=pager
        m.d.comb += [pager_port.addr.eq(Cat(self.x[:8],page)),pager_port.en.eq(self.active)]
        # Match the border layer's four-cycle latency, including the ROM read.
        chrome_hit2=Signal();chrome_color2=Signal(8)
        current=pager_port.data[2]&(y1>=60)&(y1<81)
        other=pager_port.data[0]&(y1>=62)&(y1<78)&(pager_port.data[1]|(y1<64)|(y1>=76))
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
