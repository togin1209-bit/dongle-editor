class CanvasManager {
  constructor(canvasId){
    this.canvas=new fabric.Canvas(canvasId,{preserveObjectStacking:true,selection:true,backgroundColor:'#fff'});
    this.productSpecs={id:'indoor_banner',widthMm:600,heightMm:1800,bleedMm:3,safeMm:15,eyelet:{enabled:false}};
    this.maxDisplayW=780;this.maxDisplayH=720;this.zoom=1;this.guideVisibility={trim:true,safe:true,bleed:true,eyelet:true};this.snapEnabled=true;
    this.history=[];this.historyIndex=-1;this.historyMeta=[];this._restoring=false;this._eyelets=[];this._clipboard=null;
    this._setupCustomSelectionControls();this._bindHistory();this._bindSnap();this.updateCanvasDimensions();this.saveHistory();
  }
  _setupCustomSelectionControls(){
    fabric.Object.prototype.transparentCorners=false;fabric.Object.prototype.cornerColor='#fff';fabric.Object.prototype.cornerStrokeColor='#16A05D';fabric.Object.prototype.borderColor='#16A05D';fabric.Object.prototype.cornerStyle='circle';fabric.Object.prototype.cornerSize=11;fabric.Object.prototype.borderScaleFactor=1.3;fabric.Object.prototype.padding=2;
  }
  setHandleSize(n){fabric.Object.prototype.cornerSize=Math.max(7,Math.min(18,Number(n)||11));this.canvas.requestRenderAll();}
  _bindHistory(){['object:added','object:modified','object:removed'].forEach(ev=>this.canvas.on(ev,e=>{if(!e.target?.isGuide&&!e.target?.productionPreviewType)this.saveHistory();}));}
  _bindSnap(){this.canvas.on('object:moving',e=>{if(!this.snapEnabled||e.target?.isGuide)return;const o=e.target,t=7,cx=this.canvas.width/2,cy=this.canvas.height/2;const w=o.getScaledWidth(),h=o.getScaledHeight();if(Math.abs((o.left+w/2)-cx)<t)o.left=cx-w/2;if(Math.abs((o.top+h/2)-cy)<t)o.top=cy-h/2;if(Math.abs(o.left)<t)o.left=0;if(Math.abs(o.top)<t)o.top=0;if(Math.abs(o.left+w-this.canvas.width)<t)o.left=this.canvas.width-w;if(Math.abs(o.top+h-this.canvas.height)<t)o.top=this.canvas.height-h;});}
  saveHistory(description='작업 변경'){if(this._restoring)return;const json=JSON.stringify(this.canvas.toDatalessJSON(['name','data']));if(this.history[this.historyIndex]===json)return;this.history=this.history.slice(0,this.historyIndex+1);this.historyMeta=this.historyMeta.slice(0,this.historyIndex+1);this.history.push(json);this.historyMeta.push({description,timestamp:new Date().toISOString()});if(this.history.length>60){this.history.shift();this.historyMeta.shift();}this.historyIndex=this.history.length-1;}
  _loadHistory(i){if(i<0||i>=this.history.length)return;this._restoring=true;this.canvas.loadFromJSON(this.history[i],()=>{this._restoring=false;this.historyIndex=i;this.renderGuideLines();this.canvas.requestRenderAll();/* v1.9.8: Undo/Redo 후 아크릴 Production Group(칼선·탭·슬롯) 관계 복원 (#20) */if(window.AcrylicSync&&window.AcrylicSync.rehydrate)window.AcrylicSync.rehydrate(this);if(window.KeyringSync&&window.KeyringSync.rehydrate)window.KeyringSync.rehydrate(this);});}
  undo(){this._loadHistory(this.historyIndex-1);} redo(){this._loadHistory(this.historyIndex+1);}
  toggleSnap(){this.snapEnabled=!this.snapEnabled;return this.snapEnabled;}
  setProduct(spec){this.productSpecs={...this.productSpecs,...spec};this.updateCanvasDimensions();}
  updateCanvasDimensions(){
    const wmm=Number(this.productSpecs.widthMm)||600,hmm=Number(this.productSpecs.heightMm)||600;const ratio=wmm/hmm;
    let w=this.maxDisplayW,h=w/ratio;if(h>this.maxDisplayH){h=this.maxDisplayH;w=h*ratio;}
    this.canvas.setWidth(Math.max(160,Math.round(w)));this.canvas.setHeight(Math.max(160,Math.round(h)));
    const wrapper=document.getElementById('canvas-wrapper');if(wrapper){wrapper.style.width=`${this.canvas.width}px`;wrapper.style.height=`${this.canvas.height}px`;}
    this.renderGuideLines();
  }
  setEyelets(points){this._eyelets=points||[];this.renderGuideLines();}
  _addGuide(o,type){o.set({isGuide:true,guideType:type,selectable:false,evented:false,excludeFromExport:true});this.canvas.add(o);o.moveTo(0);}
  renderGuideLines(){
    this.canvas.getObjects().filter(o=>o.isGuide).forEach(g=>this.canvas.remove(g));
    const wmm=Number(this.productSpecs.widthMm)||1,hmm=Number(this.productSpecs.heightMm)||1;
    const isRound=['button','fabric_button'].includes(this.productSpecs.id);
    if(this.guideVisibility.trim){if(isRound){const r=Math.min(this.canvas.width,this.canvas.height)/2-2;this._addGuide(new fabric.Circle({left:this.canvas.width/2-r,top:this.canvas.height/2-r,radius:r,fill:'transparent',stroke:'#ef4444',strokeWidth:1.4,strokeDashArray:[7,4]}),'trim');}else this._addGuide(new fabric.Rect({left:2,top:2,width:this.canvas.width-4,height:this.canvas.height-4,fill:'transparent',stroke:'#ef4444',strokeWidth:1.6,strokeUniform:true,strokeDashArray:[7,4]}),'trim');}
    const safe=Number(this.productSpecs.safeMm)||0;if(this.guideVisibility.safe&&safe>0){const sx=safe/wmm*this.canvas.width,sy=safe/hmm*this.canvas.height;if(isRound){const r=Math.min(this.canvas.width/2-sx,this.canvas.height/2-sy);this._addGuide(new fabric.Circle({left:this.canvas.width/2-r,top:this.canvas.height/2-r,radius:Math.max(1,r),fill:'transparent',stroke:'#10b981',strokeWidth:1.2,strokeDashArray:[5,4]}),'safe');}else this._addGuide(new fabric.Rect({left:sx,top:sy,width:Math.max(1,this.canvas.width-2*sx),height:Math.max(1,this.canvas.height-2*sy),fill:'transparent',stroke:'#10b981',strokeWidth:1.4,strokeUniform:true,strokeDashArray:[5,4]}),'safe');}
    if(this.guideVisibility.eyelet&&this._eyelets.length){this._eyelets.forEach(p=>{const x=p.x_mm/wmm*this.canvas.width,y=p.y_mm/hmm*this.canvas.height;this._addGuide(new fabric.Circle({left:x-4,top:y-4,radius:4,fill:'rgba(59,130,246,.12)',stroke:'#3b82f6',strokeWidth:1.5}),'eyelet');});}
    this.canvas.requestRenderAll();
  }
  toggleGuide(type){this.guideVisibility[type]=!this.guideVisibility[type];this.renderGuideLines();return this.guideVisibility[type];}
  toggleGuides(){const on=Object.values(this.guideVisibility).some(Boolean);Object.keys(this.guideVisibility).forEach(k=>this.guideVisibility[k]=!on);this.renderGuideLines();return !on;}
  addText(textStr,options={}){const t=new fabric.IText(textStr,{left:40,top:40,fontSize:options.fontSize||32,fill:'#111827',fontFamily:options.fontFamily||'Pretendard',name:'텍스트'});this.canvas.add(t);this.canvas.setActiveObject(t);this.canvas.requestRenderAll();return t;}
  addShape(type,opts={}){
    let s;const base={left:50,top:50,fill:opts.fill||'#16A05D',stroke:'transparent',strokeWidth:0,name:'도형'};
    if(type==='rect')s=new fabric.Rect({...base,width:120,height:80,rx:8,ry:8});
    else if(type==='circle')s=new fabric.Circle({...base,radius:50});
    else if(type==='triangle')s=new fabric.Triangle({...base,width:100,height:100});
    else if(type==='star')s=new fabric.Polygon([{x:50,y:0},{x:63,y:35},{x:100,y:35},{x:70,y:57},{x:82,y:91},{x:50,y:70},{x:18,y:91},{x:30,y:57},{x:0,y:35},{x:37,y:35}],{...base});
    else if(type==='heart')s=new fabric.Path('M 50 90 C 20 65 0 45 0 25 C 0 5 25 -5 50 20 C 75 -5 100 5 100 25 C 100 45 80 65 50 90 z',{...base});
    else if(type==='line')s=new fabric.Line([0,0,140,0],{left:50,top:60,stroke:opts.fill||'#16A05D',strokeWidth:4,name:'선'});
    else s=new fabric.Rect({...base,width:100,height:100});
    this.canvas.add(s);this.canvas.setActiveObject(s);this.canvas.requestRenderAll();return s;
  }
  addImageFile(file){return new Promise(res=>{const r=new FileReader();r.onload=e=>fabric.Image.fromURL(e.target.result,img=>{const maxW=this.canvas.width*.75,maxH=this.canvas.height*.75;const scale=Math.min(maxW/img.width,maxH/img.height,1);img.set({left:(this.canvas.width-img.width*scale)/2,top:(this.canvas.height-img.height*scale)/2,scaleX:scale,scaleY:scale,name:file.name||'이미지'});this.canvas.add(img);this.canvas.setActiveObject(img);this.canvas.requestRenderAll();res(img);});r.readAsDataURL(file);});}
  replaceActiveImage(blob){const old=this.canvas.getActiveObject();if(old&&!old.isGuide)this.canvas.remove(old);return this.addImageFile(new File([blob],'removed_bg.png',{type:'image/png'}));}
  // v1.9.8: 이미 로드된 Upload Store 자산(src dataURL)에서 이미지 추가 + assetId 태깅 (중복 read 방지)
  addImageFromAsset(asset){return new Promise((resolve,reject)=>{let done=false;const timer=setTimeout(()=>{if(!done){done=true;reject(new Error('이미지 디코딩 시간이 초과되었습니다. 다른 PNG/JPG로 다시 시도해 주세요.'));}},10000);try{fabric.Image.fromURL(asset.src,img=>{if(done)return;clearTimeout(timer);if(!img||!img.width||!img.height){done=true;reject(new Error('이미지를 해석하지 못했습니다.'));return;}const maxW=this.canvas.width*.75,maxH=this.canvas.height*.75;const scale=Math.min(maxW/img.width,maxH/img.height,1);img.set({left:(this.canvas.width-img.width*scale)/2,top:(this.canvas.height-img.height*scale)/2,scaleX:scale,scaleY:scale,name:(asset.file&&asset.file.name)||'이미지'});img.data=Object.assign({},img.data,{assetId:asset.id,productionRole:'design'});this.canvas.add(img);this.canvas.setActiveObject(img);img.setCoords();this.canvas.requestRenderAll();done=true;resolve(img);});}catch(err){clearTimeout(timer);done=true;reject(err);}});}
  activeObject(){return this.canvas.getActiveObject();}
  deleteSelected(){this.canvas.getActiveObjects().forEach(o=>{if(!o.isGuide)this.canvas.remove(o);});this.canvas.discardActiveObject();this.canvas.requestRenderAll();}
  centerSelected(){const o=this.activeObject();if(o&&!o.isGuide){o.set({left:(this.canvas.width-o.getScaledWidth())/2,top:(this.canvas.height-o.getScaledHeight())/2});o.setCoords();this.canvas.requestRenderAll();this.saveHistory();}}
  setZoom(z){this.zoom=Math.min(2,Math.max(.35,z));const w=document.getElementById('canvas-wrapper');if(w)w.style.transform=`scale(${this.zoom})`;return this.zoom;}
  // v2.1.3: 키링 모양(원형/사각형/하트형/자유형) 칼선 가이드 — 클릭 시 외곽 모양을 캔버스에 표시
  setKeyringShape(shape){
    this.clearProductionPreview('keyringShape');
    if(shape==='free'){this.canvas.requestRenderAll();return null;}
    const w=this.canvas.width,h=this.canvas.height,cx=w/2,cy=h/2,m=Math.min(w,h)*0.34;
    const common={fill:'transparent',stroke:'#ec4899',strokeWidth:2,strokeDashArray:[7,4],strokeUniform:true,selectable:false,evented:false,excludeFromExport:true,objectCaching:false,productionPreviewType:'keyringShape',name:'키링 칼선'};
    let o=null;
    if(shape==='circle')o=new fabric.Circle({left:cx-m,top:cy-m,radius:m,...common});
    else if(shape==='rect')o=new fabric.Rect({left:cx-m,top:cy-m*1.2,width:2*m,height:2.4*m,rx:m*0.16,ry:m*0.16,...common});
    else if(shape==='heart'){const s=(2*m)/100;o=new fabric.Path('M 50 90 C 20 65 0 45 0 25 C 0 5 25 -5 50 20 C 75 -5 100 5 100 25 C 100 45 80 65 50 90 z',{left:cx-m,top:cy-m*0.9,scaleX:s,scaleY:s,...common});}
    if(o){this.canvas.add(o);o.bringToFront();this.canvas.requestRenderAll();}
    return o;
  }
  clearProductionPreview(type='acrylicCutPreview'){this.canvas.getObjects().filter(o=>o.productionPreviewType===type).forEach(o=>this.canvas.remove(o));this.canvas.requestRenderAll();}
  renderAcrylicContour(pointsPx, sourceW, sourceH){
    this.clearProductionPreview('acrylicCutPreview');
    const images=this.canvas.getObjects().filter(o=>o.type==='image'&&!o.isGuide);
    const img=[...images].reverse().find(Boolean);if(!img||!pointsPx?.length)return null;
    const matrix=img.calcTransformMatrix();
    const pts=pointsPx.map(p=>{
      const local=new fabric.Point((p[0]/sourceW)*img.width-img.width/2,(p[1]/sourceH)*img.height-img.height/2);
      const world=fabric.util.transformPoint(local,matrix);return {x:world.x,y:world.y};
    });
    const poly=new fabric.Polyline(pts,{fill:'transparent',stroke:'#ec4899',strokeWidth:2,strokeDashArray:[7,4],selectable:false,evented:false,objectCaching:false,excludeFromExport:true,productionPreviewType:'acrylicCutPreview',name:'CUT Preview'});
    this.canvas.add(poly);poly.bringToFront();this.canvas.requestRenderAll();return poly;
  }
  renderStandAssembly(pointsPx, sourceW, sourceH, opts={}){
    this.clearProductionPreview('standAssemblyPreview');
    const images=this.canvas.getObjects().filter(o=>o.type==='image'&&!o.isGuide);
    const img=[...images].reverse().find(Boolean);if(!img||!pointsPx?.length)return null;
    const matrix=img.calcTransformMatrix();
    const pts=pointsPx.map(p=>{const local=new fabric.Point((p[0]/sourceW)*img.width-img.width/2,(p[1]/sourceH)*img.height-img.height/2);const world=fabric.util.transformPoint(local,matrix);return {x:world.x,y:world.y};});
    const xs=pts.map(p=>p.x),ys=pts.map(p=>p.y),minX=Math.min(...xs),maxX=Math.max(...xs),maxY=Math.max(...ys);
    const pxPerMm=this.canvas.width/(Number(this.productSpecs.widthMm)||100);
    const tabW=Math.max(18,Number(opts.tabWidthMm||20)*pxPerMm),tabH=Math.max(10,Number(opts.tabHeightMm||8)*pxPerMm);
    const tab=new fabric.Rect({left:(minX+maxX-tabW)/2,top:maxY-2,width:tabW,height:tabH,fill:'rgba(236,72,153,.08)',stroke:'#ec4899',strokeWidth:2,rx:3,ry:3,selectable:false,evented:false,excludeFromExport:true,productionPreviewType:'standAssemblyPreview',name:'Stand Tab Preview'});
    const baseW=Math.min(this.canvas.width*.78,Math.max(150,Number(opts.baseWidthMm||100)*pxPerMm)),baseH=Math.max(55,Number(opts.baseDepthMm||40)*pxPerMm*.55);
    const baseTop=Math.min(this.canvas.height-baseH-12,maxY+tabH+28);const baseLeft=(this.canvas.width-baseW)/2;
    const base=new fabric.Rect({left:baseLeft,top:baseTop,width:baseW,height:baseH,fill:'rgba(148,163,184,.08)',stroke:'#f97316',strokeWidth:1.5,rx:12,ry:12,selectable:false,evented:false,excludeFromExport:true,productionPreviewType:'standAssemblyPreview',name:'Base Preview'});
    const slotW=Math.max(24,Number(opts.slotWidthMm||20)*pxPerMm),slotH=Math.max(8,Number(opts.materialThicknessMm||3)*pxPerMm);
    const slot=new fabric.Rect({left:(this.canvas.width-slotW)/2,top:baseTop+(baseH-slotH)/2,width:slotW,height:slotH,fill:'rgba(255,255,255,.75)',stroke:'#ef4444',strokeWidth:2,rx:slotH/2,ry:slotH/2,lockScalingY:true,lockRotation:true,hasRotatingPoint:false,excludeFromExport:true,productionPreviewType:'standAssemblyPreview',name:'받침대 슬롯 · 드래그하여 위치 조정'});
    slot.on('moving',()=>{slot.set({left:Math.max(baseLeft,Math.min(baseLeft+baseW-slotW,slot.left)),top:Math.max(baseTop,Math.min(baseTop+baseH-slotH,slot.top))});});
    this.canvas.add(tab,base,slot);base.sendToBack();tab.bringToFront();slot.bringToFront();this.canvas.setActiveObject(slot);this.canvas.requestRenderAll();return {tab,base,slot};
  }
  layers(){return this.canvas.getObjects().filter(o=>!o.isGuide).map((o,i)=>({obj:o,index:i,name:o.name||(o.type==='image'?'이미지':o.text||o.type)})).reverse();}
  protectedElementsMm(){const wmm=this.productSpecs.widthMm,hmm=this.productSpecs.heightMm;return this.canvas.getObjects().filter(o=>!o.isGuide&&(o.type==='i-text'||o.type==='textbox')).map((o,i)=>{const b=o.getBoundingRect(true,true);return {name:o.text||`text-${i+1}`,x_mm:b.left/this.canvas.width*wmm,y_mm:b.top/this.canvas.height*hmm,width_mm:b.width/this.canvas.width*wmm,height_mm:b.height/this.canvas.height*hmm};});}
  applyShapeStyle(style){const o=this.activeObject();if(!o||o.isGuide)return;if(style.fill)o.set('fill',style.fill);if(style.stroke!==undefined)o.set('stroke',style.stroke);if(style.strokeWidth!==undefined)o.set('strokeWidth',Number(style.strokeWidth));if(style.opacity!==undefined)o.set('opacity',Number(style.opacity));if(style.shadowBlur!==undefined)o.set('shadow',Number(style.shadowBlur)>0?new fabric.Shadow({color:'rgba(0,0,0,.35)',blur:Number(style.shadowBlur),offsetX:4,offsetY:4}):null);if(style.gradient){o.set('fill',new fabric.Gradient({type:'linear',coords:{x1:0,y1:0,x2:o.width||100,y2:o.height||100},colorStops:[{offset:0,color:style.gradient[0]},{offset:1,color:style.gradient[1]}]}));}this.canvas.requestRenderAll();this.saveHistory();}
  flip(axis){const o=this.activeObject();if(!o)return;o.set(axis==='x'?{flipX:!o.flipX}:{flipY:!o.flipY});this.canvas.requestRenderAll();this.saveHistory();}

  // v1.7 Professional Editing helpers (additive)
  async copySelected(){
    const o=this.activeObject(); if(!o||o.isGuide)return false;
    this._clipboard=await new Promise(resolve=>o.clone(resolve,['name'])); return true;
  }
  async pasteClipboard(){
    if(!this._clipboard)return false;
    const clone=await new Promise(resolve=>this._clipboard.clone(resolve,['name']));
    clone.set({left:(clone.left||0)+16,top:(clone.top||0)+16,evented:true});
    if(clone.type==='activeSelection'){clone.canvas=this.canvas;clone.forEachObject(obj=>this.canvas.add(obj));clone.setCoords();}
    else this.canvas.add(clone);
    this.canvas.setActiveObject(clone);this.canvas.requestRenderAll();this.saveHistory('붙여넣기');return true;
  }
  async cutSelected(){if(await this.copySelected()){this.deleteSelected();this.saveHistory('잘라내기');return true;}return false;}
  async duplicateSelected(){if(await this.copySelected())return this.pasteClipboard();return false;}
  selectAll(){const objs=this.canvas.getObjects().filter(o=>!o.isGuide&&!o.productionPreviewType&&o.selectable!==false);if(!objs.length)return false;this.canvas.discardActiveObject();this.canvas.setActiveObject(new fabric.ActiveSelection(objs,{canvas:this.canvas}));this.canvas.requestRenderAll();return true;}
  deselect(){this.canvas.discardActiveObject();this.canvas.requestRenderAll();}
  moveSelection(dx,dy){const o=this.activeObject();if(!o||o.isGuide)return false;o.set({left:(o.left||0)+dx,top:(o.top||0)+dy});o.setCoords();this.canvas.requestRenderAll();this.saveHistory('객체 이동');return true;}
  bringForward(){const o=this.activeObject();if(o&&!o.isGuide){this.canvas.bringForward(o);this.canvas.requestRenderAll();this.saveHistory('레이어 앞으로');}}
  sendBackward(){const o=this.activeObject();if(o&&!o.isGuide){this.canvas.sendBackwards(o);this.renderGuideLines();this.canvas.requestRenderAll();this.saveHistory('레이어 뒤로');}}
  bringToFront(){const o=this.activeObject();if(o&&!o.isGuide){o.bringToFront();this.canvas.requestRenderAll();this.saveHistory('맨 앞으로');}}
  sendToBack(){const o=this.activeObject();if(o&&!o.isGuide){o.sendToBack();this.renderGuideLines();this.canvas.requestRenderAll();this.saveHistory('맨 뒤로');}}
  groupSelected(){const o=this.activeObject();if(o?.type==='activeSelection'){const g=o.toGroup();g.set({name:'그룹'});this.canvas.requestRenderAll();this.saveHistory('그룹');return true;}return false;}
  ungroupSelected(){const o=this.activeObject();if(o?.type==='group'){o.toActiveSelection();this.canvas.requestRenderAll();this.saveHistory('그룹 해제');return true;}return false;}
  toggleLock(){const o=this.activeObject();if(!o||o.isGuide)return false;const locked=!!o.lockMovementX;o.set({lockMovementX:!locked,lockMovementY:!locked,lockScalingX:!locked,lockScalingY:!locked,lockRotation:!locked});this.canvas.requestRenderAll();this.saveHistory(!locked?'잠금':'잠금 해제');return !locked;}
  fitToWorkspace(){return this.setZoom(1);}
  zoomIn(){return this.setZoom(this.zoom+0.1);}
  zoomOut(){return this.setZoom(this.zoom-0.1);}
  applyImageAdjustments(values={}){
    const o=this.activeObject();if(!o||o.type!=='image')return false;const F=fabric.Image.filters;const filters=[];
    if(values.brightness)filters.push(new F.Brightness({brightness:Number(values.brightness)}));
    if(values.contrast)filters.push(new F.Contrast({contrast:Number(values.contrast)}));
    if(values.saturation)filters.push(new F.Saturation({saturation:Number(values.saturation)}));
    if(values.blur)filters.push(new F.Blur({blur:Number(values.blur)}));
    o.filters=filters;o.applyFilters();this.canvas.requestRenderAll();this.saveHistory('이미지 조정');return true;
  }
  objectType(){const o=this.activeObject();if(!o)return 'NONE';if(o.type==='image')return 'IMAGE';if(['i-text','textbox','text'].includes(o.type))return 'TEXT';return 'SHAPE';}

  async exportBlob(){
    this.canvas.discardActiveObject();this.canvas.requestRenderAll();const guides=this.canvas.getObjects().filter(o=>o.isGuide||o.productionPreviewType);guides.forEach(g=>g.visible=false);this.canvas.requestRenderAll();
    const data=this.canvas.toDataURL({format:'png',multiplier:3,enableRetinaScaling:false});guides.forEach(g=>g.visible=true);this.canvas.requestRenderAll();return (await fetch(data)).blob();
  }
}
window.CanvasManager=CanvasManager;