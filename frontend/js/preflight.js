window.PreflightEngine = {
  severityClass(level) { return (level === 'ERROR' || level === 'BLOCKING_ERROR') ? 'error' : (level === 'WARNING' ? 'warning' : 'pass'); },
  render(report, container, onIssueClick) {
    container.innerHTML = '';
    if (!report) {
      container.innerHTML = `<div class="pf-card-v14 text-xs p-3.5 text-slate-400 border border-slate-800 bg-slate-950/80 rounded-xl"><div class="font-semibold text-slate-300 mb-1 flex items-center gap-1.5"><i data-lucide="shield-check" class="w-4 h-4 text-indigo-400"></i><span>자동 검사 준비됨</span></div><p class="text-[11px] text-slate-500">캔버스 변경 시 실시간으로 인쇄 적합성을 검사합니다.</p></div>`;
      if (window.lucide) lucide.createIcons();
      return;
    }
    const overall = report.overall || 'PASS';
    const headerCard = document.createElement('div');
    headerCard.className = `p-3 rounded-xl border mb-3 flex items-center justify-between ${overall === 'PASS' ? 'bg-emerald-950/30 border-emerald-500/40 text-emerald-300' : 'bg-amber-950/30 border-amber-500/40 text-amber-300'}`;
    headerCard.innerHTML = `<div class="font-bold text-xs">제작 준비도: ${overall === 'PASS' ? '● 제작 가능' : '▲ 확인 필요'}</div><span class="text-[10px] font-mono px-2 py-0.5 rounded bg-black/40 border border-white/10">${(report.issues || []).length} 건</span>`;
    container.appendChild(headerCard);

    if ((report.issues || []).length > 0) {
      report.issues.forEach((issue, idx) => {
        const card = document.createElement('div');
        card.className = `pf-card-v14 ${this.severityClass(issue.severity)} mb-2 space-y-1.5`;
        card.innerHTML = `<div class="font-bold text-xs text-slate-200">${issue.title}</div><div class="text-[11px] text-slate-300 leading-normal">${issue.description}</div><div class="flex gap-2 pt-1"><button class="btn-locate flex-1 py-1 bg-slate-800 text-slate-200 text-[10px] rounded border border-slate-700">요소 선택</button><button class="btn-autofix flex-1 py-1 bg-indigo-600 text-white text-[10px] font-bold rounded shadow">[자동 수정]</button></div>`;
        card.querySelector('.btn-locate').onclick = () => onIssueClick && onIssueClick(issue, 'select');
        card.querySelector('.btn-autofix').onclick = () => onIssueClick && onIssueClick(issue, 'autofix');
        container.appendChild(card);
      });
    }
    if (window.lucide) lucide.createIcons();
  }
};