import sys, os
import numpy as np, cv2

work, outdir = sys.argv[1], sys.argv[2]
img = cv2.imdecode(np.fromfile(os.path.join(work,"logo_clean.png"), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
b,g,r,a = cv2.split(img)
rgb = cv2.merge([b,g,r]).astype(np.int16)
alpha = a.astype(np.float32)/255.0

MINT = (0x2f,0xbf,0x9b)
DEEP = (0x0f,0x7f,0x66)
INKS = {"mint": MINT, "deep": DEEP}

best = np.zeros(img.shape[:2], np.int32)
bestd = np.full(img.shape[:2], 1e9, np.float32)
for k,(R,G,B) in enumerate(INKS.values(), start=1):
    d = ((rgb[:,:,0]-B)**2 + (rgb[:,:,1]-G)**2 + (rgb[:,:,2]-R)**2).astype(np.float32)
    m = (d < bestd) & (alpha > 0.5)
    bestd[m] = d[m]; best[m] = k

# ---------- geometry helpers ----------
def bez(pts,t):
    t=np.asarray(t,float)[:,None]; P=np.asarray(pts,float)
    return ((1-t)**3)*P[0]+3*((1-t)**2)*t*P[1]+3*(1-t)*(t**2)*P[2]+(t**3)*P[3]
def chord(pts):
    d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(pts,axis=0),axis=1))]
    return d/d[-1] if d[-1]>0 else np.linspace(0,1,len(pts))
def gen(pts,u,t1,t2):
    P=np.asarray(pts,float); p0,p3=P[0],P[-1]
    if len(P)==2:
        dd=np.linalg.norm(p3-p0)/3.0
        return np.array([p0,p0+t1*dd,p3+t2*dd,p3])
    c1=3*(1-u)**2*u; c2=3*(1-u)*u**2
    w0=((1-u)**3+3*(1-u)**2*u)[:,None]; w3=(3*(1-u)*u**2+u**3)[:,None]
    base=p0[None,:]*w0+p3[None,:]*w3
    A0=c1[:,None]*t1; A1=c2[:,None]*t2
    C=np.array([[np.sum(A0*A0),np.sum(A0*A1)],[np.sum(A1*A0),np.sum(A1*A1)]])
    R=P-base; X=np.array([np.sum(A0*R),np.sum(A1*R)])
    det=C[0,0]*C[1,1]-C[0,1]*C[1,0]
    seg=np.linalg.norm(p3-p0)
    if abs(det)<1e-12: a1=a2=seg/3.0
    else:
        a1=(X[0]*C[1,1]-X[1]*C[1,0])/det
        a2=(C[0,0]*X[1]-C[0,1]*X[0])/det
        if a1<1e-6 or a2<1e-6 or a1>seg*3 or a2>seg*3: a1=a2=seg/3.0
    return np.array([p0,p0+t1*a1,p3+t2*a2,p3])
def err(pts,u,c):
    d=np.linalg.norm(bez(c,u)-np.asarray(pts,float),axis=1)
    i=int(np.argmax(d)); return d[i],i
def reparam(pts,u,c):
    for _ in range(4):
        d=bez(c,u)-np.asarray(pts,float)
        du=(bez(c,np.clip(u+1e-4,0,1))-bez(c,np.clip(u-1e-4,0,1)))/(2e-4)
        num=np.sum(d*du,1); den=np.sum(du*du,1); den[den<1e-12]=1
        u=np.clip(u-num/den,0,1)
    return u
def fit(pts,t1,t2,tol,depth=0):
    u=chord(pts); c=gen(pts,u,t1,t2); e,i=err(pts,u,c)
    if e<tol or depth>14: return [c]
    u=reparam(pts,u,c); c=gen(pts,u,t1,t2); e,i=err(pts,u,c)
    if e<tol or depth>14: return [c]
    i=max(1,min(i,len(pts)-2)); p=pts[i]
    t=pts[min(i+1,len(pts)-1)]-pts[max(i-1,0)]
    n=np.linalg.norm(t); t=t/n if n>1e-9 else np.array([1.0,0.0])
    return fit(pts[:i+1],t1,-t,tol,depth+1)+fit(pts[i:],t,t2,tol,depth+1)
def unit(v):
    n=np.linalg.norm(v); return v/n if n>1e-9 else np.array([1.0,0.0])
def smooth_closed(pts,it=8):
    for _ in range(it):
        pts=(np.roll(pts,1,axis=0)+2*pts+np.roll(pts,-1,axis=0))/4.0
    return pts
