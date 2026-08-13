/* v2.4 ImageImportController — all editor image entry points converge here. */
(function(global){
  'use strict';
  if(global.ImageImportController)return;
  let busy=false;
  const ACCEPT=/^image\/(png|jpeg|jpg|webp)$/i;
  function status(on,label){
    document.body.classList.toggle('image-import-busy',!!on);
    let el=document.getElementById('image-import-status');
    if(!el){el=document.createElement('div');el.id='image-import-status';el.className='image-import-status';el.setAttribute('role','status');el.setAttribute('aria-live','polite');document.body.appendChild(el);}
    el.textContent=label||'이미지를 불러오는 중…';el.classList.toggle('show',!!on);
  }
  async function importFile(file,ctx={}){
    if(!file)return null;
    if(busy)throw new Error('이미지를 불러오는 중입니다. 잠시 후 다시 시도해 주세요.');
    if(!ACCEPT.test(file.type||''))throw new Error('PNG, JPG 또는 WEBP 이미지를 선택해 주세요.');
    if(file.size>150*1024*1024)throw new Error('이미지는 150MB 이하로 업로드해 주세요.');
    const mgr=ctx.canvasMgr||global.canvasMgr;if(!mgr)throw new Error('캔버스가 준비되지 않았습니다.');
    busy=true;status(true,'이미지를 최적화하고 캔버스에 표시하는 중…');
    try{
      await new Promise(r=>requestAnimationFrame(()=>r()));
      const asset=await global.UploadStore.add(file);
      const img=await mgr.addImageFromAsset(asset);
      if(!img)throw new Error('이미지를 캔버스에 표시하지 못했습니다.');
      global.UploadStore.setActive(asset.id);
      return img;
    }finally{busy=false;status(false);}
  }
  global.ImageImportController={importFile,get busy(){return busy;}};
})(window);
