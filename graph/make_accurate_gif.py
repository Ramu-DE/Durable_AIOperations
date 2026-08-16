"""
Biomedical Graph Engineering GIF — v3
Arrows arc OUTSIDE the outer ring. Labels float at arc peak beyond R_K.
Arc peak formula for matplotlib arc3,rad=r:
  peak = midpoint(p0,p1) + 0.5*r * rotate90(p1-p0)
Rad signs chosen so peak lands outside R_K = 0.70.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np
import math, struct
from PIL import Image
import io as _io

np.random.seed(42)

CX, CY = 0.0, 0.0
R_SP, R_DO, R_K = 0.155, 0.315, 0.70

BIO = [
    ('Drug',            90),
    ('Disease',         30),
    ('Clinical\nTrial', -30),
    ('Patient',         -90),
    ('Gene',           -150),
    ('Biomarker',       150),
]

def P(r, deg):
    return CX+r*math.cos(math.radians(deg)), CY+r*math.sin(math.radians(deg))

bio_list = [(lbl, P(R_K, a)) for lbl, a in BIO]
bio_pos  = {lbl.replace('\n','_'): pos for lbl, pos in bio_list}
n_bio    = len(bio_list)

DO = [('assess',75),('check',10),('decide',-55),('act',-130),('observe',165)]
do_list = [(lbl, P(R_DO, a)) for lbl, a in DO]

# ── arc peak formula ───────────────────────────────────────────────────────────
# For matplotlib arc3,rad=r connecting p0→p1:
#   peak_x = (p0x+p1x)/2  + 0.5*r*(-(p1y-p0y))
#   peak_y = (p0y+p1y)/2  + 0.5*r*(  p1x-p0x )
# We choose r so peak_dist > R_K (label floats outside ring)

def arc_peak(p0, p1, rad):
    dx, dy = p1[0]-p0[0], p1[1]-p0[1]
    return ((p0[0]+p1[0])/2 + 0.5*rad*(-dy),
            (p0[1]+p1[1])/2 + 0.5*rad*( dx))

# Verified rad values — all produce arc_peak_dist > R_K:
#   Drug→Disease      r=+0.55 → dist=0.80 ✓
#   Biomarker→Drug    r=+0.55 → dist=0.80 ✓
#   Gene→Disease      r=+1.25 → dist=0.88 ✓  (long diagonal needs large r)
#   Patient→ClinTrial r=-0.55 → dist=0.80 ✓
#   ClinTrial→Drug    r=-0.90 → dist=0.90 ✓
#   ClinTrial→Disease r=-0.55 → dist=0.80 ✓
#   Gene→Biomarker    r=+0.55 → dist=0.80 ✓
ALL_RELS = [
    ('Drug',          'Disease',        'treats',            '#C0392B', +0.55),
    ('Biomarker',     'Drug',           'predicts\nresponse','#8E44AD', +0.55),
    ('Gene',          'Disease',        'associated\nwith',  '#2980B9', +1.25),
    ('Patient',       'Clinical_Trial', 'enrolled\nin',      '#27AE60', -0.55),
    ('Clinical_Trial','Drug',           'investigates',      '#E67E22', -0.90),
    ('Clinical_Trial','Disease',        'studies',           '#16A085', -0.55),
    ('Gene',          'Biomarker',      'expressed\nas',     '#7F8C8D', +0.55),
]

# ── helpers ────────────────────────────────────────────────────────────────────
def sketchy(ax, x0,y0,x1,y1, lw=1.2, color='black', alpha=1.0, zorder=5):
    np.random.seed(int(abs(x0*1e4+y0*1e4))%999)
    n=8; xs=np.linspace(x0,x1,n); ys=np.linspace(y0,y1,n)
    xs[1:-1]+=np.random.randn(n-2)*0.0018; ys[1:-1]+=np.random.randn(n-2)*0.0018
    ax.plot(xs,ys,color=color,lw=lw,alpha=alpha,zorder=zorder,solid_capstyle='round')

def scircle(ax, cx,cy,r, lw=1.4, color='black', fc='white', zorder=5, alpha=1.0):
    t=np.linspace(0,2*np.pi,100)
    ax.fill(cx+r*np.cos(t),cy+r*np.sin(t),color=fc,zorder=zorder-1,alpha=alpha)
    ax.plot(cx+r*np.cos(t),cy+r*np.sin(t),color=color,lw=lw,zorder=zorder,alpha=alpha)

def rel_arrow(ax, p0, p1, color, label, rad):
    dx,dy = p1[0]-p0[0], p1[1]-p0[1]
    d = math.hypot(dx,dy); ox,oy = dx/d*0.10, dy/d*0.10
    ax.annotate('', xy=(p1[0]-ox,p1[1]-oy), xytext=(p0[0]+ox,p0[1]+oy),
                arrowprops=dict(arrowstyle='-|>', color=color, lw=2.6,
                                mutation_scale=13,
                                connectionstyle=f'arc3,rad={rad}'), zorder=16)
    # label at arc peak pushed slightly further from origin
    px, py = arc_peak(p0, p1, rad)
    dist = math.hypot(px,py)
    push = 0.10
    lx = px + (px/dist)*push if dist>0.01 else px
    ly = py + (py/dist)*push if dist>0.01 else py
    ax.text(lx, ly, label, ha='center', va='center',
            fontsize=8.5, color=color, zorder=17,
            fontweight='semibold', linespacing=1.2,
            bbox=dict(boxstyle='round,pad=0.22', facecolor='white',
                      edgecolor=color, alpha=0.97, lw=1.1))

def stick(ax,x,y,s=0.065,flip=False,zorder=12):
    d=-1 if flip else 1
    scircle(ax,x,y+s*1.9,s*0.38,lw=1.1,zorder=zorder)
    ax.plot([x,x],[y+s*1.5,y+s*0.55],'k-',lw=1.1,zorder=zorder)
    ax.plot([x,x+d*s*0.7],[y+s*1.2,y+s*0.9],'k-',lw=1.1,zorder=zorder)
    ax.plot([x,x-d*s*0.35],[y+s*1.2,y+s*0.75],'k-',lw=1.1,zorder=zorder)
    ax.plot([x,x-d*s*0.45],[y+s*0.55,y-s*0.4],'k-',lw=1.1,zorder=zorder)
    ax.plot([x,x+d*s*0.45],[y+s*0.55,y-s*0.3],'k-',lw=1.1,zorder=zorder)

def ladder(ax,bx,by,h=0.52,w=0.065,zorder=11):
    ax.plot([bx,bx],[by,by+h],'k-',lw=1.6,zorder=zorder)
    ax.plot([bx+w,bx+w],[by,by+h],'k-',lw=1.6,zorder=zorder)
    nr=int(h/0.09)
    for i in range(1,nr+1):
        ry=by+i*h/(nr+1); ax.plot([bx,bx+w],[ry,ry],'k-',lw=1.2,zorder=zorder)

# sphere mesh
np.random.seed(7)
_sp_pts=[]
for i in range(28):
    ang=2*math.pi*i/28+np.random.randn()*0.05
    rr=R_SP*(0.35+0.65*np.random.random())
    _sp_pts.append((CX+rr*math.cos(ang),CY+rr*math.sin(ang)))
_sp_edges=[(i,j) for i in range(28) for j in range(i+1,28)
           if math.hypot(_sp_pts[i][0]-_sp_pts[j][0],
                         _sp_pts[i][1]-_sp_pts[j][1])<R_SP*0.85]

# mid-junction points
np.random.seed(42)
_mid_pts=[]
for i in range(n_bio):
    _,p0=bio_list[i]; _,p1=bio_list[(i+1)%n_bio]
    mx,my=(p0[0]+p1[0])/2,(p0[1]+p1[1])/2
    nm=math.hypot(mx,my); mx+=(mx/nm)*0.04; my+=(my/nm)*0.04
    _mid_pts.append((mx,my))

# ── draw ───────────────────────────────────────────────────────────────────────
def draw_frame(ax, active_rels=None, headline=None, glow=None):
    ax.set_facecolor('white')
    ax.set_xlim(-1.55,1.55); ax.set_ylim(-1.58,1.62)
    ax.set_aspect('equal'); ax.axis('off')
    glow=glow or set()

    ax.text(0,1.53,'GRAPH ENGINEERING',ha='center',va='center',
            fontsize=32,fontweight='bold',color='black',fontfamily='DejaVu Sans')

    # sphere
    scircle(ax,CX,CY,R_SP,lw=1.6,fc='#F0F0F0',zorder=6)
    for i,j in _sp_edges:
        ax.plot([_sp_pts[i][0],_sp_pts[j][0]],
                [_sp_pts[i][1],_sp_pts[j][1]],'k-',lw=0.25,alpha=0.5,zorder=5)
    for pt in _sp_pts:
        ax.plot(pt[0],pt[1],'ko',markersize=1.5,zorder=6,alpha=0.8)
    ax.annotate('graph of\nweights',xy=(CX,CY-R_SP-0.005),
                xytext=(CX+0.02,CY-0.44),ha='center',fontsize=8.5,
                color='black',style='italic',
                arrowprops=dict(arrowstyle='->',color='black',lw=0.9),zorder=10)

    # doing cycle
    for i in range(len(do_list)):
        _,p0=do_list[i]; _,p1=do_list[(i+1)%len(do_list)]
        dx,dy=p1[0]-p0[0],p1[1]-p0[1]; d=math.hypot(dx,dy)
        ox,oy=dx/d*0.055,dy/d*0.055
        ax.annotate('',xy=(p1[0]-ox,p1[1]-oy),xytext=(p0[0]+ox,p0[1]+oy),
                    arrowprops=dict(arrowstyle='-|>',color='black',lw=1.1,
                                   connectionstyle='arc3,rad=0.1'),zorder=7)
    for lbl,pos in do_list:
        e=mpatches.Ellipse(pos,0.155,0.075,color='white',ec='black',lw=1.3,zorder=8)
        ax.add_patch(e)
        ax.text(pos[0],pos[1],lbl,ha='center',va='center',fontsize=8.5,
                color='black',zorder=9)
    chk=do_list[1][1]
    ax.annotate('graph of\ndoing',xy=(chk[0]+0.04,chk[1]),xytext=(0.74,0.10),
                fontsize=8.5,color='black',style='italic',
                arrowprops=dict(arrowstyle='->',color='black',lw=0.9),zorder=10)

    # outer ring
    for i in range(n_bio):
        _,p0=bio_list[i]; _,p1=bio_list[(i+1)%n_bio]
        sketchy(ax,p0[0],p0[1],p1[0],p1[1],lw=1.4,zorder=5)
    for i,(mx,my) in enumerate(_mid_pts):
        _,p0=bio_list[i]; _,p1=bio_list[(i+1)%n_bio]
        sketchy(ax,p0[0],p0[1],mx,my,lw=0.9,zorder=4)
        sketchy(ax,p1[0],p1[1],mx,my,lw=0.9,zorder=4)
        ax.plot(mx,my,'ko',markersize=5.5,zorder=7)
        nm=math.hypot(mx,my); tx=mx-(mx/nm)*0.22; ty=my-(my/nm)*0.22
        sketchy(ax,mx,my,tx,ty,lw=0.7,alpha=0.5,zorder=4)
        ax.plot(tx,ty,'ko',markersize=4.5,zorder=6)
    for _,pos in bio_list:
        ax.plot(pos[0],pos[1],'ko',markersize=7,zorder=8)
        nm=math.hypot(pos[0],pos[1])
        tx=pos[0]-(pos[0]/nm)*(R_K-R_DO-0.05)
        ty=pos[1]-(pos[1]/nm)*(R_K-R_DO-0.05)
        sketchy(ax,pos[0],pos[1],tx,ty,lw=0.5,alpha=0.25,zorder=3)

    # node boxes — colored border when active
    for lbl,pos in bio_list:
        key=lbl.replace('\n','_')
        is_glow=key in glow
        has_nl='\n' in lbl
        bw=0.175 if not has_nl else 0.195; bh=0.052 if not has_nl else 0.084
        node_color='black'; fc='white'; lw=1.5
        if is_glow and active_rels:
            for r in active_rels:
                if key in (r[0],r[1]):
                    node_color=r[3]; fc='#FFFDE7'; lw=2.5; break
        box=FancyBboxPatch((pos[0]-bw/2,pos[1]-bh/2),bw,bh,
                           boxstyle='square,pad=0.006',
                           facecolor=fc,edgecolor=node_color,lw=lw,zorder=9)
        ax.add_patch(box)
        ax.text(pos[0],pos[1],lbl,ha='center',va='center',
                fontsize=9.5,fontweight='bold',color='black',zorder=10,
                linespacing=1.15)

    dis_p=bio_list[1][1]
    ax.annotate('graph of\nknowing',xy=(dis_p[0]+0.06,dis_p[1]+0.05),
                xytext=(1.20,0.76),fontsize=8.5,color='black',style='italic',
                arrowprops=dict(arrowstyle='->',color='black',lw=0.9),zorder=10)

    # stick figures
    gn=bio_list[4][1]
    stick(ax,gn[0]-0.16,gn[1]+0.05,s=0.062,flip=True)
    ax.plot([gn[0]-0.12,gn[0]-0.04],[gn[1]+0.09,gn[1]+0.04],'k-',lw=1.1,zorder=12)
    ax.text(gn[0]-0.25,gn[1]+0.04,'))',fontsize=8,color='black',zorder=13)
    dis_xy=bio_list[1][1]; lx=dis_xy[0]+0.14; ly=dis_xy[1]-0.42
    ladder(ax,lx,ly); stick(ax,lx+0.033,ly+0.38,s=0.055)
    ct=bio_list[2][1]; stick(ax,ct[0]+0.18,ct[1]-0.13,s=0.052)

    # relationship arrows drawn last (on top of everything)
    if active_rels:
        for src,tgt,label,color,rad in active_rels:
            rel_arrow(ax,bio_pos[src],bio_pos[tgt],color,label,rad)

    # headline
    if headline:
        ax.text(0,1.39,headline,ha='center',va='center',fontsize=10,
                color='#1A252F',style='italic',linespacing=1.3,
                bbox=dict(boxstyle='round,pad=0.4',facecolor='#EBF5FB',
                          edgecolor='#2980B9',lw=1.2,alpha=0.95),zorder=20)

    # tagline
    ax.text(0,-1.42,'Graph of weights.    Graph of doing.    Graph of knowing.',
            ha='center',va='center',fontsize=10.5,color='black',
            fontfamily='DejaVu Sans',style='italic')
    sketchy(ax,-0.80,-1.49,0.80,-1.49,lw=1.8,zorder=8)


def to_pil(fig):
    buf=_io.BytesIO()
    fig.savefig(buf,format='png',dpi=115,bbox_inches='tight',facecolor='white')
    buf.seek(0); img=Image.open(buf).copy(); buf.close(); return img

def frame(active_rels=None,headline=None,glow=None):
    fig,ax=plt.subplots(figsize=(13,13))
    fig.patch.set_facecolor('white')
    draw_frame(ax,active_rels,headline,glow)
    img=to_pil(fig); plt.close(fig); return img

# ── keyframes ─────────────────────────────────────────────────────────────────
keyframes,durations=[],[]

def kf(active_rels=None,headline=None,glow=None,hold_ms=2000):
    keyframes.append(frame(active_rels,headline,glow)); durations.append(hold_ms)

kf(headline='Biomedical Knowledge Graph  ·  31 node types  ·  37 relationship types',
   hold_ms=3000)

cumulative=[]
STEPS=[
    (ALL_RELS[0],'Drug  —[treats]→  Disease',                        {'Drug','Disease'}),
    (ALL_RELS[1],'Biomarker  —[predicts response]→  Drug',           {'Drug','Disease','Biomarker'}),
    (ALL_RELS[2],'Gene  —[associated with]→  Disease',               {'Drug','Disease','Biomarker','Gene'}),
    (ALL_RELS[3],'Patient  —[enrolled in]→  Clinical Trial',         {'Drug','Disease','Biomarker','Gene','Patient','Clinical_Trial'}),
    (ALL_RELS[4],'Clinical Trial  —[investigates]→  Drug',           {'Drug','Disease','Biomarker','Gene','Patient','Clinical_Trial'}),
    (ALL_RELS[5],'Clinical Trial  —[studies]→  Disease',             {'Drug','Disease','Biomarker','Gene','Patient','Clinical_Trial'}),
    (ALL_RELS[6],'Gene  —[expressed as]→  Biomarker  ·  ring closed',set(bio_pos.keys())),
]
for rel,headline,glow_set in STEPS:
    cumulative.append(rel)
    kf(list(cumulative),headline,glow_set,hold_ms=2000)

kf(list(cumulative),
   'Drug → Disease → Clinical Trial → Patient → Gene → Biomarker → Drug\n'
   '"Two graphs. One walk."   ·   Disease = universal hub   ·   Drug = commercial hub',
   set(bio_pos.keys()),hold_ms=5000)

print(f"Keyframes: {len(keyframes)}")

# ── verify arc peaks land outside ring ────────────────────────────────────────
for src,tgt,lbl,col,rad in ALL_RELS:
    p0,p1=bio_pos[src],bio_pos[tgt]
    px,py=arc_peak(p0,p1,rad)
    d=math.hypot(px,py)
    status="OK" if d>R_K else "!! INSIDE"
    print(f"  {src:15s}->{tgt:15s} rad={rad:+.2f}  peak_dist={d:.3f} {status}")

# ── write GIF ─────────────────────────────────────────────────────────────────
def frame_bytes(img_pil, delay_cs):
    q=img_pil.convert('RGB').quantize(colors=256,dither=0)
    buf=_io.BytesIO(); q.save(buf,format='GIF'); raw=buf.getvalue()
    ct_bytes=(2**((raw[10]&0x07)+1))*3; hend=13+ct_bytes
    return (b'\x21\xF9\x04'+bytes([0x00])
            +struct.pack('<H',delay_cs)+b'\x00\x00') + raw[hend:-1]

q0=keyframes[0].convert('RGB').quantize(colors=256,dither=0)
buf0=_io.BytesIO(); q0.save(buf0,format='GIF'); raw0=buf0.getvalue()
ct_bytes=(2**((raw0[10]&0x07)+1))*3; hend=13+ct_bytes

gif=bytearray(raw0[:hend])
gif+=b'\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00'
for img,ms in zip(keyframes,durations):
    gif+=frame_bytes(img,max(1,ms//10))
gif+=b'\x3B'

out=r"C:\Users\Administrator\Durable_AIOperations\graph\graph_biomedical_accurate.gif"
with open(out,'wb') as fh: fh.write(gif)
from PIL import Image as _I; chk=_I.open(out)
print(f"\nSaved: {out}  |  {chk.n_frames} frames  |  ~{sum(durations)/1000:.0f}s loop")