def resample(pts,step=3.0):
    d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(pts,axis=0),axis=1))]; L=d[-1]
    if L<=0: return pts
    n=max(8,int(L/step)); tgt=np.linspace(0,L,n,endpoint=False)
    return np.c_[np.interp(tgt,d,pts[:,0]),np.interp(tgt,d,pts[:,1])]
def path_d(curves):
    parts=["M%.2f,%.2f"%(curves[0][0][0],curves[0][0][1])]
    for c in curves:
        parts.append("C%.2f,%.2f %.2f,%.2f %.2f,%.2f"%(c[1][0],c[1][1],c[2][0],c[2][1],c[3][0],c[3][1]))
    parts.append("Z")
    return "".join(parts)

def contours_of(mask, min_area=40, step=3.0, tol=0.75):
    cnts,_=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_NONE)
    subs=[]
    for c in cnts:
        if cv2.contourArea(c)<min_area: continue
        pts=c[:,0,:].astype(float)
        if len(pts)>1 and np.allclose(pts[0],pts[-1]): pts=pts[:-1]
        pts=smooth_closed(resample(pts,step),8)
        loop=np.vstack([pts,pts[0]])
        subs.append(path_d(fit(loop,unit(loop[1]-loop[0]),unit(loop[-2]-loop[-1]),tol)))
    return subs

# ---------- build a tight, square master ----------
H,W = img.shape[:2]
ys,xs = np.where(alpha>0.5)
x0,x1,y0,y1 = xs.min(),xs.max()+1,ys.min(),ys.max()+1
cw,ch = x1-x0,y1-y0
side = int(round(max(cw,ch)*1.10))
ox,oy = (side-cw)//2,(side-ch)//2

def to_canvas(mask, shrink=0):
    """place a mask on the square canvas, optionally shrunk back by `shrink` px"""
    m = mask
    if shrink: m = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*shrink+1,2*shrink+1)))
    out = np.zeros((side,side),np.uint8)
    out[oy:oy+ch, ox:ox+cw] = m[y0:y1, x0:x1]
    return out

masks={}
for k,(name,ink) in enumerate(INKS.items(), start=1):
    masks[name]=np.where(best==k,255,0).astype(np.uint8)

# 1px overlap so the two flat fills meet without an anti-aliased seam
k1=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
two = {}
for name,m in masks.items():
    two[name]=cv2.morphologyEx(to_canvas(m),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    two[name]=cv2.dilate(two[name],k1)

def svg(paths, vb):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">\n%s\n</svg>\n'
            % (vb,vb,vb,vb,"\n".join(paths)))

# Colour version, same construction as the artwork: the dark green is a solid
# backing shape covering the whole silhouette, the mint ribbon is painted on top
# of it. Building it this way means the two fills can never leave a seam or a
# step at their join - there is only one visible boundary, mint against dark.
whole = to_canvas(((alpha>0.5).astype(np.uint8))*255)
whole = cv2.morphologyEx(whole, cv2.MORPH_CLOSE, np.ones((3,3),np.uint8))
back_paths = contours_of(whole, min_area=60)
# Where mint meets the *outer* edge it must sit exactly on the silhouette: the
# anti-aliased outer boundary plus contour smoothing pulled it ~1 px inside, and
# the dark backing showed through as a step at the cusp. So mint is extended into
# the silhouette's edge band only - its internal boundary against the dark stays
# where it was traced.
mint_mask = cv2.morphologyEx(to_canvas(masks["mint"]), cv2.MORPH_CLOSE, np.ones((3,3),np.uint8))
outside = cv2.bitwise_not(whole)
edge_band = cv2.bitwise_and(cv2.dilate(outside, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9))), whole)
mint_mask = cv2.bitwise_or(mint_mask, cv2.bitwise_and(cv2.dilate(mint_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9))), edge_band))
mint_paths = contours_of(mint_mask)

silhouette = "".join(back_paths)
colored = [
    '<defs><clipPath id="pinly-silhouette"><path fill-rule="evenodd" d="%s"/></clipPath></defs>' % silhouette,
    '<path fill="#%02x%02x%02x" fill-rule="evenodd" d="%s"/>' % (DEEP[0],DEEP[1],DEEP[2],silhouette),
    '<path fill="#%02x%02x%02x" clip-path="url(#pinly-silhouette)" d="%s"/>' % (MINT[0],MINT[1],MINT[2],"".join(mint_paths)),
]
open(os.path.join(outdir,"logo.svg"),"w",encoding="utf-8").write(svg(colored,side))

open(os.path.join(outdir,"logo-mono.svg"),"w",encoding="utf-8").write(
    svg(['<path fill="currentColor" fill-rule="evenodd" d="%s"/>'%"".join(back_paths)], side))

print("viewBox:", side, "| silhouette subpaths:",len(back_paths),"mint:",len(mint_paths))
