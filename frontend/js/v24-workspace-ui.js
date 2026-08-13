(function(){'use strict';
function ready(fn){document.readyState==='loading'?document.addEventListener('DOMContentLoaded',fn,{once:true}):fn();}
ready(function(){if(window.__v24UI)return;window.__v24UI=true;const $=id=>document.getElementById(id),mgr=window.canvasMgr;
  const hz=$('header-zoom-label');if(hz&&mgr){
    const menu=document.createElement('div');menu.className='zoom-menu hidden';menu.id='header-zoom-menu';
    [25,50,75,100,125,150,200].forEach(n=>{const b=document.createElement('button');b.textContent=n+'%';b.onclick=e=>{e.stopPropagation();mgr.setZoom(n/100);sync();menu.classList.add('hidden');};menu.appendChild(b);});
    const fit=document.createElement('button');fit.textContent='화면 맞춤';fit.onclick=e=>{e.stopPropagation();mgr.fitToWorkspace();sync();menu.classList.add('hidden');};menu.appendChild(fit);
    hz.parentNode.appendChild(menu);hz.onclick=e=>{e.stopPropagation();menu.classList.toggle('hidden');};document.addEventListener('click',()=>menu.classList.add('hidden'));
    function sync(){hz.textContent=Math.round((mgr.zoom||1)*100)+'%';const f=$('v17-zoom-label');if(f)f.textContent=hz.textContent;window.dispatchEvent(new CustomEvent('dongle:zoomchange',{detail:{zoom:mgr.zoom||1}}));}
    ['setZoom','zoomIn','zoomOut','fitToWorkspace'].forEach(name=>{if(typeof mgr[name]!=='function'||mgr[name].__v24)return;const orig=mgr[name].bind(mgr);const wrap=function(){const r=orig.apply(null,arguments);sync();return r;};wrap.__v24=true;mgr[name]=wrap;});sync();
  }
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='0'){e.preventDefault();mgr?.fitToWorkspace();}});
  const title=$('design-title-input');if(title){title.addEventListener('input',()=>{try{sessionStorage.setItem('dongle.designTitle',title.value);}catch(_){}});try{const v=sessionStorage.getItem('dongle.designTitle');if(v)title.value=v;}catch(_){}}
});})();
