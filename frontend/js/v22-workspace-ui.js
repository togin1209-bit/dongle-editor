/* v2.2 Workspace UI — 클립아트코리아형 재설계용 '추가' 인터랙션.
 * 원칙: 기존 app.js/canvas-manager/업로드/아크릴 로직을 절대 수정하지 않는다.
 *       이 파일은 기존에 핸들러가 없던 신규 요소에만 리스너를 붙이므로 이중 바인딩(Double Binding) 위험이 없다.
 */
(function () {
  'use strict';
  function ready(fn){ if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',fn,{once:true}); else fn(); }

  ready(function () {
    var $ = function (id) { return document.getElementById(id); };

    // 중복 초기화 방지 가드
    if (window.__v22WorkspaceUI) return; window.__v22WorkspaceUI = true;

    /* ---------- 1) 파일명 인라인 편집 (제목 없는 디자인) ---------- */
    var titleInput = $('design-title-input');
    if (titleInput) {
      var applyTitle = function () {
        var v = (titleInput.value || '').trim() || '제목 없는 디자인';
        titleInput.value = v;
        try { document.title = v + ' · 동그라미 스튜디오'; } catch (e) {}
      };
      titleInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); titleInput.blur(); }
        if (e.key === 'Escape') { titleInput.blur(); }
      });
      titleInput.addEventListener('blur', applyTitle);
      titleInput.addEventListener('focus', function () { titleInput.select(); });
    }

    /* ---------- 2) 우측 인스펙터 접기/펼치기 (Collapse Handle) ---------- */
    // 기존 #inspector-collapse 버튼(핸들러 없었음) + 신규 부착형 엣지 핸들을 함께 사용.
    var collapseBtn = $('inspector-collapse');
    var edgeToggle  = $('inspector-edge-toggle');
    function setInspector(collapsed) {
      document.body.classList.toggle('inspector-collapsed', collapsed);
      if (edgeToggle) edgeToggle.setAttribute('aria-expanded', String(!collapsed));
      // fabric 캔버스가 레이아웃 변화를 반영하도록 리사이즈 신호(안전: 있으면만)
      try { if (window.canvasMgr && window.canvasMgr.updateCanvasDimensions) window.canvasMgr.updateCanvasDimensions(); } catch (e) {}
      try { window.dispatchEvent(new Event('resize')); } catch (e) {}
    }
    if (collapseBtn) collapseBtn.addEventListener('click', function (e) { e.preventDefault(); setInspector(!document.body.classList.contains('inspector-collapsed')); });
    if (edgeToggle)  edgeToggle.addEventListener('click',  function (e) { e.preventDefault(); setInspector(!document.body.classList.contains('inspector-collapsed')); });

    /* ---------- 3) 좌측 확장 패널 접기 (선택) ---------- */
    var leftEdge = $('leftpanel-edge-toggle');
    function setLeft(collapsed){
      document.body.classList.toggle('leftpanel-collapsed', collapsed);
      if (leftEdge) leftEdge.setAttribute('aria-expanded', String(!collapsed));
      try { if (window.canvasMgr && window.canvasMgr.updateCanvasDimensions) window.canvasMgr.updateCanvasDimensions(); } catch (e) {}
      try { window.dispatchEvent(new Event('resize')); } catch (e) {}
    }
    if (leftEdge) leftEdge.addEventListener('click', function(e){ e.preventDefault(); setLeft(!document.body.classList.contains('leftpanel-collapsed')); });

    /* ---------- 4) 상단 Zoom 배지: 푸터 줌 라벨과 동기 표시(읽기전용 미러) ---------- */
    var headerZoom = $('header-zoom-label');
    var footerZoom = $('v17-zoom-label');
    if (headerZoom && footerZoom) {
      var sync = function(){ headerZoom.textContent = footerZoom.textContent || '100%'; };
      sync();
      // 값 변화 관찰(경량, characterData) — footerZoom만 관찰하므로 루프 위험 없음
      try { new MutationObserver(sync).observe(footerZoom, { childList: true, characterData: true, subtree: true }); } catch (e) {}
      headerZoom.addEventListener('click', function(){ $('v17-zoom-fit') && $('v17-zoom-fit').click(); });
    }

    /* ---------- 5) 파일 메뉴 드롭다운 (기존 액션 재사용, 새 파이프라인 없음) ---------- */
    var fileBtn = $('hdr-file-btn'), fileMenu = $('hdr-file-menu');
    function closeFileMenu(){ if(fileMenu){ fileMenu.classList.add('hidden'); if(fileBtn) fileBtn.classList.remove('open'); } }
    if (fileBtn && fileMenu) {
      fileBtn.addEventListener('click', function (e) { e.stopPropagation(); var h = fileMenu.classList.toggle('hidden'); fileBtn.classList.toggle('open', !h); });
      document.addEventListener('click', function (e) { if (!fileMenu.classList.contains('hidden') && !fileMenu.contains(e.target) && e.target !== fileBtn) closeFileMenu(); });
      fileMenu.querySelectorAll('[data-file-action]').forEach(function (b) {
        b.addEventListener('click', function () {
          var act = b.getAttribute('data-file-action'); closeFileMenu();
          var toast = window.dongleToast || function () {};
          if (act === 'import' || act === 'upload') {
            // 공통 Import Pipeline 재사용: 기존 파일 input(onchange=importImageFile) 트리거
            var target = $('file-upload') || $('stand-file-import');
            if (target) target.click(); else toast('업로드 입력을 찾지 못했습니다.', 'error');
          } else if (act === 'export') { var ex = $('btn-open-export-modal'); if (ex) ex.click(); }
          else if (act === 'save' || act === 'save-as') {
            try {
              var mgr=window.canvasMgr;if(!mgr||!mgr.canvas) throw new Error('캔버스가 준비되지 않았습니다.');
              var title=(($('design-title-input')&&$('design-title-input').value)||'제목 없는 디자인').trim();
              var payload={version:'2.4',title:title,savedAt:new Date().toISOString(),product:mgr.productSpecs,canvas:mgr.canvas.toDatalessJSON(['name','data'])};
              var blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');
              a.href=url;a.download=(title.replace(/[\\/:*?"<>|]/g,'_')||'dongle_design')+'.dongle.json';a.click();setTimeout(function(){URL.revokeObjectURL(url);},0);toast('디자인 파일을 저장했습니다.','success');
            } catch(e) { toast(e.message||'저장하지 못했습니다.','error'); }
          }
          else if (act === 'new') {
            if(window.canvasMgr&&window.canvasMgr.canvas){window.canvasMgr.canvas.getObjects().filter(function(o){return !o.isGuide;}).forEach(function(o){window.canvasMgr.canvas.remove(o);});window.canvasMgr.canvas.discardActiveObject();window.canvasMgr.renderGuideLines();window.canvasMgr.canvas.requestRenderAll();}
            if($('design-title-input'))$('design-title-input').value='제목 없는 디자인';toast('새 디자인을 시작했습니다.','success');
          }
        });
      });
    }

    /* ---------- 6) 설정 버튼 → 기존 설정 드로어 ---------- */
    var setBtn = $('hdr-settings-btn'), openSet = $('btn-open-settings');
    if (setBtn && openSet) setBtn.addEventListener('click', function () { openSet.click(); });

    /* ---------- 7) 작업 사이즈 헤더 동기화 (기존 값 미러) ---------- */
    var wsMain = $('hdr-worksize-main');
    var srcWork = $('footer-working-size') || $('top-working-size');
    var srcTrim = $('footer-trim-size');
    function syncWorkSize(){
      if (!wsMain) return;
      var w = (srcWork && srcWork.textContent || '').trim();
      if (w) wsMain.textContent = /mm/.test(w) ? w : (w + ' mm');
      var host = $('hdr-worksize');
      if (host) { var t = (srcTrim && srcTrim.textContent || '').trim(); host.title = (t ? ('제품 ' + t + '  ·  ') : '') + '작업 ' + w; }
    }
    syncWorkSize();
    if (srcWork) { try { new MutationObserver(syncWorkSize).observe(srcWork, { childList: true, characterData: true, subtree: true }); } catch (e) {} }
  });
})();
