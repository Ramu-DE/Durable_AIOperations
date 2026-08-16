"""
Accurate Biomedical Graph Engineering GIF
Based on research from BioMedical_KnowledgeGraph_ontology_MCP repo:
  - 31 node types, 37 relationship types
  - Disease = universal hub (11 relationship types)
  - Drug = commercial hub (9 relationship types)
  - Closed clinical loop: Drug → ClinicalTrial → Patient → Gene → Biomarker → Drug
  - Two main chains from ontology:
      Molecular: Exposure → Gene → Protein → Pathway → BiologicalProcess
      Therapeutic: Drug → Protein → Gene → Disease → Anatomy
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np
import math
from PIL import Image
import io

np.random.seed(42)

# ── constants ──────────────────────────────────────────────────────────────────
CX, CY = 0.0, 0.0
R_SP   = 0.155   # sphere radius
R_DO   = 0.315   # doing-cycle radius
R_K    = 0.70    # knowing-ring radius

# ── 6 outer biomedical nodes ───────────────────────────────────────────────────
BIO = [
    ('Drug',           90),
    ('Disease',        30),
    ('Clinical\nTrial', -30),
    ('Patient',        -90),
    ('Gene',          -150),
    ('Biomarker',      150),
]

def P(r, deg): return CX + r*math.cos(math.radians(deg)), CY + r*math.sin(math.radians(deg))

bio_list = [(lbl, P(R_K, a)) for lbl, a in BIO]
n_bio    = len(bio_list)
bio_pos  = {lbl.replace('\n','_'): pos for lbl, pos in bio_list}

# doing cycle
DO       = [('assess',75),('check',10),('decide',-55),('act',-130),('observe',165)]
do_list  = [(lbl, P(R_DO, a)) for lbl, a in DO]

# ── accurate relationships from ontology/CSV research ─────────────────────────
#   (source_key, target_key, label, hex_color, arrow_rad, (lbl_dx, lbl_dy))
ALL_RELS = [
    ('Drug',          'Disease',       'treats\n(14 edges)',            '#C0392B',  0.15, ( 0.10,  0.08)),
    ('Biomarker',     'Drug',          'predicts_response\n(10 edges)', '#8E44AD', -0.15, (-0.08,  0.06)),
    ('Gene',          'Disease',       'associated_with\n(12 edges)',   '#2980B9',  0.18, (-0.12,  0.02)),
    ('Patient',       'Clinical_Trial','enrolled_in\n(15 edges)',       '#27AE60',  0.15, ( 0.08, -0.06)),
    ('Clinical_Trial','Drug',          'investigates\n(10 edges)',      '#E67E22',  0.20, ( 0.12,  0.02)),
    ('Clinical_Trial','Disease',       'studies\n(10 edges)',           '#16A085', -0.14, ( 0.02, -0.08)),
    ('Gene',          'Biomarker',     'expressed_as\n(13 edges)',      '#7F8C8D',  0.12, (-0.04,  0.08)),
]

# ── helpers ────────────────────────────────────────────────────────────────────
def sketchy(ax, x0,y0,x1,y1, lw=1.2, color='black', alpha=1.0, zorder=5):
    np.random.seed(int(abs(x0*1e4+y0*1e4)) % 999)
    n=8; xs=np.linspace(x0,x1,n); ys=np.linspace(y0,y1,n)
    xs[1:-1]+=np.random.randn(n-2)*0.0018; ys[1:-1]+=np.random.randn(n-2)*0.0018
    ax.plot(xs,ys,color=color,lw=lw,alpha=alpha,zorder=zorder,solid_capstyle='round')

def scircle(ax, cx,cy,r, lw=1.4, color='black', fc='white', zorder=5, alpha=1.0):
    t=np.linspace(0,2*np.pi,100)
    xs=cx+r*np.cos(t); ys=cy+r*np.sin(t)
    ax.fill(xs,ys,color=fc,zorder=zorder-1,alpha=alpha)
    ax.plot(xs,ys,color=color,lw=lw,zorder=zorder,alpha=alpha)

def rel_arrow(ax, p0, p1, color, label, rad=0.15, loff=(0,0.05)):
    dx,dy=p1[0]-p0[0],p1[1]-p0[1]; d=math.hypot(dx,dy)
    ox,oy=dx/d*0.095,dy/d*0.095
    ax.annotate('', xy=(p1[0]-ox,p1[1]-oy), xytext=(p0[0]+ox,p0[1]+oy),
                arrowprops=dict(arrowstyle='-|>',color=color,lw=2.2,
                                connectionstyle=f'arc3,rad={rad}'), zorder=15)
    mx=(p0[0]+p1[0])/2+loff[0]; my=(p0[1]+p1[1])/2+loff[1]
    ax.text(mx,my,label,ha='center',va='center',fontsize=7.0,color=color,
            zorder=16,style='italic',linespacing=1.2,
            bbox=dict(boxstyle='round,pad=0.18',facecolor='white',
                      edgecolor=color,alpha=0.95,lw=1.0))

def stick(ax, x,y,s=0.065,flip=False,zorder=12):
    d=-1 if flip else 1
    scircle(ax,x,y+s*1.9,s*0.38,lw=1.1,zorder=zorder)
    ax.plot([x,x],[y+s*1.5,y+s*0.55],'k-',lw=1.1,zorder=zorder)
    ax.plot([x,x+d*s*0.7],[y+s*1.2,y+s*0.9],'k-',lw=1.1,zorder=zorder)
    ax.plot([x,x-d*s*0.35],[y+s*1.2,y+s*0.75],'k-',lw=1.1,zorder=zorder)
    ax.plot([x,x-d*s*0.45],[y+s*0.55,y-s*0.4],'k-',lw=1.1,zorder=zorder)
    ax.plot([x,x+d*s*0.45],[y+s*0.55,y-s*0.3],'k-',lw=1.1,zorder=zorder)

def ladder(ax, bx,by,h=0.52,w=0.065,zorder=11):
    ax.plot([bx,bx],[by,by+h],'k-',lw=1.6,zorder=zorder)
    ax.plot([bx+w,bx+w],[by,by+h],'k-',lw=1.6,zorder=zorder)
    nr=int(h/0.09)
    for i in range(1,nr+1):
        ry=by+i*h/(nr+1); ax.plot([bx,bx+w],[ry,ry],'k-',lw=1.2,zorder=zorder)

# ── sphere mesh (pre-compute for consistency) ──────────────────────────────────
np.random.seed(7)
_sp_pts=[]
for i in range(28):
    ang=2*math.pi*i/28+np.random.randn()*0.05
    rr=R_SP*(0.35+0.65*np.random.random())
    _sp_pts.append((CX+rr*math.cos(ang),CY+rr*math.sin(ang)))
_sp_edges=[(i,j) for i in range(28) for j in range(i+1,28)
           if math.hypot(_sp_pts[i][0]-_sp_pts[j][0],_sp_pts[i][1]-_sp_pts[j][1])<R_SP*0.85]

# ── mid-junction points for triangulated ring ──────────────────────────────────
np.random.seed(42)
_mid_pts=[]
for i in range(n_bio):
    _,p0=bio_list[i]; _,p1=bio_list[(i+1)%n_bio]
    mx,my=(p0[0]+p1[0])/2,(p0[1]+p1[1])/2
    nm=math.hypot(mx,my); mx+=(mx/nm)*0.04; my+=(my/nm)*0.04
    _mid_pts.append((mx,my))

# ── main draw function ─────────────────────────────────────────────────────────
def draw_frame(ax, active_rels=None, headline=None, glow=None):
    ax.set_facecolor('white')
    ax.set_xlim(-1.45,1.45); ax.set_ylim(-1.50,1.54)
    ax.set_aspect('equal'); ax.axis('off')
    glow=glow or set()

    # title
    ax.text(0,1.44,'GRAPH ENGINEERING',ha='center',va='center',
            fontsize=32,fontweight='bold',color='black',fontfamily='DejaVu Sans')

    # ── sphere ────────────────────────────────────────────────────────────────
    scircle(ax,CX,CY,R_SP,lw=1.6,fc='#F0F0F0',zorder=6)
    for i,j in _sp_edges:
        ax.plot([_sp_pts[i][0],_sp_pts[j][0]],[_sp_pts[i][1],_sp_pts[j][1]],
                'k-',lw=0.25,alpha=0.5,zorder=5)
    for pt in _sp_pts:
        ax.plot(pt[0],pt[1],'ko',markersize=1.5,zorder=6,alpha=0.8)
    ax.annotate('graph of\nweights',xy=(CX,CY-R_SP-0.005),xytext=(CX+0.02,CY-0.43),
                ha='center',fontsize=8.5,color='black',style='italic',
                arrowprops=dict(arrowstyle='->',color='black',lw=0.9),zorder=10)

    # ── doing cycle ───────────────────────────────────────────────────────────
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
        ax.text(pos[0],pos[1],lbl,ha='center',va='center',fontsize=8.5,color='black',zorder=9)
    chk=do_list[1][1]
    ax.annotate('graph of\ndoing',xy=(chk[0]+0.04,chk[1]),xytext=(0.72,0.10),
                fontsize=8.5,color='black',style='italic',
                arrowprops=dict(arrowstyle='->',color='black',lw=0.9),zorder=10)

    # ── outer ring structure ──────────────────────────────────────────────────
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

    # node boxes
    for lbl,pos in bio_list:
        key=lbl.replace('\n','_')
        is_glow=key in glow
        has_nl='\n' in lbl
        bw=0.175 if not has_nl else 0.195
        bh=0.052 if not has_nl else 0.084
        fc='#FFF9C4' if is_glow else 'white'
        lw=2.4 if is_glow else 1.5
        ec='#E67E22' if is_glow else 'black'
        box=FancyBboxPatch((pos[0]-bw/2,pos[1]-bh/2),bw,bh,
                           boxstyle='square,pad=0.006',
                           facecolor=fc,edgecolor=ec,lw=lw,zorder=9)
        ax.add_patch(box)
        ax.text(pos[0],pos[1],lbl,ha='center',va='center',
                fontsize=9.5,fontweight='bold',color='black',zorder=10,linespacing=1.15)

    dis_p=bio_list[1][1]
    ax.annotate('graph of\nknowing',xy=(dis_p[0]+0.06,dis_p[1]+0.05),xytext=(1.12,0.72),
                fontsize=8.5,color='black',style='italic',
                arrowprops=dict(arrowstyle='->',color='black',lw=0.9),zorder=10)

    # ── stick figures ─────────────────────────────────────────────────────────
    gn=bio_list[4][1]
    stick(ax,gn[0]-0.16,gn[1]+0.05,s=0.062,flip=True)
    ax.plot([gn[0]-0.12,gn[0]-0.04],[gn[1]+0.09,gn[1]+0.04],'k-',lw=1.1,zorder=12)
    ax.text(gn[0]-0.24,gn[1]+0.04,'))',fontsize=8,color='black',zorder=13)
    dis_xy=bio_list[1][1]; lx=dis_xy[0]+0.14; ly=dis_xy[1]-0.42
    ladder(ax,lx,ly); stick(ax,lx+0.033,ly+0.38,s=0.055)
    ct=bio_list[2][1]; stick(ax,ct[0]+0.16,ct[1]-0.12,s=0.052)

    # ── relationship overlays ─────────────────────────────────────────────────
    if active_rels:
        for src,tgt,label,color,rad,loff in active_rels:
            p0=bio_pos[src]; p1=bio_pos[tgt]
            rel_arrow(ax,p0,p1,color,label,rad=rad,loff=loff)
            for pos in [p0,p1]:
                scircle(ax,pos[0],pos[1],0.09,lw=1.8,color=color,fc='none',zorder=8,alpha=0.35)

    # ── headline annotation ───────────────────────────────────────────────────
    if headline:
        ax.text(0,1.27,headline,ha='center',va='center',fontsize=9.5,
                color='#1A252F',style='italic',linespacing=1.3,
                bbox=dict(boxstyle='round,pad=0.4',facecolor='#EBF5FB',
                          edgecolor='#2980B9',lw=1.2,alpha=0.95),zorder=20)

    # ── bottom tagline ────────────────────────────────────────────────────────
    ax.text(0,-1.30,'Graph of weights.    Graph of doing.    Graph of knowing.',
            ha='center',va='center',fontsize=10.5,color='black',
            fontfamily='DejaVu Sans',style='italic')
    sketchy(ax,-0.80,-1.38,0.80,-1.38,lw=1.8,zorder=8)


def to_pil(fig):
    buf=io.BytesIO()
    fig.savefig(buf,format='png',dpi=115,bbox_inches='tight',facecolor='white')
    buf.seek(0); img=Image.open(buf).copy(); buf.close(); return img

def frame(active_rels=None, headline=None, glow=None):
    fig,ax=plt.subplots(figsize=(13,13))
    fig.patch.set_facecolor('white')
    draw_frame(ax,active_rels,headline,glow)
    img=to_pil(fig); plt.close(fig); return img

# ── animation sequence — 9 distinct keyframes with per-frame durations ─────────
keyframes = []     # PIL images
durations  = []    # ms per frame

def kf(active_rels=None, headline=None, glow=None, hold_ms=1800):
    keyframes.append(frame(active_rels, headline, glow))
    durations.append(hold_ms)

# Frame 0 — base (3 s)
kf(headline='Biomedical Knowledge Graph  |  31 nodes · 37 relationship types', hold_ms=3000)

# Frames 1-7 — cumulative relationships (1.8 s each)
cumulative = []
STEPS = [
    (ALL_RELS[0], 'Drug --[treats]--> Disease  (14 edges)',            {'Drug','Disease'}),
    (ALL_RELS[1], 'Biomarker --[predicts_response]--> Drug  (10)',     {'Drug','Disease','Biomarker'}),
    (ALL_RELS[2], 'Gene --[associated_with]--> Disease  (12)',         {'Drug','Disease','Biomarker','Gene'}),
    (ALL_RELS[3], 'Patient --[enrolled_in]--> Clinical Trial  (15)',   {'Drug','Disease','Biomarker','Gene','Patient','Clinical_Trial'}),
    (ALL_RELS[4], 'Clinical Trial --[investigates]--> Drug  (10)',     {'Drug','Disease','Biomarker','Gene','Patient','Clinical_Trial'}),
    (ALL_RELS[5], 'Clinical Trial --[studies]--> Disease  (10)',       {'Drug','Disease','Biomarker','Gene','Patient','Clinical_Trial'}),
    (ALL_RELS[6], 'Gene --[expressed_as]--> Biomarker  (closes ring)', set(bio_pos.keys())),
]
for rel, headline, glow_set in STEPS:
    cumulative.append(rel)
    kf(list(cumulative), headline, glow_set, hold_ms=1800)

# Frame 8 — full graph + closed-loop callout (5 s)
kf(
    list(cumulative),
    'Drug → Disease → Clinical Trial → Patient → Gene → Biomarker → Drug\n'
    '"Two graphs. One walk."   (Disease = universal hub · Drug = commercial hub)',
    set(bio_pos.keys()),
    hold_ms=5000
)

print(f"Total keyframes: {len(keyframes)}")

# ── save ───────────────────────────────────────────────────────────────────────
import struct

out = r"C:\Users\Administrator\Durable_AIOperations\graph\graph_biomedical_accurate.gif"

# Write GIF manually: save each keyframe as a separate GIF, then stitch them
# into one file using raw GIF binary manipulation to honour per-frame delay.

import io as _io

def frame_to_gif_bytes(img_pil, delay_cs):
    """Return the GCE + Image block bytes for one frame (no header/trailer)."""
    # Quantize
    q = img_pil.convert('RGB').quantize(colors=256, dither=0)
    # Save as single-frame GIF to buffer
    buf = _io.BytesIO()
    q.save(buf, format='GIF', loop=0)
    raw = buf.getvalue()
    # Extract colour table size from logical screen descriptor byte 10
    lsd_flags = raw[10]
    ct_size   = 2 ** ((lsd_flags & 0x07) + 1)  # number of colours
    ct_bytes  = ct_size * 3
    header_end = 13 + ct_bytes                   # after header + global CT
    # Build GCE (Graphic Control Extension) with our delay
    gce = (b'\x21\xF9\x04'          # extension introducer + label + block size
           + bytes([0x00])           # flags: no disposal, no user input
           + struct.pack('<H', delay_cs)  # delay in centiseconds (little-endian)
           + b'\x00\x00')           # transparent colour index + block terminator
    # Image block starts at header_end, ends before trailer (0x3B)
    image_block = raw[header_end:-1]  # strip 0x3B trailer
    return gce + image_block

# Build full GIF: header of frame0 + all (GCE+image) blocks + trailer
q0 = keyframes[0].convert('RGB').quantize(colors=256, dither=0)
buf0 = _io.BytesIO(); q0.save(buf0, format='GIF'); raw0 = buf0.getvalue()
lsd_flags = raw0[10]; ct_size = 2**((lsd_flags & 0x07)+1); ct_bytes = ct_size*3
header_end = 13 + ct_bytes

gif_data = bytearray()
# Header (6 bytes) + logical screen descriptor (7 bytes) + global CT
gif_data += raw0[:header_end]
# Netscape looping extension (loop=0 = infinite)
gif_data += (b'\x21\xFF\x0B'               # app extension
             b'NETSCAPE2.0'
             b'\x03\x01\x00\x00\x00')      # 3 sub-blocks, loop count=0

for img, ms in zip(keyframes, durations):
    delay_cs = max(1, ms // 10)   # convert ms → centiseconds
    gif_data += frame_to_gif_bytes(img, delay_cs)

gif_data += b'\x3B'  # GIF trailer

with open(out, 'wb') as fh:
    fh.write(gif_data)

# Verify
from PIL import Image as _Img
check = _Img.open(out)
print(f"Saved: {out}")
print(f"  Frames: {check.n_frames} | Size: {check.size} | Total: ~{sum(durations)/1000:.1f}s")
