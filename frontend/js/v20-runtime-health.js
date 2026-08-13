/* 동그라미 스튜디오 v2.0 — runtime dependency health check */
(function(){
  function show(message, level){
    if(document.getElementById('v20-runtime-health')) return;
    var el=document.createElement('div');
    el.id='v20-runtime-health';
    el.setAttribute('role','alert');
    el.style.cssText='position:fixed;left:50%;top:66px;transform:translateX(-50%);z-index:99999;max-width:720px;padding:10px 14px;border-radius:10px;font:600 13px/1.45 Pretendard,Arial,sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.18);background:'+(level==='error'?'#fff1f2':'#fffbeb')+';color:'+(level==='error'?'#9f1239':'#92400e')+';border:1px solid '+(level==='error'?'#fecdd3':'#fde68a');
    el.textContent=message;
    document.body.appendChild(el);
  }
  window.addEventListener('DOMContentLoaded', function(){
    var missing=[];
    if(!window.fabric) missing.push('Fabric.js');
    if(!window.lucide) missing.push('Lucide');
    if(!window.THREE) missing.push('Three.js');
    if(missing.length){
      show('편집기 필수 모듈을 불러오지 못했습니다: '+missing.join(', ')+' · 인터넷 연결을 확인한 뒤 새로고침하세요.', 'error');
      document.documentElement.dataset.runtimeHealth='dependency-error';
    } else {
      document.documentElement.dataset.runtimeHealth='ok';
    }
  });
})();
