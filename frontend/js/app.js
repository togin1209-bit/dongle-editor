document.addEventListener('DOMContentLoaded', async()=>{
  if(window.lucide)lucide.createIcons();const $=id=>document.getElementById(id);
  const canvasMgr=new CanvasManager('fabric-canvas');window.canvasMgr=canvasMgr;if(window.AcrylicSync)AcrylicSync.bind(canvasMgr);if(window.KeyringSync)KeyringSync.bind(canvasMgr);let products=await ProductionAPI.getProducts();let groups=(await ProductionAPI.getProductGroups()).groups;
  let currentProduct=products.indoor_banner,currentProductId='indoor_banner',currentJob=null,currentUploadFile=null,lastPreflight=null;let guideHelp={};try{const gh=await ProductionAPI.getGuideHelp();(gh.guides||[]).forEach(g=>guideHelp[g.guide_id]=g);}catch{}
  const FontRegistry={KOREAN:['Pretendard','Noto Sans KR','Noto Serif KR','Nanum Gothic','Nanum Myeongjo','Gowun Dodum','Gowun Batang'],ENGLISH:['Inter','Manrope','DM Sans','Montserrat','Poppins','Playfair Display','Libre Baskerville']};
  function toast(msg,type='info'){const e=document.createElement('div');e.className=`dongle-toast ${type}`;e.textContent=msg;document.body.appendChild(e);setTimeout(()=>e.classList.add('show'),10);setTimeout(()=>{e.classList.remove('show');setTimeout(()=>e.remove(),250)},2600);}window.dongleToast=toast;
  // v1.9.8 Upload Store SSoT: DOM/변수 대신 "현재 선택 객체의 assetId"로 원본 파일을 찾는다(#4)
  function activeAssetFile(){const s=window.UploadStore;if(!s)return currentUploadFile;const a=s.forObject(canvasMgr.activeObject())||s.active();return (a&&a.file)||currentUploadFile;}
  const keyringState={holeMode:'TOP_CENTER',innerMm:3,outerMm:7,count:1,placement:'OUTSIDE'};
  function activeArtworkImage(){return canvasMgr.canvas.getObjects().filter(o=>o.type==='image'&&!o.isGuide&&!o.productionPreviewType).slice(-1)[0]||null;}
  async function buildKeyringAssembly(file,img,{silent=false}={}){
    if(currentProductId!=='acrylic_keyring'||!file||file.type!=='image/png'||!img)return false;
    try{
      const result=await ProductionAPI.previewAcrylicContour(file,'acrylic_keyring',Number(document.getElementById('acrylic-offset-mm')?.value||1));
      if(currentProductId!=='acrylic_keyring')return false;
      window.KeyringSync?.attach({image:img,pointsPx:result.points_px,sourceW:result.source_width_px,sourceH:result.source_height_px,hole:keyringState});
      if(!silent)toast('키링 외곽 칼선과 고리를 만들었습니다.','success');
      return true;
    }catch(e){if(!silent)toast(e.message||'키링 제작에 실패했습니다.','error');return false;}
  }
  async function importImageFile(f){
    if(!f)return null;
    if(!window.ImageImportController)throw new Error('이미지 가져오기 모듈을 초기화하지 못했습니다.');
    const img=await window.ImageImportController.importFile(f,{canvasMgr});
    currentUploadFile=f;
    _productionUploadedSig=null;
    refreshLayers&&refreshLayers();
    canvasMgr.canvas.requestRenderAll();
    try{renderUploadAssets?.();}catch(_){}
    // v2.6: 키링은 화면 표시를 먼저 확정한 뒤 백그라운드에서 1mm 칼선+고리를 자동 생성한다.
    if(currentProductId==='acrylic_keyring'&&f.type==='image/png')setTimeout(()=>buildKeyringAssembly(f,img,{silent:true}),0);
    if(currentProductId==='acrylic_print'&&f.type==='image/png')setTimeout(async()=>{try{const r=await ProductionAPI.previewAcrylicContour(f,'acrylic_print',Number(document.getElementById('acrylic-offset-mm')?.value||1));canvasMgr.renderAcrylicContour(r.points_px,r.source_width_px,r.source_height_px);toast(`PNG 외곽 ${r.cutline_offset_mm}mm 칼선을 자동 적용했습니다.`,'success');}catch(e){toast(e.message||'자동 칼선 생성에 실패했습니다.','error');}},0);
    return img;
  }
  window.importDongleImage=importImageFile;
  // 제작 업로드/Preflight를 필요한 시점에만 1회 수행 (중복 방지)
  let _productionUploadedSig=null;
  async function ensureProductionUpload(){
    if(!currentProduct.productionEnabled)return true;
    const f=(typeof activeAssetFile==='function'&&activeAssetFile())||currentUploadFile;
    if(!f){toast('먼저 이미지를 가져오세요.','error');return false;}
    if(!currentJob)await newJob();
    if(!currentJob)return false;
    const sig=`${currentJob.job_id}|${f.name}|${f.size}|${f.lastModified}`;
    if(_productionUploadedSig===sig)return true; // 이미 업로드/검수 완료
    try{await ProductionAPI.upload(currentJob.job_id,f);_productionUploadedSig=sig;await runPreflight();return true;}
    catch(err){console.error('[production upload]',err);toast(err.message||'제작 업로드에 실패했습니다.','error');return false;}
  }
  function statusBadge(p){return p.productionEnabled?'<span class="status-badge status-partial">제작 가능</span>':'<span class="status-badge status-guide">검증중</span>';}
  let activeCategory='SIGNAGE',productSearch='';
  const CATEGORY_META={SIGNAGE:{label:'배너/사인',icon:'panel-top',tone:'neutral'},ACRYLIC:{label:'아크릴',icon:'key-round',tone:'neutral'},BUTTON:{label:'버튼',icon:'circle-dot',tone:'neutral'},STICKER:{label:'스티커',icon:'sticker',tone:'neutral'},LARGE_FORMAT:{label:'실사출력',icon:'scan-line',tone:'neutral'},CARD:{label:'카드/명함',icon:'contact',tone:'neutral'}};
  function renderCategoryTabs(){const c=$('product-category-tabs');if(!c)return;c.innerHTML='';const tabs=[['ALL','전체'],...groups.map(g=>[g.id,g.label])];tabs.forEach(([id,label])=>{const b=document.createElement('button');b.className=`category-tab ${activeCategory===id?'active':''}`;b.dataset.category=id;const meta=CATEGORY_META[id];b.innerHTML=`${meta?`<span class="category-dot tone-${meta.tone}"></span>`:''}<span>${label}</span>`;b.onclick=()=>{activeCategory=id;renderCategoryTabs();renderProducts();};c.appendChild(b);});}
  function renderProducts(){const c=$('taxonomy-container');c.innerHTML='';let shown=0;groups.forEach(g=>{if(!['SIGNAGE','ACRYLIC','BUTTON'].includes(g.id))return;if(activeCategory!=='ALL'&&activeCategory!==g.id)return;const candidates=g.products.filter(p=>!productSearch||`${p.name} ${p.categoryLabel||''}`.toLowerCase().includes(productSearch));if(!candidates.length)return;const sec=document.createElement('section');sec.className=`product-category-section tone-${CATEGORY_META[g.id]?.tone||'neutral'}`;const meta=CATEGORY_META[g.id]||{};sec.innerHTML=`<div class="category-heading"><div class="category-icon"><i data-lucide="${meta.icon||'grid-2x2'}"></i></div><div><strong>${g.label}</strong><span>${candidates.length}개 상품</span></div></div>`;const grid=document.createElement('div');grid.className='product-card-grid';candidates.forEach(p=>{shown++;const b=document.createElement('button');b.className=`product-card ${p.id===currentProductId?'active':''}`;b.dataset.productId=p.id;const size=(p.widthMm&&p.heightMm)?`${p.widthMm} × ${p.heightMm} mm`:(p.customSizeAllowed?'자유 사이즈':'규격 확인 필요');b.innerHTML=`<div class="product-card-top">${statusBadge(p)}<span class="product-arrow">›</span></div><span class="product-name">${p.name}</span><span class="product-size">${size}</span>`;b.onclick=()=>selectProduct(p.id);grid.appendChild(b);});sec.appendChild(grid);c.appendChild(sec);});if(!shown)c.innerHTML='<div class="catalog-empty"><b>검색 결과가 없습니다.</b><span>다른 상품명이나 카테고리를 선택해보세요.</span></div>';window.lucide?.createIcons();}
  function clearProductSpecificProductionUI(){
    try{window.AcrylicSync?.clearAll?.();}catch(e){console.warn('[acrylic cleanup]',e);}try{window.KeyringSync?.clearAll?.();}catch(e){console.warn('[keyring cleanup]',e);}
    const c=canvasMgr?.canvas;
    if(c){
      c.getObjects().filter(o=>o&&o.productionPreviewType).forEach(o=>c.remove(o));
      c.discardActiveObject();
      c.requestRenderAll();
    }
    ['acrylicCutPreview','standAssemblyPreview','keyringShape'].forEach(t=>canvasMgr?.clearProductionPreview?.(t));
  }


  async function selectProduct(id){clearProductSpecificProductionUI();currentProductId=id;currentProduct=products[id];currentJob=null;/* 업로드 이미지는 캔버스에 남으므로 상품 전환 시에도 유지 */lastPreflight=null;const preview={...currentProduct,widthMm:currentProduct.widthMm||600,heightMm:currentProduct.heightMm||600,safeMm:currentProduct.safeMm||0,bleedMm:currentProduct.bleedMm||0};canvasMgr.setProduct(preview);canvasMgr.setEyelets([]);const isButton=['button','fabric_button'].includes(currentProductId);const canResize=!!(currentProduct.productionEnabled&&currentProduct.customSizeAllowed);if($('input-placard-w')){$('input-placard-w').value=currentProduct.widthMm||'';$('input-placard-w').disabled=isButton||!canResize;}if($('input-placard-h')){$('input-placard-h').value=currentProduct.heightMm||'';$('input-placard-h').disabled=isButton||!canResize;}if($('btn-apply-placard-size'))$('btn-apply-placard-size').disabled=isButton||!canResize;if($('size-ratio-lock'))$('size-ratio-lock').disabled=!canResize;if($('size-mode-badge')){$('size-mode-badge').textContent=isButton?'고정 규격':(canResize?'자유 입력':'고정/검증 대기');$('size-mode-badge').classList.toggle('is-custom',canResize);}if($('size-panel-help'))$('size-panel-help').textContent=isButton?'32 · 44 · 58 · 75mm 중 제작 규격을 선택하세요.':(canResize?'가로·세로를 mm 단위로 입력하면 제작 규격을 다시 계산합니다.':'선택한 상품의 제작 사이즈입니다.');if($('size-restriction-note'))$('size-restriction-note').textContent=canResize?'사이즈 변경 시 기존 디자인은 새 규격에 맞춰 비례 재배치됩니다.':'※ 임의 규격으로 제작사고가 발생하지 않도록, 공식 제작가이드 검증 전에는 입력을 잠급니다.';const pc=$('size-preset-chips');if(pc){pc.innerHTML='';(currentProduct.sizePresets||[]).forEach(p=>{const b=document.createElement('button');b.className='size-preset-chip';b.textContent=p.label||`${p.width_mm}×${p.height_mm}`;b.disabled=!(canResize||isButton);b.onclick=async()=>{$('input-placard-w').value=p.width_mm;$('input-placard-h').value=p.height_mm;if(isButton){currentProduct={...currentProduct,widthMm:p.width_mm,heightMm:p.height_mm,bleedMm:(Number(p.work_mm)-Number(p.width_mm))/2};products[currentProductId]=currentProduct;canvasMgr.setProduct(currentProduct);currentJob=null;currentUploadFile=null;lastPreflight=null;updateFooter();syncTopProductBar();await newJob();document.querySelectorAll('.size-preset-chip').forEach(x=>x.classList.toggle('active',x===b));toast(`버튼 ${p.width_mm}mm 규격 적용`,'success');}else if(canResize){$('input-placard-w').value=p.width_mm;$('input-placard-h').value=p.height_mm;await applyCustomSize(p.width_mm,p.height_mm);document.querySelectorAll('.size-preset-chip').forEach(x=>x.classList.toggle('active',x===b));toast(`${p.label||`${p.width_mm}×${p.height_mm}`} 규격 적용`,'success');}};pc.appendChild(b);});if(!(currentProduct.sizePresets||[]).length){const hint=document.createElement('span');hint.className='size-preset-empty';hint.textContent=canResize?'직접 입력':'등록된 규격 없음';pc.appendChild(hint);}}if($('selected-product-card-name'))$('selected-product-card-name').textContent=currentProduct.name||id;
if($('selected-product-card-size'))$('selected-product-card-size').textContent=(currentProduct.widthMm&&currentProduct.heightMm)?`${currentProduct.widthMm} × ${currentProduct.heightMm} mm`:'자유 규격';
const presetSelect=$('size-preset-select');if(presetSelect){presetSelect.innerHTML='<option value="">직접 입력</option>';(currentProduct.sizePresets||[]).forEach((p,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=p.label||`${p.width_mm} × ${p.height_mm} mm`;presetSelect.appendChild(o);});presetSelect.disabled=!(canResize||isButton);presetSelect.onchange=async()=>{if(presetSelect.value==='')return;const p=(currentProduct.sizePresets||[])[Number(presetSelect.value)];if(!p)return;$('input-placard-w').value=p.width_mm;$('input-placard-h').value=p.height_mm;if(isButton){currentProduct={...currentProduct,widthMm:p.width_mm,heightMm:p.height_mm,bleedMm:(Number(p.work_mm)-Number(p.width_mm))/2};products[currentProductId]=currentProduct;canvasMgr.setProduct(currentProduct);updateFooter();syncTopProductBar();await newJob();}else if(canResize)await applyCustomSize(p.width_mm,p.height_mm);};}
const isAcrylic=['acrylic_print','acrylic_keyring','acrylic_stand'].includes(id);
// v291 acrylic context
if(id==='acrylic_keyring'){
  $('acrylic-production-tools')?.classList.remove('hidden');
  $('acrylic-keyring-tools')?.classList.remove('hidden');
  $('acrylic-stand-tools')?.classList.add('hidden');
  if($('acrylic-main-action-label'))$('acrylic-main-action-label').textContent='키링 제작';
}
if(id==='acrylic_stand'){
  $('acrylic-production-tools')?.classList.remove('hidden');
  $('acrylic-stand-tools')?.classList.remove('hidden');
  $('acrylic-keyring-tools')?.classList.add('hidden');
}
if(id==='acrylic_print'){
  $('acrylic-production-tools')?.classList.remove('hidden');
  $('acrylic-keyring-tools')?.classList.add('hidden');
  $('acrylic-stand-tools')?.classList.add('hidden');
  if($('acrylic-main-action-label'))$('acrylic-main-action-label').textContent='칼선 만들기';
}

$('acrylic-production-tools')?.classList.toggle('hidden',!isAcrylic);
$('acrylic-keyring-tools')?.classList.toggle('hidden',id!=='acrylic_keyring');
$('acrylic-stand-tools')?.classList.toggle('hidden',id!=='acrylic_stand');
$('acrylic-offset-control')?.classList.toggle('hidden',!['acrylic_print','acrylic_keyring'].includes(id));
const contourBtn=$('btn-acrylic-auto-contour'), contourLabel=$('acrylic-main-action-label'), contourStatus=$('acrylic-contour-status');
if(contourBtn){
  contourBtn.classList.toggle('hidden',id==='acrylic_stand');
  if(contourLabel)contourLabel.textContent=id==='acrylic_keyring'?'키링 제작':id==='acrylic_print'?'칼선 만들기':'스탠드 제작';
}
if(contourStatus){contourStatus.classList.add('hidden');contourStatus.innerHTML='';}canvasMgr.clearProductionPreview?.();renderProducts();renderRelated();renderStatus();updateFooter();syncTopProductBar();$('preflight-list-container').innerHTML=currentProduct.productionEnabled?'<div class="text-xs text-slate-500">이미지를 업로드하면 검수를 시작합니다.</div>':'<div class="pf-card-v14"><b>제작가이드 확인 필요</b><div class="text-[11px] text-slate-400 mt-1">공식 제작가이드 검증 전에는 인쇄파일 생성을 차단합니다.</div></div>';if(currentProduct.productionEnabled)await newJob();}
  async function newJob(){if(!currentProduct.productionEnabled)return null;try{currentJob=await ProductionAPI.createJob(currentProductId,currentProduct.widthMm,currentProduct.heightMm,'contain');window.currentDongleJob=currentJob;return currentJob;}catch(e){toast(e.message,'error');return null;}}
  function renderRelated(){const box=$('related-products-box');box.innerHTML='';if(!currentProduct.relatedProducts?.length)return;box.innerHTML='<div class="text-[10px] font-bold text-emerald-600 uppercase mb-1">관련 상품</div>';currentProduct.relatedProducts.forEach(id=>{const p=products[id];if(!p)return;const b=document.createElement('button');b.className='mini-btn mr-1 mb-1';b.textContent=p.name;b.onclick=()=>selectProduct(id);box.appendChild(b);});}
  function renderStatus(){const p=currentProduct;$('product-status-card').innerHTML=`<div class="flex justify-between"><b>${p.name}</b>${statusBadge(p)}</div><div class="text-[11px] text-slate-400 mt-2">${p.productionEnabled?'제작파일 생성 가능 · 적용된 제작 규격을 확인하세요':'상품 등록 완료 · 제작가이드 검증 후 출력 가능'}</div><div class="text-[10px] text-slate-500 mt-2">Capabilities: ${(p.capabilities||[]).join(', ')||'-'}</div>`;}
  function updateFooter(){
    const finished=(currentProduct.widthMm&&currentProduct.heightMm)?`${currentProduct.widthMm}×${currentProduct.heightMm}`:'-';
    if($('footer-product-name'))$('footer-product-name').textContent=currentProduct?.name||'상품';
    if($('footer-trim-size'))$('footer-trim-size').textContent=finished;
    if($('footer-working-size'))$('footer-working-size').textContent=workingSizeForProduct(currentProduct).replace(' mm','').replace(' × ','×');
    if($('footer-recommended-dpi'))$('footer-recommended-dpi').textContent=`${recommendedDpiForProduct(currentProduct)} DPI`;
  }
  function workingSizeForProduct(p){const w=Number(p?.widthMm||0),h=Number(p?.heightMm||0),b=Number(p?.bleedMm||0);return w&&h?`${Math.round((w+b*2)*100)/100} × ${Math.round((h+b*2)*100)/100} mm`:'규격 확인 필요';}
  function recommendedDpiForProduct(p){return p?.recommendedDpi||p?.recommendedDpiMin||p?.recommended_dpi||((currentProductId==='hyeonsumak_outdoor'||currentProductId==='hyeonsumak')?150:300);}
  function syncTopProductBar(){if(!currentProduct)return;const canResize=!!(currentProduct.productionEnabled&&currentProduct.customSizeAllowed);if($('top-product-name'))$('top-product-name').textContent=currentProduct.name;if($('top-product-status')){$('top-product-status').textContent=currentProduct.productionEnabled?'제작 가능':'검증중';$('top-product-status').className=`top-status-badge ${currentProduct.productionEnabled?'ready':'wait'}`;}if($('top-size-w')){$('top-size-w').value=currentProduct.widthMm||'';$('top-size-w').disabled=!canResize;}if($('top-size-h')){$('top-size-h').value=currentProduct.heightMm||'';$('top-size-h').disabled=!canResize;}if($('top-size-apply'))$('top-size-apply').disabled=!canResize;if($('top-working-size'))$('top-working-size').textContent=workingSizeForProduct(currentProduct);if($('top-recommended-dpi'))$('top-recommended-dpi').textContent=`${recommendedDpiForProduct(currentProduct)} dpi`;if($('production-summary-name'))$('production-summary-name').textContent=currentProduct.name;if($('production-summary-badge')){$('production-summary-badge').textContent=currentProduct.productionEnabled?'제작 가능':'검증중';$('production-summary-badge').className=currentProduct.productionEnabled?'summary-ready':'top-status-badge wait';}if($('production-summary-finished'))$('production-summary-finished').textContent=(currentProduct.widthMm&&currentProduct.heightMm)?`${currentProduct.widthMm} × ${currentProduct.heightMm} mm`:'규격 확인 필요';if($('production-summary-working'))$('production-summary-working').textContent=workingSizeForProduct(currentProduct);if($('production-summary-dpi'))$('production-summary-dpi').textContent=`${recommendedDpiForProduct(currentProduct)} dpi`;}
  renderProducts();
  document.querySelectorAll('.nav-btn').forEach(btn=>btn.addEventListener('click',()=>{const p=btn.dataset.panel;if(!p)return;document.querySelectorAll('.nav-btn').forEach(b=>b.classList.toggle('active',b===btn));document.querySelectorAll('[id^="panel-content-"]').forEach(el=>el.classList.add('hidden'));$(`panel-content-${p}`)?.classList.remove('hidden');}));
  const textPanelFont=$('text-panel-font-family');
  if(textPanelFont){
    textPanelFont.innerHTML='<optgroup label="한글">'+FontRegistry.KOREAN.map(x=>`<option>${x}</option>`).join('')+'</optgroup><optgroup label="영문">'+FontRegistry.ENGLISH.map(x=>`<option>${x}</option>`).join('')+'</optgroup>';
    textPanelFont.value='Pretendard';
  }
  const textPresetMap={
    title:{text:'제목 텍스트',fontSize:42,fontWeight:700},
    subtitle:{text:'부제목 텍스트',fontSize:28,fontWeight:600},
    body:{text:'본문 텍스트',fontSize:18,fontWeight:400}
  };
  $('selected-product-more')?.addEventListener('click',()=>{$('taxonomy-container')?.scrollIntoView({behavior:'smooth',block:'start'});});
  document.querySelectorAll('[data-text-preset]').forEach(btn=>btn.addEventListener('click',()=>{
    const p=textPresetMap[btn.dataset.textPreset]||textPresetMap.body;
    const o=canvasMgr.addText(p.text,{fontSize:p.fontSize,fontFamily:textPanelFont?.value||'Pretendard'});
    o?.set?.({fontWeight:p.fontWeight});
    canvasMgr.canvas.requestRenderAll();
    canvasMgr.saveHistory?.('텍스트 추가');
    refreshInspector();refreshLayers();
  }));
  const fontSamples=$('text-font-sample-grid');
  if(fontSamples){
    ['Pretendard','Noto Sans KR','Nanum Gothic','Nanum Myeongjo','Arial','Georgia'].forEach(name=>{
      const b=document.createElement('button');b.type='button';b.className='font-sample-card';b.style.fontFamily=name;
      b.innerHTML=`<strong>${name==='Georgia'?'Aa':'가나다'}</strong><span>${name}</span>`;
      b.onclick=()=>{if(textPanelFont)textPanelFont.value=name;const o=canvasMgr.activeObject();if(o&&['i-text','textbox','text'].includes(o.type)){o.set('fontFamily',name);canvasMgr.canvas.requestRenderAll();canvasMgr.saveHistory?.('폰트 변경');}};
      fontSamples.appendChild(b);
    });
  }
document.querySelectorAll('.add-elem-btn').forEach(b=>b.onclick=()=>{canvasMgr.addShape(b.dataset.element);refreshInspector();refreshLayers();});
  function renderUploadAssets(){
    const grid=$('upload-assets-grid');if(!grid||!window.UploadStore)return;
    const assets=Object.values(UploadStore.state.items||{});grid.innerHTML='';
    if(!assets.length){grid.innerHTML='<div class="upload-empty">불러온 이미지가 여기에 표시됩니다.</div>';return;}
    assets.slice().reverse().forEach(asset=>{
      const b=document.createElement('button');b.type='button';b.className='upload-asset-card';b.title=asset.file?.name||'이미지';
      b.innerHTML=`<img src="${asset.src}" alt=""><span>${(asset.file?.name||'이미지').replace(/</g,'&lt;')}</span>`;
      b.onclick=async()=>{try{const img=await canvasMgr.addImageFromAsset(asset);UploadStore.setActive(asset.id);currentUploadFile=asset.file;refreshLayers();canvasMgr.canvas.requestRenderAll();toast('이미지를 캔버스에 추가했습니다.','success');if(currentProductId==='acrylic_keyring'&&asset.file?.type==='image/png')setTimeout(()=>buildKeyringAssembly(asset.file,img,{silent:true}),0);}catch(e){toast(e.message,'error');}};
      grid.appendChild(b);
    });
  }
  const uploadPanel=$('panel-content-upload');uploadPanel.innerHTML='<div class="library-panel-head"><strong>업로드</strong><span>내 이미지</span></div><div class="upload-panel-card"><button id="btn-choose-upload" class="upload-primary-btn">+ 이미지 가져오기</button><input id="file-upload" type="file" accept="image/png,image/jpeg,image/webp" hidden><div class="upload-format-note">PNG · JPG · WEBP</div></div><div class="upload-assets-grid" id="upload-assets-grid"></div>';const fileInput=$('file-upload');$('btn-choose-upload').onclick=()=>fileInput.click();fileInput.onchange=async e=>{const f=e.target.files[0];if(!f)return;try{await importImageFile(f);renderUploadAssets();toast('이미지를 캔버스에 추가했습니다.','success');}catch(err){console.error('[image import]',err);toast(err.message||'이미지를 불러오지 못했습니다.','error');}finally{e.target.value='';}};renderUploadAssets();
  async function runPreflight(){if(!currentUploadFile||!currentJob)return;try{lastPreflight=await ProductionAPI.preflight(currentJob.job_id,{fit_policy:'contain',protected_elements:canvasMgr.protectedElementsMm()});PreflightEngine.render(lastPreflight,$('preflight-list-container'),()=>{});canvasMgr.setEyelets(lastPreflight.eyelets||[]);}catch(e){toast(e.message,'error');}}
  $('btn-ai-remove-bg')?.addEventListener('click',async()=>{if(!currentUploadFile||!currentJob){toast('Production 가능 상품에서 이미지를 먼저 업로드하세요.','error');return;}try{const blob=await ProductionAPI.removeBackground(currentJob.job_id,currentUploadFile);const newFile=new File([blob],'removed_bg.png',{type:'image/png'});currentUploadFile=newFile;await canvasMgr.replaceActiveImage(blob);currentJob=await ProductionAPI.createJob(currentProductId,currentProduct.widthMm,currentProduct.heightMm,'contain');await ProductionAPI.upload(currentJob.job_id,newFile);toast('AI 배경 제거 완료','success');await runPreflight();refreshLayers();}catch(e){toast(e.message,'error');}});
  // v1.8 dynamic product size
  $('btn-apply-placard-size')?.addEventListener('click',async()=>{if(!(currentProduct.productionEnabled&&currentProduct.customSizeAllowed)){toast('현재 상품은 공식 자유 규격이 검증되지 않아 사이즈 변경이 잠겨 있습니다.','info');return;}const w=Number($('input-placard-w').value),h=Number($('input-placard-h').value);if(!(w>0&&h>0)){toast('가로/세로를 확인하세요.','error');return;}try{if(!currentJob)await newJob();if(!currentJob)return;const r=await ProductionAPI.resizeJob(currentJob.job_id,w,h);currentProduct={...currentProduct,widthMm:r.width_mm,heightMm:r.height_mm,bleedMm:r.bleed_mm,safeMm:r.safe_margin_mm};products[currentProductId]=currentProduct;canvasMgr.setProduct(currentProduct);canvasMgr.setEyelets(r.eyelets||[]);updateFooter();syncTopProductBar();if(currentUploadFile){await runPreflight();}toast(`제작 사이즈 ${w}×${h}mm 적용 완료`,'success');if(r.warnings?.length)toast(r.warnings.join(' / '),'info');}catch(e){toast(e.message,'error');}});
  // v1.8.1 product browser search & size UX
  $('product-search')?.addEventListener('input',e=>{productSearch=e.target.value.trim().toLowerCase();renderProducts();});
  $('product-search-clear')?.addEventListener('click',()=>{if($('product-search'))$('product-search').value='';productSearch='';renderProducts();});
  let sizeAspect=600/1800;
  function syncSizeAspect(){const w=Number($('input-placard-w')?.value||0),h=Number($('input-placard-h')?.value||0);if(w>0&&h>0)sizeAspect=w/h;}
  $('input-placard-w')?.addEventListener('focus',syncSizeAspect);$('input-placard-h')?.addEventListener('focus',syncSizeAspect);
  $('input-placard-w')?.addEventListener('input',()=>{if($('size-ratio-lock')?.checked&&sizeAspect>0){const w=Number($('input-placard-w').value);if(w>0)$('input-placard-h').value=Math.round((w/sizeAspect)*100)/100;}});
  $('input-placard-h')?.addEventListener('input',()=>{if($('size-ratio-lock')?.checked&&sizeAspect>0){const h=Number($('input-placard-h').value);if(h>0)$('input-placard-w').value=Math.round((h*sizeAspect)*100)/100;}});
  renderCategoryTabs();
  // fonts & object inspector
  const fs=$('obj-font-family');fs.innerHTML='<optgroup label="Korean">'+FontRegistry.KOREAN.map(x=>`<option>${x}</option>`).join('')+'</optgroup><optgroup label="English">'+FontRegistry.ENGLISH.map(x=>`<option>${x}</option>`).join('')+'</optgroup>';fs.onchange=()=>{const o=canvasMgr.activeObject();if(o&&(o.type==='i-text'||o.type==='textbox')){o.set('fontFamily',fs.value);canvasMgr.canvas.requestRenderAll();canvasMgr.saveHistory();}};
  function refreshInspector(){const o=canvasMgr.activeObject();$('active-object-type').textContent=o?(o.type==='image'?'이미지':o.type==='i-text'?'텍스트':'도형'):'선택 없음';if(o&&typeof o.fill==='string')$('obj-fill').value=o.fill.startsWith('#')?o.fill:'#1F9D68';$('obj-opacity').value=o?.opacity??1;$('obj-stroke-width').value=o?.strokeWidth||0;$('obj-shadow-blur').value=o?.shadow?.blur||0;if(o?.fontFamily)fs.value=o.fontFamily;}
  ['selection:created','selection:updated','selection:cleared','object:modified'].forEach(ev=>canvasMgr.canvas.on(ev,()=>{refreshInspector();refreshLayers();}));
  function applyStyle(){canvasMgr.applyShapeStyle({fill:$('obj-fill').value,stroke:$('obj-stroke').value,strokeWidth:$('obj-stroke-width').value,opacity:$('obj-opacity').value,shadowBlur:$('obj-shadow-blur').value});}['obj-fill','obj-stroke','obj-stroke-width','obj-opacity','obj-shadow-blur'].forEach(id=>$(id).addEventListener('input',applyStyle));$('btn-apply-gradient').onclick=()=>canvasMgr.applyShapeStyle({gradient:[$('gradient-a').value,$('gradient-b').value]});$('btn-flip-x').onclick=()=>canvasMgr.flip('x');$('btn-flip-y').onclick=()=>canvasMgr.flip('y');
  function refreshLayers(){const c=$('layers-container');c.innerHTML='';canvasMgr.layers().forEach(l=>{const row=document.createElement('button');row.className='layer-row';row.innerHTML=`<span>${l.name}</span><span class="text-[10px]">${l.obj.visible===false?'숨김':'표시'} · ${l.obj.lockMovementX?'잠금':'편집'}</span>`;row.onclick=()=>{canvasMgr.canvas.setActiveObject(l.obj);canvasMgr.canvas.requestRenderAll();refreshInspector();};row.oncontextmenu=e=>{e.preventDefault();l.obj.visible=l.obj.visible===false?true:false;canvasMgr.canvas.requestRenderAll();refreshLayers();};c.appendChild(row);});}$('btn-refresh-layers').onclick=refreshLayers;
  document.querySelectorAll('.guide-toggle').forEach(b=>{const g=guideHelp[b.dataset.help];if(g)b.title=`${g.title}: ${g.description}`;b.onclick=()=>canvasMgr.toggleGuide(b.dataset.guide);});
  // settings/theme
  $('btn-open-settings')?.addEventListener('click',()=>$('drawer-settings').classList.remove('hidden'));$('hdr-settings-btn')?.addEventListener('click',()=>$('drawer-settings').classList.remove('hidden'));$('btn-close-settings')?.addEventListener('click',()=>$('drawer-settings').classList.add('hidden'));
  const storedTheme=localStorage.getItem('dongle_theme')||'light';$('theme-select').value=storedTheme;function applyTheme(v){let use=v;if(v==='system')use=matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';document.body.classList.toggle('light',use==='light');document.body.dataset.theme=use;document.documentElement.classList.toggle('dark',use!=='light');localStorage.setItem('dongle_theme',v);}$('theme-select').onchange=e=>applyTheme(e.target.value);applyTheme(storedTheme);$('handle-size').oninput=e=>{canvasMgr.setHandleSize(e.target.value);localStorage.setItem('dongle_handle_size',e.target.value)};const hs=localStorage.getItem('dongle_handle_size');if(hs){$('handle-size').value=hs;canvasMgr.setHandleSize(hs);}
  // toolbar
  $('btn-undo').onclick=()=>canvasMgr.undo();$('btn-redo').onclick=()=>canvasMgr.redo();$('btn-guides').onclick=()=>{const on=canvasMgr.toggleGuides();const fg=$('footer-guide-status');if(fg){fg.textContent=`가이드 ${on?'ON':'OFF'}`;fg.classList.toggle('on',on);}};$('btn-toggle-snap').onclick=()=>{const on=canvasMgr.toggleSnap();toast(`스냅 ${on?'ON':'OFF'}`);};
  // 3D mockup prototype with orbit controls
  let mockupRenderer=null,mockupAnim=null;$('btn-preview-mockup').onclick=()=>{$('modal-mockup').classList.remove('hidden');initMockup();};$('btn-close-modal-mockup').onclick=()=>{$('modal-mockup').classList.add('hidden');};function initMockup(){const c=$('three-canvas-container');c.innerHTML='';if(typeof THREE==='undefined')return;const scene=new THREE.Scene();scene.background=new THREE.Color(0x0b1020);const camera=new THREE.PerspectiveCamera(45,c.clientWidth/c.clientHeight,.1,100);camera.position.set(2,1.5,5);const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setSize(c.clientWidth,c.clientHeight);c.appendChild(renderer.domElement);mockupRenderer=renderer;const texture=new THREE.TextureLoader().load(canvasMgr.canvas.toDataURL({format:'png'}));const ratio=(currentProduct.widthMm||600)/(currentProduct.heightMm||600);let ph=3,pw=ph*ratio;if(pw>4){pw=4;ph=pw/ratio;}const plane=new THREE.Mesh(new THREE.PlaneGeometry(pw,ph),new THREE.MeshStandardMaterial({map:texture,side:THREE.DoubleSide}));scene.add(plane);const floor=new THREE.Mesh(new THREE.PlaneGeometry(10,10),new THREE.MeshStandardMaterial({color:0x232937,roughness:1}));floor.rotation.x=-Math.PI/2;floor.position.y=-ph/2-.3;scene.add(floor);scene.add(new THREE.HemisphereLight(0xffffff,0x334155,2));const d=new THREE.DirectionalLight(0xffffff,2);d.position.set(3,4,5);scene.add(d);const controls=THREE.OrbitControls?new THREE.OrbitControls(camera,renderer.domElement):null;if(controls){controls.enableDamping=true;controls.target.set(0,0,0);}const animate=()=>{mockupAnim=requestAnimationFrame(animate);controls?.update();renderer.render(scene,camera);};animate();}
  // export

  const clampOffset=v=>Math.max(1,Math.min(10,Math.round(Number(v)||1)));
  const offsetInput=$('acrylic-offset-mm');
  if(offsetInput){offsetInput.onchange=()=>offsetInput.value=clampOffset(offsetInput.value);$('acrylic-offset-minus')?.addEventListener('click',()=>offsetInput.value=clampOffset(Number(offsetInput.value)-1));$('acrylic-offset-plus')?.addEventListener('click',()=>offsetInput.value=clampOffset(Number(offsetInput.value)+1));}
  $('btn-acrylic-auto-contour')?.addEventListener('click',async()=>{
    if(!['acrylic_print','acrylic_keyring','acrylic_stand'].includes(currentProductId)){toast('아크릴 상품을 먼저 선택하세요.','error');return;}
    const _file=activeAssetFile();
    if(!_file){toast('투명 PNG 이미지를 먼저 업로드하세요.','error');return;}
    if((_file.type||'')!=='image/png'){toast('자동 칼선 분석은 투명 PNG 파일만 지원합니다.','error');return;}
    const st=$('acrylic-contour-status');if(st){st.classList.remove('hidden');st.innerHTML='<span class="text-slate-600">제작 형태를 만들고 있습니다...</span>';}
    try{
      const result=await ProductionAPI.previewAcrylicContour(_file,currentProductId,Number($('acrylic-offset-mm')?.value||1));
      if(currentProductId==='acrylic_keyring'){
        const img=activeArtworkImage();
        if(!img)throw new Error('키링으로 만들 이미지를 선택해 주세요.');
        window.KeyringSync?.attach({image:img,pointsPx:result.points_px,sourceW:result.source_width_px,sourceH:result.source_height_px,hole:keyringState});
      }else canvasMgr.renderAcrylicContour(result.points_px,result.source_width_px,result.source_height_px);
      if(st){st.innerHTML='';st.classList.add('hidden');}
      toast(currentProductId==='acrylic_keyring'?'키링 외곽 칼선과 고리를 만들었습니다.':'칼선을 만들었습니다.','success');
    }catch(e){if(st){st.classList.remove('hidden');st.innerHTML=`<span class="text-rose-600">${e.message}</span>`;}toast(e.message,'error');}
  });
  document.querySelectorAll('.acrylic-hole-btn').forEach(btn=>btn.addEventListener('click',()=>{
    document.querySelectorAll('.acrylic-hole-btn').forEach(b=>b.classList.remove('active','ring-1','ring-emerald-500'));
    btn.classList.add('active');keyringState.holeMode=btn.dataset.holeMode||'TOP_CENTER';
    window.KeyringSync?.updateHole({mode:keyringState.holeMode});
  }));
  document.querySelectorAll('.keyring-ring-size').forEach(btn=>btn.addEventListener('click',()=>{
    document.querySelectorAll('.keyring-ring-size').forEach(b=>b.classList.remove('active'));btn.classList.add('active');
    keyringState.innerMm=Number(btn.dataset.inner||3);keyringState.outerMm=Number(btn.dataset.outer||7);window.KeyringSync?.updateHole({innerMm:keyringState.innerMm,outerMm:keyringState.outerMm});
  }));
  document.querySelectorAll('.keyring-count-btn').forEach(btn=>btn.addEventListener('click',()=>{
    document.querySelectorAll('.keyring-count-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');keyringState.count=Number(btn.dataset.count||1);window.KeyringSync?.updateHole({count:keyringState.count});
  }));
  document.querySelectorAll('.keyring-placement-btn').forEach(btn=>btn.addEventListener('click',()=>{
    document.querySelectorAll('.keyring-placement-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');keyringState.placement=btn.dataset.placement||'OUTSIDE';window.KeyringSync?.updateHole({placement:keyringState.placement});
  }));
  
  $('btn-stand-structure-preview')?.addEventListener('click',async()=>{
    try{await ensureProductionUpload();}catch(_){}/* v2.1.5: 스탠드 제작 시점에 제작 업로드/검수 수행 */
    const payload={part_count:Number($('stand-part-count')?.value||1),base_width_mm:Number($('stand-base-w')?.value||100),base_depth_mm:Number($('stand-base-d')?.value||40),base_shape:'rounded',material_thickness_mm:Number($('stand-thickness')?.value||0),tab_width_mm:Number($('stand-tab-w')?.value||15),tab_height_mm:Number($('stand-tab-h')?.value||0),slot_width_mm:Number($('stand-slot-w')?.value||0),slot_clearance_mm:Number($('stand-clearance')?.value||0)};
    try{const r=await ProductionAPI.previewStandStructure(payload);const st=$('stand-structure-status');const _file=activeAssetFile();if(_file&&(_file.type||'')==='image/png'){const contour=await ProductionAPI.previewAcrylicContour(_file,'acrylic_stand');const rt=r.resolved_tolerances||{};const _img=canvasMgr.canvas.getObjects().filter(o=>o.type==='image'&&!o.isGuide).slice(-1)[0];if(_img&&window.AcrylicSync){AcrylicSync.attach({image:_img,pointsPx:contour.points_px,sourceW:contour.source_width_px,sourceH:contour.source_height_px,tol:{tabWidthMm:payload.tab_width_mm||rt.tab_width_mm||20,tabHeightMm:payload.tab_height_mm||rt.tab_height_mm||8,slotWidthMm:payload.slot_width_mm||rt.slot_width_mm||3.2,materialThicknessMm:payload.material_thickness_mm||rt.material_thickness_mm||3},base:{widthMm:payload.base_width_mm,depthMm:payload.base_depth_mm,shape:payload.base_shape}});}else{canvasMgr.renderAcrylicContour(contour.points_px,contour.source_width_px,contour.source_height_px);}if(st){st.innerHTML='';st.classList.add('hidden');}toast('스탠드 제작 형태를 만들었습니다.','success');}else{if(st){st.classList.remove('hidden');st.textContent='투명 PNG를 먼저 가져오세요.';}toast('투명 PNG를 먼저 가져오세요.','error');}}catch(e){toast(e.message,'error');}
  });
  // v1.9.8: 작업화면 내 '+ 이미지 가져오기' (업로드 탭 이동 없이) — 같은 Upload Store 사용(#3)
  $('btn-stand-import-image')?.addEventListener('click',()=>$('stand-file-import')?.click());
  $('stand-file-import')?.addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;try{await importImageFile(f);toast('이미지를 캔버스에 추가했습니다.','success');}catch(err){toast(err.message,'error');}e.target.value='';});
  // v1.9.8: Canvas Drag & Drop 업로드(#3) — 업로드→캔버스추가→선택→상태저장 한 번에
  (function(){const cw=$('canvas-workspace');if(!cw)return;['dragenter','dragover'].forEach(ev=>cw.addEventListener(ev,e=>{e.preventDefault();cw.classList.add('drag-over');}));cw.addEventListener('dragleave',e=>{if(e.target===cw)cw.classList.remove('drag-over');});cw.addEventListener('drop',async e=>{e.preventDefault();cw.classList.remove('drag-over');const f=[...((e.dataTransfer&&e.dataTransfer.files)||[])].find(x=>/^image\//.test(x.type));if(!f){toast('이미지 파일만 캔버스에 놓을 수 있습니다.','error');return;}try{await importImageFile(f);toast('이미지를 캔버스에 추가했습니다.','success');}catch(err){toast(err.message,'error');}});})();
  // v2.7.2: 캔버스 바깥의 빈 영역/헤더/좌측 메뉴를 클릭해도 선택 해제. 인스펙터/플로팅 편집툴은 선택 유지.
  document.addEventListener('pointerdown',e=>{
    const t=e.target;
    if(!canvasMgr.activeObject())return;
    if(t.closest?.('.canvas-container,#canvas-wrapper,.dongle-inspector,.v17-floating-toolbar,.v17-context-menu,.final-preview-dialog'))return;
    canvasMgr.deselect();refreshInspector();refreshLayers();
  },true);

  $('btn-open-export-modal').onclick=async()=>{if(!currentProduct.productionEnabled){toast('공식 제작가이드 검증 전 상품은 Production PDF를 만들 수 없습니다.','error');return;}const _ok=await ensureProductionUpload();if(!_ok)return;$('export-summary').innerHTML=`<b>${currentProduct.name}</b><br>${currentProduct.widthMm} × ${currentProduct.heightMm} mm<br>RGB 편집 → CMYK 자동 변환<br>${lastPreflight?`Preflight: ${lastPreflight.overall}`:'Preflight 미실행'}`;$('modal-export').classList.remove('hidden');};$('btn-close-export-modal').onclick=()=>$('modal-export').classList.add('hidden');$('btn-confirm-export-pdf').onclick=async()=>{try{const art=await canvasMgr.exportBlob();const opts={fitPolicy:'contain',order_number:$('export-order-number').value,channel:$('export-channel').value,customer_name:$('export-customer').value,quantity:$('export-quantity').value,memo:$('export-memo').value};const blob=await ProductionAPI.exportPrintPdf(currentJob.job_id,art,opts);const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`DONGLE_${currentProductId}_${currentJob.job_id.slice(0,8)}.pdf`;a.click();URL.revokeObjectURL(a.href);$('btn-download-proof')?.classList.remove('hidden');$('btn-download-package')?.classList.remove('hidden');toast('Production PDF 생성 완료 · 고객 시안/제작 패키지도 준비할 수 있습니다.','success');setTimeout(()=>{const m=document.createElement('a');m.href=ProductionAPI.manifestUrl(currentJob.job_id);m.download='production_manifest.json';m.click();},600);}catch(e){if(e.status===409&&e.payload?.issues){toast('Preflight ERROR로 출력이 차단되었습니다.','error');PreflightEngine.render(e.payload,$('preflight-list-container'),()=>{});}else toast(e.message,'error');}};
  $('btn-download-proof')?.addEventListener('click',async()=>{if(!currentJob)return;try{const blob=await ProductionAPI.proofBlob(currentJob.job_id,{order_number:$('export-order-number').value});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${$('export-order-number').value||currentJob.job_id}_proof.jpg`;a.click();URL.revokeObjectURL(a.href);}catch(e){toast(e.message,'error');}});
  $('btn-download-package')?.addEventListener('click',async()=>{if(!currentJob)return;try{const blob=await ProductionAPI.packageBlob(currentJob.job_id);const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${currentJob.job_id}_package.zip`;a.click();URL.revokeObjectURL(a.href);}catch(e){toast(e.message,'error');}});
  // v1.9.3 admin-style product navigation
  $('sidebar-product-toggle')?.addEventListener('click',()=>{const menu=$('sidebar-product-menu');menu?.classList.toggle('collapsed');$('sidebar-product-toggle')?.classList.toggle('is-expanded',!menu?.classList.contains('collapsed'));});
  document.querySelectorAll('.sidebar-category-btn').forEach(btn=>btn.addEventListener('click',()=>{
    activeCategory=btn.dataset.category;
    document.querySelectorAll('.sidebar-category-btn').forEach(b=>b.classList.toggle('active',b===btn));
    document.querySelectorAll('[id^="panel-content-"]').forEach(el=>el.classList.add('hidden'));
    $('panel-content-product')?.classList.remove('hidden');
    document.querySelectorAll('.nav-btn').forEach(b=>b.classList.toggle('active',b.id==='sidebar-product-toggle'));
    $('sidebar-product-toggle')?.classList.add('is-expanded');
    $('sidebar-product-menu')?.classList.remove('collapsed');
    renderCategoryTabs();
    renderProducts();
    $('taxonomy-container')?.scrollTo?.({top:0,behavior:'smooth'});
  }));
  document.querySelector('[data-home="true"]')?.addEventListener('click',()=>{activeCategory='SIGNAGE';productSearch='';if($('product-search'))$('product-search').value='';document.querySelectorAll('.sidebar-category-btn').forEach(b=>b.classList.toggle('active',b.dataset.category==='SIGNAGE'));renderCategoryTabs();renderProducts();});
  $('top-open-product')?.addEventListener('click',()=>{document.querySelector('[data-panel="product"]')?.click();$('product-search')?.focus();});
  function copyTopToBottom(){if($('input-placard-w')&&$('top-size-w'))$('input-placard-w').value=$('top-size-w').value;if($('input-placard-h')&&$('top-size-h'))$('input-placard-h').value=$('top-size-h').value;}
  function copyBottomToTop(){if($('top-size-w')&&$('input-placard-w'))$('top-size-w').value=$('input-placard-w').value;if($('top-size-h')&&$('input-placard-h'))$('top-size-h').value=$('input-placard-h').value;}
  $('top-size-w')?.addEventListener('input',copyTopToBottom);$('top-size-h')?.addEventListener('input',copyTopToBottom);$('input-placard-w')?.addEventListener('input',copyBottomToTop);$('input-placard-h')?.addEventListener('input',copyBottomToTop);$('top-size-apply')?.addEventListener('click',()=>{copyTopToBottom();$('btn-apply-placard-size')?.click();});
  // Inspector tabs
  function setInspectorTab(tab){document.querySelectorAll('.inspector-tab').forEach(b=>b.classList.toggle('active',b.dataset.inspectorTab===tab));document.querySelectorAll('[data-inspector-section]').forEach(el=>{el.style.display=el.dataset.inspectorSection===tab?'':'none';});}
  document.querySelectorAll('.inspector-tab').forEach(b=>b.addEventListener('click',()=>setInspectorTab(b.dataset.inspectorTab)));setInspectorTab('edit');
  // Workspace quick navigation + real horizontal scrolling
  const track=$('workspace-tab-track');$('workspace-tabs-left')?.addEventListener('click',()=>track?.scrollBy({left:-240,behavior:'smooth'}));$('workspace-tabs-right')?.addEventListener('click',()=>track?.scrollBy({left:240,behavior:'smooth'}));track?.addEventListener('wheel',e=>{if(Math.abs(e.deltaY)>Math.abs(e.deltaX)){e.preventDefault();track.scrollLeft+=e.deltaY;}},{passive:false});let dragScroll=false,dragX=0,dragLeft=0;track?.addEventListener('pointerdown',e=>{if(e.target.closest('button'))return;dragScroll=true;dragX=e.clientX;dragLeft=track.scrollLeft;track.setPointerCapture?.(e.pointerId)});track?.addEventListener('pointermove',e=>{if(dragScroll)track.scrollLeft=dragLeft-(e.clientX-dragX)});track?.addEventListener('pointerup',()=>dragScroll=false);track?.addEventListener('pointercancel',()=>dragScroll=false);
  function activateWorkspace(btn){document.querySelectorAll('.workspace-tab').forEach(b=>b.classList.toggle('active',b===btn));const w=btn.dataset.workspace;if(w==='product'){document.querySelector('[data-panel="product"]')?.click();setInspectorTab('production');}else if(w==='design'){setInspectorTab('edit');}else if(w==='guide'){setInspectorTab('production');document.querySelector('[data-guide="trim"]')?.scrollIntoView({behavior:'smooth',block:'center'});}else if(w==='mockup'){$('btn-preview-mockup')?.click();}else if(w==='preflight'){setInspectorTab('production');$('preflight-list-container')?.scrollIntoView({behavior:'smooth',block:'center'});}else if(w==='layers'){setInspectorTab('layers');$('layers-container')?.scrollIntoView({behavior:'smooth',block:'center'});}else if(w==='history'){setInspectorTab('history');}}
  document.querySelectorAll('.workspace-tab').forEach(b=>b.addEventListener('click',()=>activateWorkspace(b)));
  await selectProduct('indoor_banner');refreshInspector();refreshLayers();
});
