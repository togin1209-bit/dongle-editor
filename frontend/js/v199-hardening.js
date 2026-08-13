/* v1.9.9 Production Hardening
 * 운영 안정화 + 편집 정밀도 + 제작사고 방지 Quick Wins.
 * 기존 app.js를 덮어쓰지 않고 확장한다.
 */
(function(global){
'use strict';
const $=id=>document.getElementById(id);
const qs=(s,r=document)=>r.querySelector(s);
const qsa=(s,r=document)=>[...r.querySelectorAll(s)];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const isAcrylic=()=>/^acrylic_/.test(global.canvasMgr?.productSpecs?.id||'');
const isStand=()=>global.canvasMgr?.productSpecs?.id==='acrylic_stand';
const mmPerPx=()=>Number(global.canvasMgr?.productSpecs?.widthMm||1)/Math.max(1,global.canvasMgr?.canvas?.width||1);
const pxPerMm=()=>1/mmPerPx();
const round1=n=>Math.round(Number(n||0)*10)/10;

function toast(msg,type='info'){(global.dongleToast||console.log)(msg,type);}
function active(){return global.canvasMgr?.activeObject?.();}
function productionObjects(){return global.canvasMgr?.canvas?.getObjects().filter(o=>!o.isGuide&&!o.productionPreviewType)||[];}

function waitForApp(){
  if(global.canvasMgr&&global.canvasMgr.canvas){init();return;}
  setTimeout(waitForApp,80);
}

function init(){
  const mgr=global.canvasMgr, canvas=mgr.canvas;
  if(global.__v199HardeningReady)return; global.__v199HardeningReady=true;
  document.documentElement.dataset.dongleVersion='2.3.0';

  // v2.1.4-fix: MutationObserver 무한루프 방지 — 콜백이 관찰 대상 DOM을 스스로 변경해
  // 옵저버가 다시 자신을 트리거하며 '페이지 응답 없음(무한루프)'을 유발했음.
  // 콜백 실행 중에는 관찰을 끊고, 끝난 뒤 rAF로 재관찰한다. 재진입도 플래그로 차단.
  function guardedObserver(target, cb){
    if(!target) return null;
    let running=false;
    const opts={childList:true,subtree:true};
    const obs=new MutationObserver(()=>{
      if(running) return;
      running=true; obs.disconnect();
      try{ cb(); }catch(e){}
      (global.requestAnimationFrame||((f)=>setTimeout(f,16)))(()=>{ running=false; obs.observe(target,opts); });
    });
    obs.observe(target,opts);
    return obs;
  }

  // 1 Empty State + same-page import
  const empty=$('canvas-empty-state'), emptyBtn=$('empty-import-btn');
  const triggerImport=()=>{
    const stand=$('stand-file-import'), generic=$('file-upload');
    (isStand()&&stand?stand:generic||stand)?.click();
  };
  emptyBtn?.addEventListener('click',e=>{e.stopPropagation();triggerImport();});
  empty?.addEventListener('click',e=>{if(e.target===empty||e.target.closest('.empty-drop-icon')||e.target.tagName==='STRONG'||e.target.tagName==='SPAN')triggerImport();});
  empty?.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();triggerImport();}});
  function refreshEmpty(){const n=productionObjects().filter(o=>o.type==='image'||['i-text','textbox','text','rect','circle','polygon','path'].includes(o.type)).length;empty?.classList.toggle('hidden',n>0);}
  canvas.on('object:added',refreshEmpty);canvas.on('object:removed',refreshEmpty);setTimeout(refreshEmpty,300);

  // 2 Precision W/H/X/Y in mm
  const ids=['obj-x-mm','obj-y-mm','obj-w-mm','obj-h-mm'];
  function refreshPrecision(){
    const o=active(), card=$('precision-card');
    if(!card)return;
    const disabled=!o||o.isGuide||o.productionPreviewType;
    card.classList.toggle('disabled',disabled);
    ids.forEach(id=>$(id)&&( $(id).disabled=disabled ));
    if(disabled){ids.forEach(id=>$(id)&&($(id).value=''));return;}
    const m=mmPerPx(), b=o.getBoundingRect(true,true);
    $('obj-x-mm').value=round1(b.left*m);$('obj-y-mm').value=round1(b.top*m);$('obj-w-mm').value=round1(b.width*m);$('obj-h-mm').value=round1(b.height*m);
  }
  function applyPrecision(){
    const o=active();if(!o||o.isGuide)return;
    const ppm=pxPerMm(), x=Number($('obj-x-mm').value),y=Number($('obj-y-mm').value),w=Number($('obj-w-mm').value),h=Number($('obj-h-mm').value);
    if([x,y,w,h].some(v=>!Number.isFinite(v)||v<0))return;
    const b=o.getBoundingRect(true,true), sx=w*ppm/Math.max(1,b.width), sy=h*ppm/Math.max(1,b.height);
    o.scaleX*=sx;o.scaleY*=sy;o.setCoords();
    const nb=o.getBoundingRect(true,true);o.left+=(x*ppm-nb.left);o.top+=(y*ppm-nb.top);o.setCoords();
    canvas.requestRenderAll();mgr.saveHistory('수치 배치');refreshPrecision();
  }
  ids.forEach(id=>$(id)?.addEventListener('change',applyPrecision));
  ['selection:created','selection:updated','selection:cleared','object:moving','object:scaling','object:rotating','object:modified'].forEach(ev=>canvas.on(ev,refreshPrecision));

  // 3 Align / distribute
  function selectedObjects(){const o=active();if(!o)return[];return o.type==='activeSelection'?[...o._objects]:[o];}
  function align(action){
    const arr=selectedObjects().filter(o=>!o.isGuide&&!o.productionPreviewType);if(!arr.length)return;
    if(arr.length===1){
      const o=arr[0],b=o.getBoundingRect(true,true);
      if(action==='left')o.left-=b.left;
      if(action==='right')o.left+=canvas.width-(b.left+b.width);
      if(action==='top')o.top-=b.top;
      if(action==='bottom')o.top+=canvas.height-(b.top+b.height);
      if(action==='hcenter')o.left+=(canvas.width/2-(b.left+b.width/2));
      if(action==='vcenter')o.top+=(canvas.height/2-(b.top+b.height/2));
    }else{
      const boxes=arr.map(o=>({o,b:o.getBoundingRect(true,true)}));
      const minX=Math.min(...boxes.map(x=>x.b.left)),maxX=Math.max(...boxes.map(x=>x.b.left+x.b.width));
      const minY=Math.min(...boxes.map(x=>x.b.top)),maxY=Math.max(...boxes.map(x=>x.b.top+x.b.height));
      if(['left','right','hcenter'].includes(action)) boxes.forEach(x=>{const target=action==='left'?minX:action==='right'?maxX-x.b.width:(minX+maxX-x.b.width)/2;x.o.left+=target-x.b.left;});
      if(['top','bottom','vcenter'].includes(action)) boxes.forEach(x=>{const target=action==='top'?minY:action==='bottom'?maxY-x.b.height:(minY+maxY-x.b.height)/2;x.o.top+=target-x.b.top;});
      if(action==='distribute-h'&&arr.length>2){boxes.sort((a,b)=>a.b.left-b.b.left);const total=boxes.reduce((s,x)=>s+x.b.width,0),gap=(maxX-minX-total)/(boxes.length-1);let x=minX;boxes.forEach(z=>{z.o.left+=x-z.b.left;x+=z.b.width+gap;});}
      if(action==='distribute-v'&&arr.length>2){boxes.sort((a,b)=>a.b.top-b.b.top);const total=boxes.reduce((s,x)=>s+x.b.height,0),gap=(maxY-minY-total)/(boxes.length-1);let y=minY;boxes.forEach(z=>{z.o.top+=y-z.b.top;y+=z.b.height+gap;});}
    }
    arr.forEach(o=>o.setCoords());canvas.requestRenderAll();mgr.saveHistory('정렬/분배');
  }
  qsa('#align-toolbar [data-align]').forEach(b=>b.addEventListener('click',()=>align(b.dataset.align)));

  // 4 mm ruler + snap visualization — v2.5.1: workspace-fixed ruler frame
  function ensureWorkspaceRulerFrame(){
    const workspace=$('canvas-workspace');if(!workspace)return null;
    let top=$('workspace-ruler-top'),left=$('workspace-ruler-left'),corner=$('workspace-ruler-corner');
    if(!top){top=document.createElement('div');top.id='workspace-ruler-top';top.className='workspace-ruler-top';workspace.appendChild(top);}
    if(!left){left=document.createElement('div');left.id='workspace-ruler-left';left.className='workspace-ruler-left';workspace.appendChild(left);}
    if(!corner){corner=document.createElement('div');corner.id='workspace-ruler-corner';corner.className='workspace-ruler-corner';workspace.appendChild(corner);}
    return {workspace,top,left,corner};
  }
  function buildRulers(){
    const frame=ensureWorkspaceRulerFrame(),wrap=$('canvas-wrapper');if(!frame||!wrap)return;
    const {workspace,top,left,corner}=frame;top.innerHTML='';left.innerHTML='';corner.textContent='mm';corner.setAttribute('aria-label','눈금 단위 밀리미터');
    const ws=workspace.getBoundingClientRect(),wr=wrap.getBoundingClientRect();
    const w=Number(mgr.productSpecs.widthMm||100),h=Number(mgr.productSpecs.heightMm||100);
    const canvasLeft=wr.left-ws.left+workspace.scrollLeft,canvasTop=wr.top-ws.top+workspace.scrollTop;
    const visibleW=wr.width,visibleH=wr.height,candidates=[1,2,5,10,20,25,50,100,200,500,1000,2000,5000],targetPx=52;
    const majorX=candidates.find(v=>(v/w*visibleW)>=targetPx)||candidates[candidates.length-1];
    const majorY=candidates.find(v=>(v/h*visibleH)>=targetPx)||candidates[candidates.length-1];
    const fragX=document.createDocumentFragment(),fragY=document.createDocumentFragment();
    const drawX=(mm,major)=>{
      const x=canvasLeft+(mm/w*visibleW);if(x<-4||x>workspace.clientWidth+4)return;
      const t=document.createElement('i');t.className=`workspace-ruler-tick ${major?'major':'minor'}`;t.style.left=`${x}px`;fragX.appendChild(t);
      if(major){const l=document.createElement('span');l.className='workspace-ruler-label';l.style.left=`${x+3}px`;l.textContent=Number.isInteger(mm)?String(mm):String(Number(mm.toFixed(2)));fragX.appendChild(l);}
    };
    const drawY=(mm,major)=>{
      const y=canvasTop+(mm/h*visibleH);if(y<-4||y>workspace.clientHeight+4)return;
      const t=document.createElement('i');t.className=`workspace-ruler-tick ${major?'major':'minor'}`;t.style.top=`${y}px`;fragY.appendChild(t);
      if(major){const l=document.createElement('span');l.className='workspace-ruler-label';l.style.top=`${y+3}px`;l.textContent=Number.isInteger(mm)?String(mm):String(Number(mm.toFixed(2)));fragY.appendChild(l);}
    };
    const minorX=majorX/5,minorY=majorY/5;
    for(let mm=0;mm<=w+.0001;mm+=minorX){const major=Math.abs((mm/majorX)-Math.round(mm/majorX))<.001;drawX(mm,major);}
    for(let mm=0;mm<=h+.0001;mm+=minorY){const major=Math.abs((mm/majorY)-Math.round(mm/majorY))<.001;drawY(mm,major);}
    top.appendChild(fragX);left.appendChild(fragY);
    const ox=document.createElement('i');ox.className='ruler-origin-x';ox.style.left=`${canvasLeft}px`;top.appendChild(ox);
    const oy=document.createElement('i');oy.className='ruler-origin-y';oy.style.top=`${canvasTop}px`;left.appendChild(oy);
  }
  const origUpdate=mgr.updateCanvasDimensions.bind(mgr);
  mgr.updateCanvasDimensions=function(){const r=origUpdate();requestAnimationFrame(()=>requestAnimationFrame(buildRulers));return r;};
  window.addEventListener('dongle:zoomchange',()=>requestAnimationFrame(buildRulers));
  window.addEventListener('resize',()=>requestAnimationFrame(buildRulers));
  $('canvas-workspace')?.addEventListener('scroll',()=>requestAnimationFrame(buildRulers),{passive:true});
  new ResizeObserver(()=>requestAnimationFrame(buildRulers)).observe($('canvas-workspace'));
  requestAnimationFrame(()=>requestAnimationFrame(buildRulers));
  canvas.on('object:moving',e=>{
    const o=e.target;if(!o||!mgr.snapEnabled)return;
    const b=o.getBoundingRect(true,true),cx=b.left+b.width/2,cy=b.top+b.height/2;
    const v=$('snap-guide-v'),h=$('snap-guide-h');
    v?.classList.toggle('hidden',Math.abs(cx-canvas.width/2)>8);h?.classList.toggle('hidden',Math.abs(cy-canvas.height/2)>8);
  });
  canvas.on('object:modified',()=>{$('snap-guide-v')?.classList.add('hidden');$('snap-guide-h')?.classList.add('hidden');});

  // 5 Zoom controls
  $('zoom-floating-out')?.addEventListener('click',()=>mgr.zoomOut());$('zoom-floating-in')?.addEventListener('click',()=>mgr.zoomIn());$('zoom-floating-fit')?.addEventListener('click',()=>mgr.fitToWorkspace());

  // 6 Replace image preserving transform
  const replaceBtn=document.createElement('button');replaceBtn.id='v199-replace-image';replaceBtn.textContent='이미지 교체';replaceBtn.title='위치·크기를 유지하고 이미지만 교체';replaceBtn.className='hidden';
  $('v17-floating-toolbar')?.insertBefore(replaceBtn,$('v17-float-duplicate'));
  const replaceInput=document.createElement('input');replaceInput.type='file';replaceInput.accept='image/png,image/jpeg,image/webp';replaceInput.hidden=true;document.body.appendChild(replaceInput);
  replaceBtn.addEventListener('click',()=>replaceInput.click());
  replaceInput.addEventListener('change',async e=>{
    const f=e.target.files[0],old=active();if(!f||!old||old.type!=='image')return;e.target.value='';
    try{
      const asset=await UploadStore.add(f);const idx=canvas.getObjects().indexOf(old);const props={left:old.left,top:old.top,scaleX:old.scaleX,scaleY:old.scaleY,angle:old.angle,flipX:old.flipX,flipY:old.flipY,originX:old.originX,originY:old.originY};
      fabric.Image.fromURL(asset.src,img=>{img.set({...props,name:f.name});UploadStore.tagObject(img,asset.id,'design');canvas.remove(old);canvas.insertAt(img,Math.max(0,idx),false);canvas.setActiveObject(img);canvas.requestRenderAll();mgr.saveHistory('이미지 교체');toast('위치와 크기를 유지해 이미지를 교체했습니다.','success');});
    }catch(err){toast(actionError(err),'error');}
  });
  function floatVisibility(){replaceBtn.classList.toggle('hidden',active()?.type!=='image');}
  ['selection:created','selection:updated','selection:cleared'].forEach(ev=>canvas.on(ev,floatVisibility));

  // 7 Layer enhancement (thumbnail/visibility/lock/name)
  function enhanceLayers(){
    const rows=qsa('#layers-container .layer-row');const layers=mgr.layers();
    rows.forEach((row,i)=>{
      if(row.dataset.v199)return;row.dataset.v199='1';const item=layers[i];if(!item)return;
      // v2.1.4-fix: 레이어 썸네일 toDataURL 제거 — 대용량 이미지에서 매 레이어 갱신마다 rasterize가 멈춤을 유발.
      const o=item.obj;const thumb=document.createElement('span');thumb.className='layer-thumb';
      thumb.textContent=o.type==='image'?'🖼':(['i-text','textbox','text'].includes(o.type)?'T':'◆');
      row.prepend(thumb);
      const nameEl=qsa('span,button',row).find(x=>x.textContent?.trim()===item.name)||row.children[1];if(nameEl){nameEl.classList.add('layer-name-edit');nameEl.title='더블클릭하여 이름 변경';nameEl.addEventListener('dblclick',e=>{e.stopPropagation();const n=prompt('레이어 이름',o.name||item.name);if(n){o.name=n;nameEl.textContent=n;mgr.saveHistory('레이어 이름 변경');}});}
      const actions=document.createElement('div');actions.className='layer-inline-actions';
      const eye=document.createElement('button');eye.innerHTML='<i data-lucide="eye"></i>';eye.title='표시/숨김';eye.onclick=e=>{e.stopPropagation();o.visible=!o.visible;canvas.requestRenderAll();eye.innerHTML=`<i data-lucide="${o.visible?'eye':'eye-off'}"></i>`;lucide?.createIcons();};
      const lock=document.createElement('button');lock.innerHTML=`<i data-lucide="${o.lockMovementX?'lock':'unlock'}"></i>`;lock.title='잠금/해제';lock.onclick=e=>{e.stopPropagation();const v=!o.lockMovementX;o.set({lockMovementX:v,lockMovementY:v,lockScalingX:v,lockScalingY:v,lockRotation:v,selectable:true});canvas.requestRenderAll();lock.innerHTML=`<i data-lucide="${v?'lock':'unlock'}"></i>`;lucide?.createIcons();};
      actions.append(eye,lock);row.append(actions);
    });lucide?.createIcons();
  }
  guardedObserver($('layers-container'),enhanceLayers);setTimeout(enhanceLayers,500);

  // 8 History thumbnails
  mgr.historyThumbs=mgr.historyThumbs||[];
  // v2.1.2-fix: 저장마다 toDataURL 썸네일 생성 제거 — 대용량 이미지에서 매 변경 rasterize가 멈춤을 유발. (히스토리 자체는 유지)
  function enhanceHistory(){qsa('#v17-history-list .v17-history-row').forEach((row,i)=>{if(row.dataset.v199)return;row.dataset.v199='1';const img=document.createElement('img');img.className='history-thumb';img.alt='';img.src=mgr.historyThumbs[i]||'';row.prepend(img);});}
  guardedObserver($('v17-history-list'),enhanceHistory);

  // 9 Acrylic 1mm print-safe guide
  function addAcrylicSafe(){
    qsa('#canvas-wrapper .acrylic-safe-warning').forEach(e=>e.remove());
    if(!isAcrylic())return;
    const wrap=$('canvas-wrapper'),m=1*pxPerMm(),d=document.createElement('div');d.className='acrylic-safe-warning';
    d.style.left=`${m}px`;d.style.top=`${m}px`;d.style.width=`${Math.max(0,canvas.width-m*2)}px`;d.style.height=`${Math.max(0,canvas.height-m*2)}px`;d.title='인쇄 안전영역: 재단선 사방 1mm 안쪽';wrap?.appendChild(d);
  }
  const origSetProduct=mgr.setProduct.bind(mgr);mgr.setProduct=function(spec){const r=origSetProduct(spec);setTimeout(()=>{addAcrylicSafe();buildRulers();updateProdLayerCard();},0);return r;};addAcrylicSafe();

  // 10 Real-time 5mm stand gap warning (image bbox approximation)
  const gapBadge=document.createElement('div');gapBadge.className='gap-warning-badge hidden';$('canvas-wrapper')?.appendChild(gapBadge);
  function checkPartGap(){
    if(!isStand()){gapBadge.classList.add('hidden');return;}
    const imgs=canvas.getObjects().filter(o=>o.type==='image'&&!o.isGuide&&o.visible!==false);if(imgs.length<2){gapBadge.classList.add('hidden');return;}
    let min=Infinity,pair=null;
    for(let i=0;i<imgs.length;i++)for(let j=i+1;j<imgs.length;j++){const a=imgs[i].getBoundingRect(true,true),b=imgs[j].getBoundingRect(true,true);const dx=Math.max(0,Math.max(a.left,b.left)-Math.min(a.left+a.width,b.left+b.width));const dy=Math.max(0,Math.max(a.top,b.top)-Math.min(a.top+a.height,b.top+b.height));const dist=Math.hypot(dx,dy)*mmPerPx();if(dist<min){min=dist;pair=[a,b];}}
    if(min<5&&pair){gapBadge.textContent=`간격 ${round1(min)}mm · 최소 5mm`;gapBadge.style.left=`${Math.min(canvas.width-110,(pair[0].left+pair[1].left)/2)}px`;gapBadge.style.top=`${Math.min(canvas.height-24,(pair[0].top+pair[1].top)/2)}px`;gapBadge.classList.remove('hidden');}
    else gapBadge.classList.add('hidden');
  }
  ['object:moving','object:modified','object:added','object:removed'].forEach(ev=>canvas.on(ev,checkPartGap));

  // 11 3T preset
  const details=qs('#acrylic-stand-tools .stand-detail');
  if(details&&!$('preset-3t')){const b=document.createElement('button');b.id='preset-3t';b.type='button';b.className='mini-btn';b.textContent='3T 규격';b.title='아크릴 두께 3mm 프리셋';b.onclick=()=>{$('stand-thickness').value='3';toast('아크릴 두께 3T(3mm)를 적용했습니다.','success');};details.parentNode.insertBefore(b,details);}

  // 12 Production layer visibility
  function updateProdLayerCard(){$('production-layer-card')?.classList.toggle('hidden',!isAcrylic());}
  qsa('.prod-layer-toggle').forEach(b=>b.addEventListener('click',()=>{
    b.classList.toggle('active');const on=b.classList.contains('active'),role=b.dataset.prodLayer;
    canvas.getObjects().forEach(o=>{
      if(role==='cutline'&&(o.productionPreviewType==='acrylicCutPreview'||/CUT Preview/i.test(o.name||'')))o.visible=on;
      if(role==='print'&&o.type==='image'&&o.data?.productionRole!=='white')o.visible=on;
      if(role==='white'&&o.data?.productionRole==='white')o.visible=on;
    });canvas.requestRenderAll();
  }));updateProdLayerCard();

  // 13 Tab merge/link status
  function updateMergeStatus(){const e=$('tab-merge-status');if(!e)return;const parts=global.AcrylicSync?._parts||[];if(isStand()&&parts.length){e.textContent=`연동 완료 · 파츠 ${parts.length}개 · 칼선/탭/슬롯 동기화`;e.style.color='#16784f';}else e.textContent='칼선 생성 후 연동 상태를 표시합니다.';}
  ['object:modified','object:added','object:removed'].forEach(ev=>canvas.on(ev,()=>setTimeout(updateMergeStatus,20)));setInterval(updateMergeStatus,1200);

  // 14 Preflight issue → locate
  function enhancePreflight(){
    qsa('#preflight-list-container > *').forEach(card=>{if(card.dataset.v199)return;card.dataset.v199='1';if(!/오류|경고|ERROR|WARNING|부족|벗어|해상도|간격/i.test(card.textContent||''))return;const b=document.createElement('button');b.className='issue-locate-btn';b.textContent='문제 위치 보기';b.onclick=()=>{const objs=productionObjects();if(objs.length){canvas.setActiveObject(objs[0]);objs[0].bringToFront?.();canvas.requestRenderAll();toast('문제와 관련된 객체를 선택했습니다.','info');}};card.appendChild(b);});
  }
  guardedObserver($('preflight-list-container'),enhancePreflight);

  // 15 status reason tooltip
  function enhanceStatusBadges(){qsa('.status-badge').forEach(b=>{b.title=b.textContent.includes('검증')?'공식 제작값 중 일부가 미확정입니다. 출력 전 제작규격을 확인하세요.':'검증된 제작 프로필을 사용합니다.';});}
  guardedObserver($('taxonomy-container'),enhanceStatusBadges);setTimeout(enhanceStatusBadges,300);

  // 16 remove duplicated density / 20 related purpose
  function compactInfo(){
    const card=$('product-status-card');if(card)card.style.display='none';
    qsa('.related-products-box button').forEach(b=>b.title=`${b.textContent.trim()} 상품으로 전환`);
  }
  setTimeout(compactInfo,400);guardedObserver($('related-products-box'),compactInfo);

  // 18 Accordion on major left sections
  function addAccordion(el,label){
    if(!el||el.dataset.accordion)return;el.dataset.accordion='1';
    const h=document.createElement('button');h.type='button';h.className='section-collapse-btn';h.innerHTML=`<span>${label}</span><i data-lucide="chevron-up"></i>`;el.prepend(h);
    h.onclick=()=>{const collapsed=el.classList.toggle('section-collapsed');h.querySelector('i')?.setAttribute('data-lucide',collapsed?'chevron-down':'chevron-up');lucide?.createIcons();};
  }
  // v2.1.1: 아코디언 헤더 제거 — 섹션에 이미 동일 제목(h3)이 있어 '제작 규격/아크릴 제작 도구'가 중복 표시되던 문제 해결.

  // 19 context retention alert
  let lastProduct=mgr.productSpecs.id;
  const productWatch=new MutationObserver(()=>{const now=mgr.productSpecs.id;if(now!==lastProduct){if(productionObjects().length)toast('상품이 변경되었습니다. 기존 디자인은 유지되며 새 제작규격을 확인해주세요.','info');lastProduct=now;}});
  productWatch.observe($('footer-product-name'),{childList:true,characterData:true,subtree:true});

  // 21 Final preview
  const modal=$('modal-final-preview');
  let previewConfirmed=false;
  $('btn-open-export-modal')?.addEventListener('click',()=>{previewConfirmed=false;});
  $('btn-confirm-export-pdf')?.addEventListener('click',e=>{if(!previewConfirmed){e.preventDefault();e.stopImmediatePropagation();$('btn-show-final-preview')?.click();toast('최종 미리보기를 확인한 뒤 제작파일을 생성해주세요.','info');}},true);
  $('btn-show-final-preview')?.addEventListener('click',async()=>{
    try{
      showProgress('최종 미리보기를 준비하고 있습니다.');
      const prev=active();canvas.discardActiveObject();canvas.requestRenderAll();
      const data=canvas.toDataURL({format:'png',multiplier:1.5,enableRetinaScaling:false});
      if(prev&&canvas.getObjects().includes(prev))canvas.setActiveObject(prev);
      canvas.requestRenderAll();
      $('final-preview-image').src=data;modal.classList.remove('hidden');modal.classList.add('flex');
    }finally{hideProgress();}
  });
  const closePreview=()=>{modal.classList.add('hidden');modal.classList.remove('flex');};$('btn-close-final-preview')?.addEventListener('click',closePreview);$('btn-preview-confirm')?.addEventListener('click',()=>{previewConfirmed=true;closePreview();toast('최종 미리보기를 확인했습니다.','success');});

  // 22 server autosave/session recovery
  const sessionId=`browser_${Math.random().toString(36).slice(2)}_${Date.now().toString(36)}`;let saveTimer=null,lastSnapshotHash='';
  async function autosave(){
    try{const state=canvas.toDatalessJSON(['name','data']);const payload={product_id:mgr.productSpecs.id,product_specs:mgr.productSpecs,canvas:state,updated_at:new Date().toISOString()};const s=JSON.stringify(payload);if(s===lastSnapshotHash)return;lastSnapshotHash=s;await fetch(`/api/session-snapshots/${sessionId}`,{method:'POST',headers:{'Content-Type':'application/json'},body:s});}catch{}
  }
  // v2.1.2-fix: 자동저장/세션복구 비활성화 — 변경마다 대용량 이미지가 포함된 전체 캔버스를 직렬화·전송하고
  // 로드 시 blocking confirm()을 띄워 이미지 업로드 시 화면 멈춤의 주원인이었음. (필요 시 별도 경량 방식으로 재도입)
  void autosave; void saveTimer; void lastSnapshotHash; void sessionId;

  // 24 package preview text updated dynamically
  const pkg=$('export-package-preview');if(pkg)pkg.title='제작 PDF · 고객 확인용 시안 · 매니페스트를 기준으로 패키지를 구성합니다.';

  // 26 progress UI for heavy endpoints
  const originalFetch=global.fetch.bind(global);let pendingHeavy=0;
  global.fetch=async function(input,opts){const url=typeof input==='string'?input:(input?.url||'');const heavy=/remove-background|\/export|\/package|\/proof|preview-contour/.test(url);if(heavy){pendingHeavy++;showProgress(labelForUrl(url));}try{return await originalFetch(input,opts);}finally{if(heavy&&--pendingHeavy<=0)hideProgress();}};
  function labelForUrl(u){if(u.includes('remove-background'))return'배경을 제거하고 있습니다.';if(u.includes('preview-contour'))return'칼선을 분석하고 있습니다.';if(u.includes('/export'))return'인쇄파일을 생성하고 있습니다.';if(u.includes('/package'))return'제작 패키지를 만들고 있습니다.';if(u.includes('/upload'))return'이미지를 확인하고 있습니다.';return'처리 중입니다.';}
  let __progressSafety=null;
  function showProgress(msg){let o=$('v199-progress');if(!o){o=document.createElement('div');o.id='v199-progress';o.className='progress-overlay';o.innerHTML='<div class="progress-card"><div class="progress-title"></div><div class="progress-track"><div class="progress-bar"></div></div><div class="progress-detail">완료될 때까지 잠시 기다려주세요.</div></div>';document.body.appendChild(o);}o.querySelector('.progress-title').textContent=msg||'처리 중입니다.';o.classList.remove('hidden');
    // v2.0.1-fix: 진행 표시가 화면에 영구히 남지 않도록 안전 타임아웃(15s) — 업로드 지연/실패에도 화면이 멈추지 않는다.
    clearTimeout(__progressSafety);__progressSafety=setTimeout(function(){pendingHeavy=0;hideProgress();},15000);}
  function hideProgress(){clearTimeout(__progressSafety);pendingHeavy=0;$('v199-progress')?.classList.add('hidden');}

  // 27 actionable error language
  function actionError(err){const s=String(err?.message||err||'');if(/RGBA|투명.*PNG|alpha/i.test(s))return'투명 PNG가 아닙니다. 배경 제거 후 다시 시도해주세요.';if(/파일.*용량|FILE_TOO_LARGE|150MB|content length/i.test(s))return'파일 용량이 너무 큽니다. 150MB 이하 이미지로 다시 시도해주세요.';if(/해상도|DPI|PPI/i.test(s))return'출력 해상도가 부족합니다. 더 큰 원본 이미지를 사용하거나 제작 크기를 줄여주세요.';if(/slot|슬롯|공차/i.test(s))return'끼움 규격을 확인해주세요. 아크릴 두께와 슬롯 폭/공차를 입력한 뒤 다시 생성하세요.';return s||'처리하지 못했습니다. 입력값과 파일을 확인한 뒤 다시 시도해주세요.';}
  global.addEventListener('unhandledrejection',e=>{if(e.reason)toast(actionError(e.reason),'error');});

  // 28 upload pre-validation
  const origAdd=UploadStore.add.bind(UploadStore);UploadStore.add=async function(file){
    if(!file)throw new Error('이미지 파일을 선택해주세요.');
    const okTypes=['image/png','image/jpeg','image/tiff','image/webp'];if(file.type&&!okTypes.includes(file.type))throw new Error('PNG, JPG, TIFF, WEBP 이미지만 업로드할 수 있습니다.');
    if(file.size>150*1024*1024)throw new Error('파일 용량은 150MB 이하여야 합니다.');
    const asset=await origAdd(file);if(!asset.originalWidth||!asset.originalHeight){this.remove(asset.id);throw new Error('손상되었거나 읽을 수 없는 이미지입니다. 다른 파일로 다시 시도해주세요.');}return asset;
  };


  // 25 Customer proof approval flow
  $('btn-create-approval-link')?.addEventListener('click',async()=>{
    const job=global.currentDongleJob;
    if(!job?.job_id){toast('먼저 제작 작업을 시작해주세요.','error');return;}
    try{
      showProgress('고객 확인 링크를 만들고 있습니다.');
      const payload={order_number:$('export-order-number')?.value||'',customer_name:$('export-customer')?.value||'',memo:$('export-memo')?.value||''};
      const r=await originalFetch(`/api/jobs/${job.job_id}/approval`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const data=await r.json();if(!r.ok)throw new Error(data.error||'승인 링크 생성 실패');
      const full=`${location.origin}${data.url}`;const box=$('approval-link-box');box.textContent=full;box.classList.remove('hidden');
      try{await navigator.clipboard.writeText(full);toast('고객 승인 링크를 생성하고 복사했습니다.','success');}catch{toast('고객 승인 링크를 생성했습니다.','success');}
    }catch(err){toast(actionError(err),'error');}finally{hideProgress();}
  });

  // 29 accessibility
  qsa('button').forEach(b=>{if(!b.getAttribute('aria-label')&&!b.textContent.trim()){const title=b.getAttribute('title');if(title)b.setAttribute('aria-label',title);}});
  qsa('input[type="color"]').forEach(i=>{if(!i.getAttribute('aria-label'))i.setAttribute('aria-label',i.id.replace(/-/g,' '));});

  // 30 DPI 표기 통일 (라벨 한글화는 index.html에서 직접 처리 — v2.1: 전역 qsa('*') 치환 제거)
  qsa('#production-summary-dpi,#footer-recommended-dpi').forEach(e=>{e.textContent=(e.textContent||'').replace(/ppi/ig,'DPI').replace(/dpi/ig,'DPI');});

  // Text options baseline hardening (font size/weight/line-height/letter spacing)
  addTextOptions();

  // periodic UI sync
  setInterval(()=>{refreshEmpty();refreshPrecision();checkPartGap();updateMergeStatus();enhanceStatusBadges();},800);
  lucide?.createIcons();

  function addTextOptions(){
    const card=qs('.object-properties-card');if(!card||$('text-typography-options'))return;
    const box=document.createElement('div');box.id='text-typography-options';box.className='text-typography-options hidden';
    box.innerHTML='<div class="typography-grid"><label>크기<input id="text-font-size" type="number" min="6" max="400" step="1"></label><label>굵기<select id="text-font-weight"><option value="400">보통</option><option value="500">중간</option><option value="600">세미볼드</option><option value="700">볼드</option><option value="800">엑스트라볼드</option></select></label><label>행간<input id="text-line-height" type="number" min="0.6" max="3" step="0.05"></label><label>자간<input id="text-letter-spacing" type="number" min="-200" max="1000" step="5"></label></div>';
    const sel=$('obj-font-family');sel?.after(box);
    const apply=()=>{const o=active();if(!o||!['i-text','textbox','text'].includes(o.type))return;o.set({fontSize:Number($('text-font-size').value)||o.fontSize,fontWeight:Number($('text-font-weight').value)||400,lineHeight:Number($('text-line-height').value)||1.16,charSpacing:Number($('text-letter-spacing').value)||0});canvas.requestRenderAll();mgr.saveHistory('텍스트 서식');};
    qsa('input,select',box).forEach(e=>e.addEventListener('change',apply));
    function sync(){const o=active(),isText=o&&['i-text','textbox','text'].includes(o.type);box.classList.toggle('hidden',!isText);if(isText){$('text-font-size').value=Math.round(o.fontSize||32);$('text-font-weight').value=String(o.fontWeight||400);$('text-line-height').value=o.lineHeight||1.16;$('text-letter-spacing').value=o.charSpacing||0;}}
    ['selection:created','selection:updated','selection:cleared'].forEach(ev=>canvas.on(ev,sync));sync();
  }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',waitForApp);else waitForApp();
})(window);
