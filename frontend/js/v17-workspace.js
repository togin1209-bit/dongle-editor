(function(){
'use strict';
const isTextTarget=(t)=>{if(!t)return false;const tag=(t.tagName||'').toUpperCase();return tag==='INPUT'||tag==='TEXTAREA'||t.isContentEditable;};
const mod=(e)=>e.ctrlKey||e.metaKey;
function init(){
 const mgr=window.canvasMgr;if(!mgr)return setTimeout(init,80);
 const $=id=>document.getElementById(id);let spaceDown=false,isPanning=false,last={x:0,y:0};
 const toast=(msg)=>window.dongleToast?window.dongleToast(msg):console.log(msg);
 const run=async(name)=>{switch(name){
   case'delete':mgr.deleteSelected();mgr.saveHistory('삭제');break;case'undo':mgr.undo();break;case'redo':mgr.redo();break;
   case'copy':await mgr.copySelected();break;case'paste':await mgr.pasteClipboard();break;case'cut':await mgr.cutSelected();break;case'duplicate':await mgr.duplicateSelected();break;
   case'selectAll':mgr.selectAll();break;case'deselect':mgr.deselect();break;case'group':mgr.groupSelected();break;case'ungroup':mgr.ungroupSelected();break;case'lock':mgr.toggleLock();break;
   case'front':mgr.bringForward();break;case'back':mgr.sendBackward();break;case'top':mgr.bringToFront();break;case'bottom':mgr.sendToBack();break;
   case'fit':mgr.fitToWorkspace();updateZoom();break;case'zin':mgr.zoomIn();updateZoom();break;case'zout':mgr.zoomOut();updateZoom();break;
 }};
 document.addEventListener('keydown',async e=>{
   if(e.key===' '&&!isTextTarget(e.target)){spaceDown=true;e.preventDefault();return;}
   if(isTextTarget(e.target))return;
   const k=e.key.toLowerCase();let action=null;
   if(k==='delete'||k==='backspace')action='delete';
   else if(mod(e)&&k==='z'&&!e.shiftKey)action='undo';else if((mod(e)&&e.shiftKey&&k==='z')||(mod(e)&&k==='y'))action='redo';
   else if(mod(e)&&k==='c')action='copy';else if(mod(e)&&k==='v')action='paste';else if(mod(e)&&k==='x')action='cut';else if(mod(e)&&k==='d')action='duplicate';else if(mod(e)&&k==='a')action='selectAll';
   else if(k==='escape')action='deselect';else if(mod(e)&&k==='g'&&!e.shiftKey)action='group';else if(mod(e)&&k==='g'&&e.shiftKey)action='ungroup';else if(mod(e)&&k==='l')action='lock';
   else if(mod(e)&&k===']'&&!e.shiftKey)action='front';else if(mod(e)&&k==='['&&!e.shiftKey)action='back';else if(mod(e)&&k===']'&&e.shiftKey)action='top';else if(mod(e)&&k==='['&&e.shiftKey)action='bottom';
   else if(mod(e)&&k==='0')action='fit';else if(mod(e)&&(k==='+'||k==='='))action='zin';else if(mod(e)&&k==='-')action='zout';
   if(['arrowleft','arrowright','arrowup','arrowdown'].includes(k)){const n=e.shiftKey?10:1;mgr.moveSelection(k==='arrowleft'?-n:k==='arrowright'?n:0,k==='arrowup'?-n:k==='arrowdown'?n:0);e.preventDefault();refreshHistory();return;}
   if(mod(e)&&k==='s'){e.preventDefault();localStorage.setItem('dongle_autosave_canvas',JSON.stringify(mgr.canvas.toDatalessJSON(['name'])));toast('로컬 작업상태를 저장했습니다.');return;}
   if(action){e.preventDefault();await run(action);refreshHistory();refreshFloating();}
 });
 document.addEventListener('keyup',e=>{if(e.key===' ')spaceDown=false;});
 const viewport=$('canvas-workspace')||$('canvas-wrapper')?.parentElement;
 if(viewport){viewport.addEventListener('mousedown',e=>{if(!spaceDown)return;isPanning=true;last={x:e.clientX,y:e.clientY};viewport.style.cursor='grabbing';e.preventDefault();});window.addEventListener('mousemove',e=>{if(!isPanning)return;viewport.scrollLeft-=e.clientX-last.x;viewport.scrollTop-=e.clientY-last.y;last={x:e.clientX,y:e.clientY};});window.addEventListener('mouseup',()=>{if(isPanning){isPanning=false;viewport.style.cursor='';}});viewport.addEventListener('wheel',e=>{if(!e.altKey)return;e.preventDefault();e.deltaY<0?mgr.zoomIn():mgr.zoomOut();updateZoom();},{passive:false});}
 const updateZoom=()=>{const z=$('v17-zoom-label');if(z)z.textContent=Math.round(mgr.zoom*100)+'%';};
 $('v17-zoom-in')?.addEventListener('click',()=>{mgr.zoomIn();updateZoom();});$('v17-zoom-out')?.addEventListener('click',()=>{mgr.zoomOut();updateZoom();});$('v17-zoom-fit')?.addEventListener('click',()=>{mgr.fitToWorkspace();updateZoom();});
 const floating=$('v17-floating-toolbar');
 function refreshFloating(){if(!floating)return;const o=mgr.activeObject();if(!o||o.isGuide){floating.classList.add('hidden');return;}floating.classList.remove('hidden');const wr=$('canvas-wrapper')?.getBoundingClientRect();const b=o.getBoundingRect(true,true);if(wr){floating.style.left=(wr.left+b.left* mgr.zoom)+'px';floating.style.top=Math.max(62,wr.top+b.top*mgr.zoom-42)+'px';}}
 ['selection:created','selection:updated','selection:cleared','object:moving','object:modified'].forEach(ev=>mgr.canvas.on(ev,refreshFloating));window.addEventListener('resize',refreshFloating);
 $('v17-float-delete')?.addEventListener('click',()=>run('delete'));$('v17-float-duplicate')?.addEventListener('click',()=>run('duplicate'));$('v17-float-remove-bg')?.addEventListener('click',()=>document.getElementById('btn-ai-remove-bg')?.click());
 // Context menu
 const menu=$('v17-context-menu');mgr.canvas.on('mouse:down',opt=>{if(opt.e?.button===2){opt.e.preventDefault();if(menu){menu.classList.remove('hidden');menu.style.left=opt.e.clientX+'px';menu.style.top=opt.e.clientY+'px';}}});document.addEventListener('click',()=>menu?.classList.add('hidden'));menu?.querySelectorAll('[data-v17-action]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();run(b.dataset.v17Action);menu.classList.add('hidden');}));
 // Smart image inspector adjustments
 function refreshSmart(){const type=mgr.objectType();document.querySelectorAll('[data-smart-type]').forEach(x=>x.classList.toggle('hidden',x.dataset.smartType!==type));}
 ['selection:created','selection:updated','selection:cleared'].forEach(ev=>mgr.canvas.on(ev,refreshSmart));refreshSmart();
 ['brightness','contrast','saturation','blur'].forEach(k=>{$('v17-'+k)?.addEventListener('input',()=>{mgr.applyImageAdjustments({brightness:Number($('v17-brightness')?.value||0),contrast:Number($('v17-contrast')?.value||0),saturation:Number($('v17-saturation')?.value||0),blur:Number($('v17-blur')?.value||0)});});});
 $('v17-img-flip-x')?.addEventListener('click',()=>mgr.flip('x'));$('v17-img-flip-y')?.addEventListener('click',()=>mgr.flip('y'));$('v17-img-duplicate')?.addEventListener('click',()=>run('duplicate'));
 // History panel
 function refreshHistory(){const c=$('v17-history-list');if(!c)return;c.innerHTML='';(mgr.historyMeta||[]).map((m,i)=>({m,i})).slice(-12).reverse().forEach(({m,i})=>{const b=document.createElement('button');b.className='v17-history-row';const tm=new Date(m.timestamp).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'});b.innerHTML=`<span>${m.description||'작업 변경'}</span><small>${tm}</small>`;b.onclick=()=>{mgr._loadHistory(i);refreshHistory();};c.appendChild(b);});}
 ['object:added','object:modified','object:removed'].forEach(ev=>mgr.canvas.on(ev,()=>setTimeout(refreshHistory,0)));refreshHistory();
 // Quick local command bar - intentionally not presented as generative AI
 $('v17-command-run')?.addEventListener('click',()=>executeCommand());$('v17-command-input')?.addEventListener('keydown',e=>{if(e.key==='Enter')executeCommand();});
 function executeCommand(){const q=($('v17-command-input')?.value||'').trim();if(!q)return;if(q.includes('배경')&&q.includes('제거'))document.getElementById('btn-ai-remove-bg')?.click();else if(q.includes('삭제'))run('delete');else if(q.includes('복제'))run('duplicate');else if(q.includes('가운데')||q.includes('중앙'))mgr.centerSelected();else if(q.includes('맞춤')||q.includes('화면'))run('fit');else toast('현재 로컬 Quick Command에서는 배경제거/삭제/복제/가운데정렬/화면맞춤을 지원합니다.');}
 updateZoom();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
