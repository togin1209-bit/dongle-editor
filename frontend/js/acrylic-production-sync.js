/* acrylic-production-sync.js — v1.9.8 (CLAUDE track)
 * 작업지시서 #5,#6,#7,#16,#17: 아크릴 Production Group(칼선·탭·슬롯)이 이미지와
 * "하나의 시스템처럼" 움직이게 한다.
 *
 * 설계 원칙 (백엔드 production_part.py 계약과 동일):
 *  - Local Geometry = 업로드 원본 px 좌표(칼선 point). 이동/확대/회전 때 절대 재계산 안 함(#15).
 *  - World = image.calcTransformMatrix() 로 매 프레임 투영 (contour 재추출 없음, 성능 #17/#28).
 *  - Slot 은 Base 에 속함 → Tab 중앙 X 만 추종(회전 X, Y 고정), Base 밖이면 clamp(#7).
 *  - 이미지 삭제 → 칼선/탭/슬롯 동시 삭제(Orphan 금지 #18).
 *
 * 순수 기하 함수(clamp/followSlotCenterX/projectPoints)는 window.AcrylicSyncMath 로도
 * 노출해 브라우저 없이 단위 테스트할 수 있다.
 */
(function (global) {
  'use strict';

  // ---- 순수 기하 (테스트 가능) ----
  function clamp(v, lo, hi) { return hi < lo ? (lo + hi) / 2 : Math.max(lo, Math.min(hi, v)); }

  function followSlotCenterX(tabCenterX, baseLeft, baseWidth, slotWidth, edgeMargin) {
    edgeMargin = edgeMargin || 0;
    const half = slotWidth / 2;
    return clamp(tabCenterX, baseLeft + half + edgeMargin, baseLeft + baseWidth - half - edgeMargin);
  }

  // local(px) → world(canvas px) : fabric matrix [a,b,c,d,e,f]
  function projectPoint(px, py, sourceW, sourceH, imgW, imgH, m) {
    const lx = (px / sourceW) * imgW - imgW / 2;
    const ly = (py / sourceH) * imgH - imgH / 2;
    return { x: m[0] * lx + m[2] * ly + m[4], y: m[1] * lx + m[3] * ly + m[5] };
  }

  function projectPoints(pointsPx, sourceW, sourceH, imgW, imgH, m) {
    return pointsPx.map(p => projectPoint(p[0], p[1], sourceW, sourceH, imgW, imgH, m));
  }

  function bbox(points) {
    const xs = points.map(p => p.x), ys = points.map(p => p.y);
    return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
  }


  function forwardPath(points,start,end){const out=[];let i=start,n=points.length,guard=0;while(guard++<=n){out.push(points[i]);if(i===end)break;i=(i+1)%n;}return out;}
  function longerPath(points,left,right){const a=forwardPath(points,left,right),b=forwardPath(points,right,left).reverse();return a.length>=b.length?a:b;}
  const Math2D = { clamp, followSlotCenterX, projectPoint, projectPoints, bbox, longerPath };
  global.AcrylicSyncMath = Math2D;

  // node 환경(테스트)에서는 fabric 이 없으므로 여기서 종료
  if (typeof global.fabric === 'undefined') {
    if (typeof module !== 'undefined' && module.exports) module.exports = Math2D;
    return;
  }

  const fabric = global.fabric;
  const CUT = 'acrylicCutPreview';
  const ASM = 'standAssemblyPreview';

  const AcrylicSync = {
    canvasMgr: null,
    _parts: [],           // {image, pointsPx, sourceW, sourceH, tol, base, cutline, tab, slot}
    _raf: 0,
    _pending: null,

    bind(canvasMgr) {
      if (this.canvasMgr === canvasMgr) return;
      this.canvasMgr = canvasMgr;
      const canvas = canvasMgr.canvas;
      const onXform = (e) => {
        const part = this._findByImage(e.target);
        if (part) this._schedule(part);
      };
      canvas.on('object:moving', onXform);
      canvas.on('object:scaling', onXform);
      canvas.on('object:rotating', onXform);
      canvas.on('object:modified', (e) => { const p = this._findByImage(e.target); if (p) this.reflow(p); });
      canvas.on('object:removed', (e) => {
        const part = this._findByImage(e.target);
        if (part) this._destroyPart(part, /*keepImage*/true);
      });
    },

    _findByImage(obj) { return obj ? this._parts.find(p => p.image === obj) : null; },

    _schedule(part) {
      this._pending = part;
      if (this._raf) return;
      const tick = () => { this._raf = 0; if (this._pending) { const p = this._pending; this._pending = null; this.reflow(p); } };
      this._raf = (global.requestAnimationFrame || ((cb) => setTimeout(cb, 16)))(tick);
    },

    /** 이미지 + 칼선 원본 point 로 Production Part(칼선/탭/슬롯)를 생성/추적한다. */
    attach(opts) {
      const { image, pointsPx, sourceW, sourceH, tol, base } = opts;
      if (!image || !pointsPx || !pointsPx.length) return null;
      // 같은 이미지의 기존 part 는 정리(재생성)
      const prev = this._findByImage(image);
      if (prev) this._destroyPart(prev, true);
      const part = { image, pointsPx, sourceW, sourceH, tol: tol || {}, base: base || null,
                     cutline: null, tab: null, slot: null };
      this._parts.push(part);
      this._build(part);
      // Undo/Redo 복원용: 자산에 칼선 원본 point + 규격을 저장(직렬화 가능한 로컬 지오메트리)
      const assetId = image.data && image.data.assetId;
      const store = global.UploadStore;
      if (assetId && store) {
        const asset = store.get(assetId);
        if (asset) asset.production = { pointsPx, sourceW, sourceH, tol: part.tol, base: part.base };
      }
      return part;
    },

    /** Undo/Redo 로 캔버스가 재구성된 뒤, 자산에 저장된 칼선/규격으로 Production Group 복원 (#20). */
    rehydrate(canvasMgr) {
      if (canvasMgr) this.bind(canvasMgr);
      this._parts = [];              // 이전 preview 객체는 loadFromJSON 이 이미 제거함(excludeFromExport)
      const store = global.UploadStore;
      if (!store) return;
      const images = this.canvasMgr.canvas.getObjects().filter(o => o.type === 'image' && !o.isGuide);
      images.forEach(img => {
        const asset = store.forObject(img);
        if (asset && asset.production) {
          const p = asset.production;
          this.attach({ image: img, pointsPx: p.pointsPx, sourceW: p.sourceW,
                        sourceH: p.sourceH, tol: p.tol, base: p.base });
        }
      });
    },

    _integratedCutline(part) {
      const world=this._project(part),pts=part.pointsPx,m=part.image.calcTransformMatrix(),c=this.canvasMgr.canvas,pxPerMm=c.width/(Number(this.canvasMgr.productSpecs.widthMm)||100),tabW=Math.max(12,Number(part.tol.tabWidthMm||15)*pxPerMm),tabH=Math.max(8,Number(part.tol.tabHeightMm||6)*pxPerMm);
      const maxY=Math.max(...pts.map(q=>q[1])),anchorX=(Math.min(...pts.map(q=>q[0]))+Math.max(...pts.map(q=>q[0])))/2,scaleX=Math.max(.0001,Math.hypot(m[0],m[1])*(part.image.width/part.sourceW)),halfSrc=(tabW/2)/scaleX,bandH=Math.max(part.sourceH*.06,4);
      const cand=pts.map((q,i)=>({q,i})).filter(v=>v.q[1]>=maxY-bandH),score=(v,x)=>(v.q[0]-x)**2+(v.q[1]-maxY)**2;
      let L=cand.filter(v=>v.q[0]<=anchorX).sort((a,b)=>score(a,anchorX-halfSrc)-score(b,anchorX-halfSrc))[0],R=cand.filter(v=>v.q[0]>=anchorX).sort((a,b)=>score(a,anchorX+halfSrc)-score(b,anchorX+halfSrc))[0];
      const bottomI=pts.reduce((best,q,i)=>q[1]>pts[best][1]?i:best,0);if(!L)L={i:(bottomI-2+pts.length)%pts.length};if(!R)R={i:(bottomI+2)%pts.length};if(L.i===R.i)R={i:(R.i+2)%pts.length};
      const bodyLocal=longerPath(pts,L.i,R.i),body=projectPoints(bodyLocal,part.sourceW,part.sourceH,part.image.width,part.image.height,m),left=body[0],right=body[body.length-1];
      let downx=m[2],downy=m[3],dn=Math.hypot(downx,downy)||1;downx/=dn;downy/=dn;
      const rb={x:right.x+downx*tabH,y:right.y+downy*tabH},lb={x:left.x+downx*tabH,y:left.y+downy*tabH};
      return {points:[...body,rb,lb,left],tabW,tabH,tabCenterX:(left.x+right.x)/2};
    },

    _build(part) {
      const c=this.canvasMgr.canvas,geo=this._integratedCutline(part),pxPerMm=c.width/(Number(this.canvasMgr.productSpecs.widthMm)||100),tol=part.tol;
      part._tabW=geo.tabW;part._tabH=geo.tabH;
      part.cutline=new fabric.Polyline(geo.points,{fill:'transparent',stroke:'#ec4899',strokeWidth:1.7,strokeDashArray:[6,4],strokeUniform:true,selectable:false,evented:false,objectCaching:false,excludeFromExport:true,productionPreviewType:CUT,name:'스탠드 본체+탭 일체형 칼선'});c.add(part.cutline);
      const bb=bbox(geo.points),baseW=Math.min(c.width*.78,Math.max(120,Number((part.base&&part.base.widthMm)||70)*pxPerMm)),baseH=Math.max(18,Number((part.base&&part.base.depthMm)||12)*pxPerMm*.34),baseTop=Math.min(c.height-baseH-18,bb.maxY+18),baseLeft=(c.width-baseW)/2;part._baseRect={left:baseLeft,top:baseTop,width:baseW,height:baseH};
      part.baseObj=new fabric.Rect({left:baseLeft,top:baseTop,width:baseW,height:baseH,rx:Math.min(9,baseH/2),ry:Math.min(9,baseH/2),fill:'rgba(255,255,255,.72)',stroke:'#94a3b8',strokeWidth:1.4,selectable:false,evented:false,excludeFromExport:true,productionPreviewType:ASM,name:'받침대'});
      const slotW=Math.max(16,Number(tol.tabWidthMm||15)*pxPerMm),slotH=Math.max(4,Number((tol.materialThicknessMm||3)+(tol.slotClearanceMm||.4))*pxPerMm);part._slotW=slotW;part._slotH=slotH;
      const br=part._baseRect,slotCx=followSlotCenterX(geo.tabCenterX,br.left,br.width,slotW,6);part.slot=new fabric.Rect({left:slotCx-slotW/2,top:br.top+(br.height-slotH)/2,width:slotW,height:slotH,fill:'#fff',stroke:'#ef4444',strokeWidth:1.5,rx:Math.min(slotH/2,5),ry:Math.min(slotH/2,5),lockScalingY:true,lockRotation:true,hasRotatingPoint:false,excludeFromExport:true,productionPreviewType:ASM,name:'받침대 슬롯'});
      part.slot.on('moving',()=>{const b=part._baseRect;part.slot.set({left:clamp(part.slot.left,b.left,b.left+b.width-slotW),top:clamp(part.slot.top,b.top,b.top+b.height-slotH)});});c.add(part.baseObj,part.slot);part.baseObj.sendToBack();part.cutline.bringToFront();part.slot.bringToFront();c.requestRenderAll();
    },

    _project(part) {
      const m = part.image.calcTransformMatrix();
      return projectPoints(part.pointsPx, part.sourceW, part.sourceH, part.image.width, part.image.height, m);
    },

    /** 이미지 변환에 맞춰 칼선/탭/슬롯을 재투영(형상 재계산 아님 — point 만 재투영). */
    reflow(part) {
      if(!part||!this._parts.includes(part))return;const c=this.canvasMgr.canvas,geo=this._integratedCutline(part);part.cutline.set({points:geo.points});if(typeof part.cutline._setPositionDimensions==='function')part.cutline._setPositionDimensions({});part.cutline.setCoords();const b=part._baseRect,slotCx=followSlotCenterX(geo.tabCenterX,b.left,b.width,part._slotW,6);part.slot.set({left:slotCx-part._slotW/2,top:b.top+(b.height-part._slotH)/2});part.slot.setCoords();part.cutline.bringToFront();part.slot.bringToFront();c.requestRenderAll();
    },

    _destroyPart(part, keepImage) {
      const c = this.canvasMgr.canvas;
      [part.cutline, part.slot, part.baseObj].forEach(o => { if (o) c.remove(o); });
      if (!keepImage && part.image) c.remove(part.image);
      this._parts = this._parts.filter(p => p !== part);
      c.requestRenderAll();
    },

    clearAll() { [...this._parts].forEach(p => this._destroyPart(p, true)); },
  };

  global.AcrylicSync = AcrylicSync;
})(typeof window !== 'undefined' ? window : globalThis);
