/* keyring-production-sync.js — v2.7.3
 * Transparent PNG -> ONE integrated outer cutline + keyring hole.
 * The lug is spliced into the body contour so no separate floating ring outline remains.
 */
(function(global){
  'use strict';
  function clamp(v,a,b){return Math.max(a,Math.min(b,v));}
  function projectPoint(px,py,sw,sh,iw,ih,m){const lx=(px/sw)*iw-iw/2,ly=(py/sh)*ih-ih/2;return{x:m[0]*lx+m[2]*ly+m[4],y:m[1]*lx+m[3]*ly+m[5]};}
  function projectPoints(points,sw,sh,iw,ih,m){return points.map(p=>projectPoint(p[0],p[1],sw,sh,iw,ih,m));}
  function forwardPath(points,start,end){const out=[];let i=start,n=points.length,guard=0;while(guard++<=n){out.push(points[i]);if(i===end)break;i=(i+1)%n;}return out;}
  function longerBodyPath(points,left,right){const a=forwardPath(points,left,right),b=forwardPath(points,right,left).reverse();return a.length>=b.length?a:b;}
  function dist2(p,x,y){const dx=p[0]-x,dy=p[1]-y;return dx*dx+dy*dy;}
  const Math2D={clamp,projectPoint,projectPoints,longerBodyPath};global.KeyringSyncMath=Math2D;
  if(typeof global.fabric==='undefined'){if(typeof module!=='undefined'&&module.exports)module.exports=Math2D;return;}
  const fabric=global.fabric,TYPE='keyringAssemblyPreview';
  const Sync={mgr:null,parts:[],raf:0,pending:null,
    bind(mgr){if(this.mgr===mgr)return;this.mgr=mgr;const c=mgr.canvas;const x=e=>{const p=this.parts.find(p=>p.image===e.target);if(p)this.schedule(p);};c.on('object:moving',x);c.on('object:scaling',x);c.on('object:rotating',x);c.on('object:modified',e=>{const p=this.parts.find(p=>p.image===e.target);if(p)this.reflow(p);});c.on('object:removed',e=>{const p=this.parts.find(p=>p.image===e.target);if(p)this.destroy(p,true);});},
    schedule(p){this.pending=p;if(this.raf)return;this.raf=(global.requestAnimationFrame||((f)=>setTimeout(f,16)))(()=>{this.raf=0;const q=this.pending;this.pending=null;if(q)this.reflow(q);});},
    attach({image,pointsPx,sourceW,sourceH,hole={}}){
      if(!image||!pointsPx?.length)return null;
      const old=this.parts.find(p=>p.image===image);if(old)this.destroy(old,true);
      const normalizedHole={innerMm:Number(hole.innerMm||3),outerMm:Number(hole.outerMm||7),count:Math.max(1,Math.min(2,Number(hole.count||1))),mode:hole.mode||'TOP_CENTER'};
      const p={image,pointsPx,sourceW,sourceH,hole:normalizedHole,cutline:null,holes:[]};
      const assetId=image?.data?.assetId;
      const asset=global.UploadStore?.get?.(assetId);
      if(asset)asset.production={kind:'keyring',pointsPx:pointsPx.map(q=>[Number(q[0]),Number(q[1])]),sourceW:Number(sourceW),sourceH:Number(sourceH),hole:{...normalizedHole}};
      this.parts.push(p);this.build(p);return p;
    },
    _anchorX(p,index=0){const ys=p.pointsPx.map(q=>q[1]),minY=Math.min(...ys),band=p.pointsPx.filter(q=>q[1]<=minY+Math.max(2,p.sourceH*.07));let x=band.length?band.reduce((a,q)=>a+q[0],0)/band.length:p.sourceW/2;if(p.hole.mode==='TOP_LEFT')x=p.sourceW*.30;else if(p.hole.mode==='TOP_RIGHT')x=p.sourceW*.70;if(p.hole.count===2)x+=(index===0?-1:1)*p.sourceW*.15;return clamp(x,0,p.sourceW);},
    _integratedWorld(p,index=0){
      const pts=p.pointsPx,m=p.image.calcTransformMatrix(),world=projectPoints(pts,p.sourceW,p.sourceH,p.image.width,p.image.height,m),mmPx=this.mgr.canvas.width/(Number(this.mgr.productSpecs.widthMm)||100),r=Math.max(5,p.hole.outerMm*mmPx/2);
      const minY=Math.min(...pts.map(q=>q[1])),ax=this._anchorX(p,index),scaleX=Math.max(.0001,Math.hypot(m[0],m[1])*(p.image.width/p.sourceW)),halfSrc=(r*.46)/scaleX,bandH=Math.max(p.sourceH*.07,(r*.45)/Math.max(.0001,Math.hypot(m[2],m[3])*(p.image.height/p.sourceH)));
      const candidates=pts.map((q,i)=>({q,i})).filter(v=>v.q[1]<=minY+bandH);
      let L=candidates.filter(v=>v.q[0]<=ax).sort((u,v)=>dist2(u.q,ax-halfSrc,minY)-dist2(v.q,ax-halfSrc,minY))[0];
      let R=candidates.filter(v=>v.q[0]>=ax).sort((u,v)=>dist2(u.q,ax+halfSrc,minY)-dist2(v.q,ax+halfSrc,minY))[0];
      const topI=pts.reduce((best,q,i)=>q[1]<pts[best][1]?i:best,0);if(!L)L={i:(topI-2+pts.length)%pts.length};if(!R)R={i:(topI+2)%pts.length};if(L.i===R.i)R={i:(R.i+2)%pts.length};
      const bodyLocal=longerBodyPath(pts,L.i,R.i),body=projectPoints(bodyLocal,p.sourceW,p.sourceH,p.image.width,p.image.height,m),left=body[0],right=body[body.length-1];
      const dx=right.x-left.x,dy=right.y-left.y,d=Math.max(.01,Math.hypot(dx,dy)),ux=dx/d,uy=dy/d;
      let upx=-m[2],upy=-m[3],un=Math.hypot(upx,upy)||1;upx/=un;upy/=un;
      const rr=Math.max(r,d*.53),half=d/2,h=Math.sqrt(Math.max(0,rr*rr-half*half)),mid={x:(left.x+right.x)/2,y:(left.y+right.y)/2},center={x:mid.x+upx*h,y:mid.y+upy*h};
      const alpha=Math.asin(clamp(h/rr,-1,1)),arc=[]; // right -> over top -> left
      for(let t=-alpha;t<=Math.PI+alpha+.001;t+=(Math.PI+2*alpha)/26){arc.push({x:center.x+ux*rr*Math.cos(t)+upx*rr*Math.sin(t),y:center.y+uy*rr*Math.cos(t)+upy*rr*Math.sin(t)});}
      return {points:[...body,...arc],center,radius:rr};
    },
    build(p){const c=this.mgr.canvas;p.cutline=new fabric.Polyline([{x:0,y:0},{x:1,y:1}],{fill:'transparent',stroke:'#ec4899',strokeWidth:1.7,strokeDashArray:[6,4],strokeUniform:true,selectable:false,evented:false,objectCaching:false,excludeFromExport:true,productionPreviewType:TYPE,productionRole:'keyring-cutline',name:'키링 일체형 칼선'});c.add(p.cutline);for(let i=0;i<p.hole.count;i++){const inner=new fabric.Circle({radius:1,fill:'#fff',stroke:'#64748b',strokeWidth:1.2,strokeUniform:true,selectable:false,evented:false,excludeFromExport:true,productionPreviewType:TYPE,productionRole:'keyring-hole',name:'키링 타공'});p.holes.push(inner);c.add(inner);}this.reflow(p);},
    reflow(p){if(!this.parts.includes(p))return;const c=this.mgr.canvas,geom=this._integratedWorld(p,0);p.cutline.set({points:geom.points});if(p.cutline._setPositionDimensions)p.cutline._setPositionDimensions({});p.cutline.setCoords();const all=[geom];for(let i=1;i<p.hole.count;i++)all.push(this._integratedWorld(p,i));
      // two-hole mode: preview main body with first lug plus second lug as an open outline only; default is one hole.
      p.holes.forEach((inner,i)=>{const g=all[Math.min(i,all.length-1)],mmPx=c.width/(Number(this.mgr.productSpecs.widthMm)||100),ir=Math.max(2,p.hole.innerMm*mmPx/2);inner.set({radius:ir,left:g.center.x-ir,top:g.center.y-ir});inner.setCoords();inner.bringToFront();});p.cutline.bringToFront();c.requestRenderAll();},
    updateHole(opts={}){this.parts.forEach(p=>{Object.assign(p.hole,opts);const asset=global.UploadStore?.get?.(p.image?.data?.assetId);if(asset?.production?.kind==='keyring')asset.production.hole={...p.hole};const c=this.mgr.canvas;[p.cutline,...p.holes].forEach(o=>o&&c.remove(o));p.cutline=null;p.holes=[];this.build(p);});},
    rehydrate(mgr){
      this.bind(mgr);this.clearAll();
      mgr.canvas.getObjects().filter(o=>o?.type==='image'&&!o.isGuide&&!o.productionPreviewType).forEach(image=>{
        const asset=global.UploadStore?.get?.(image?.data?.assetId),prod=asset?.production;
        if(prod?.kind!=='keyring'||!Array.isArray(prod.pointsPx)||!prod.pointsPx.length)return;
        this.attach({image,pointsPx:prod.pointsPx,sourceW:prod.sourceW,sourceH:prod.sourceH,hole:prod.hole||{}});
      });
    },
    destroy(p,keepImage){const c=this.mgr.canvas;[p.cutline,...p.holes].forEach(o=>o&&c.remove(o));if(!keepImage&&p.image)c.remove(p.image);this.parts=this.parts.filter(x=>x!==p);c.requestRenderAll();},clearAll(){[...this.parts].forEach(p=>this.destroy(p,true));}
  };global.KeyringSync=Sync;
})(typeof window!=='undefined'?window:globalThis);
