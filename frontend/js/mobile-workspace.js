
(function(){
  const $=id=>document.getElementById(id);
  const isMobile=()=>window.matchMedia('(max-width: 768px)').matches;
  const panel=document.querySelector('.dongle-product-panel');
  const inspector=document.querySelector('.dongle-inspector');
  const backdrop=$('mobile-sheet-backdrop');
  const inspectorToggle=$('mobile-inspector-toggle');

  function closeSheets(except){
    if(except!=='panel') panel?.classList.remove('mobile-open');
    if(except!=='inspector') inspector?.classList.remove('mobile-open');
    const any=panel?.classList.contains('mobile-open')||inspector?.classList.contains('mobile-open');
    backdrop?.classList.toggle('show',!!any);
    document.body.classList.toggle('mobile-sheet-open',!!any);
  }

  function openPanel(){
    if(!isMobile()) return;
    inspector?.classList.remove('mobile-open');
    panel?.classList.add('mobile-open');
    backdrop?.classList.add('show');
    document.body.classList.add('mobile-sheet-open');
  }
  function openInspector(){
    if(!isMobile()) return;
    panel?.classList.remove('mobile-open');
    inspector?.classList.add('mobile-open');
    backdrop?.classList.add('show');
    document.body.classList.add('mobile-sheet-open');
  }

  document.querySelectorAll('.sidebar-main-btn.nav-btn').forEach(btn=>{
    btn.addEventListener('click',()=>setTimeout(openPanel,0));
  });
  document.querySelectorAll('.sidebar-category-btn').forEach(btn=>{
    btn.addEventListener('click',()=>setTimeout(openPanel,0));
  });

  inspectorToggle?.addEventListener('click',openInspector);
  backdrop?.addEventListener('click',()=>closeSheets());

  document.getElementById('canvas-workspace')?.addEventListener('pointerdown',e=>{
    if(!isMobile()) return;
    if(e.target.closest('#canvas-wrapper')) closeSheets();
  });

  // close product sheet after adding an item / selecting product on narrow screens
  panel?.addEventListener('click',e=>{
    if(!isMobile()) return;
    const actionable=e.target.closest('.product-card,.add-elem-btn,[data-text-preset],.upload-library-item');
    if(actionable) setTimeout(()=>closeSheets(),120);
  });

  // Product button remains expandable, but sheet itself must open.
  $('sidebar-product-toggle')?.addEventListener('click',()=>setTimeout(openPanel,0));

  // Mobile header export: keep actual button; hide label via CSS only.
  function syncMobile(){
    const mobile=isMobile();
    document.body.classList.toggle('is-mobile-editor',mobile);
    if(!mobile) closeSheets();
    if(mobile){
      setTimeout(()=>window.DongleCanvas?.fitToWorkspace?.(),180);
    }
  }
  window.addEventListener('resize',syncMobile,{passive:true});
  window.addEventListener('orientationchange',()=>setTimeout(syncMobile,180));
  syncMobile();

  // expose for QA / future native wrapper
  window.MobileWorkspace={openPanel,openInspector,closeSheets,isMobile};
})();

/* v2.10.1: mobile viewport stabilization + canvas refit */
(function(){
  if(!window.matchMedia) return;
  const mq=window.matchMedia('(max-width: 768px)');
  function refit(){
    if(!mq.matches) return;
    requestAnimationFrame(()=>requestAnimationFrame(()=>window.DongleCanvas?.fitToWorkspace?.()));
  }
  if(window.visualViewport){
    window.visualViewport.addEventListener('resize',refit,{passive:true});
    window.visualViewport.addEventListener('scroll',refit,{passive:true});
  }
  window.addEventListener('load',()=>setTimeout(refit,250),{once:true});
})();
