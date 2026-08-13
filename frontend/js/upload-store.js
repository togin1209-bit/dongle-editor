/* upload-store.js — v1.9.8 (CLAUDE track)
 * 작업지시서 #4: Upload State 단일화 (Single Source of Truth).
 *
 * 버그 원인: Canvas 에는 PNG 가 있는데 "PNG 를 먼저 업로드하세요" 로 판단하는 문제.
 * 원인은 업로드 상태가 여러 곳(currentUploadFile 변수 / DOM input / Canvas)에 흩어져
 * 있었기 때문. 이 모듈이 유일한 자산 저장소가 된다.
 *
 *   editorState.assets = { activeImageId, items: { [id]: {file,src,mimeType,
 *                          isTransparent, originalWidth, originalHeight} } }
 *
 * Fabric 객체에는 object.data = { assetId, productionRole } 를 저장하고,
 * 칼선 생성 기능은 DOM input 이 아니라 "현재 선택 객체의 assetId" 로 원본을 찾는다.
 */
(function (global) {
  'use strict';

  const editorState = global.editorState || (global.editorState = {});
  editorState.assets = editorState.assets || { activeImageId: null, items: {} };

  let _seq = 0;
  const nextId = () => `asset_${Date.now().toString(36)}_${(_seq++).toString(36)}`;

  function _isTransparentType(file) {
    return !!file && (file.type === 'image/png' || /\.png$/i.test(file.name || ''));
  }

  const UploadStore = {
    state: editorState.assets,

    /**
     * v2.1.5(PM P0-2): 메인스레드 비차단 디코딩/축소.
     * - 디코딩은 createImageBitmap(파일)로 오프-메인스레드에서 수행(new Image().onload의
     *   메인스레드 동기 디코딩을 피함 → 초대형 이미지에서도 UI가 멈추지 않음).
     * - 3000px 초과 시 GPU 스케일 draw + toBlob(비동기 인코딩) → objectURL. (동기 toDataURL 회피)
     * - createImageBitmap 미지원 시 원본 objectURL로 안전 폴백.
     */
    async add(file) {
      if (!file) throw new Error('file required');
      const sig = `${file.name}|${file.size}|${file.lastModified}`;
      const existing = Object.values(this.state.items).find(a => a._sig === sig);
      if (existing) { this.state.activeImageId = existing.id; return existing; }

      const id = nextId();
      const MAX = 3000;
      let src, isObjectUrl = true, fw = 0, fh = 0;
      try {
        if (typeof createImageBitmap === 'function') {
          const bmp = await createImageBitmap(file);           // 오프-메인스레드 디코딩
          const ow = bmp.width, oh = bmp.height;
          if (Math.max(ow, oh) > MAX) {
            const k = MAX / Math.max(ow, oh);
            fw = Math.round(ow * k); fh = Math.round(oh * k);
            const cv = document.createElement('canvas');
            cv.width = fw; cv.height = fh;
            cv.getContext('2d').drawImage(bmp, 0, 0, fw, fh);  // GPU 스케일 다운(빠름)
            const type = _isTransparentType(file) ? 'image/png' : 'image/jpeg';
            const blob = await new Promise(res => cv.toBlob(res, type, 0.92)); // 비동기 인코딩
            src = blob ? URL.createObjectURL(blob) : URL.createObjectURL(file);
            isObjectUrl = true;
          } else {
            fw = ow; fh = oh; src = URL.createObjectURL(file);
          }
          if (bmp.close) bmp.close();
        } else {
          src = URL.createObjectURL(file); // 폴백: 원본(축소 없음)
        }
      } catch (_) {
        try { src = URL.createObjectURL(file); } catch (__) { throw new Error('손상되었거나 읽을 수 없는 이미지입니다.'); }
        isObjectUrl = true;
      }
      const asset = {
        id, _sig: sig, file, src, objectUrl: isObjectUrl,
        mimeType: file.type || 'image/png',
        isTransparent: _isTransparentType(file),
        originalWidth: fw, originalHeight: fh,
      };
      this.state.items[id] = asset;
      this.state.activeImageId = id;
      return asset;
    },

    get(id) { return id ? this.state.items[id] || null : null; },

    /** Fabric 객체(object.data.assetId)로 자산 조회 — DOM 조회 대신 이걸 쓴다. */
    forObject(obj) {
      const id = obj && obj.data && obj.data.assetId;
      return this.get(id);
    },

    setActive(id) { if (this.state.items[id]) this.state.activeImageId = id; },
    active() { return this.get(this.state.activeImageId); },

    /** 현재 활성 자산의 File 객체 (기존 currentUploadFile 대체). */
    activeFile() { const a = this.active(); return a ? a.file : null; },

    remove(id) {
      const a = this.state.items[id];
      if (a && a.objectUrl && a.src) { try { URL.revokeObjectURL(a.src); } catch (_) {} }
      delete this.state.items[id];
      if (this.state.activeImageId === id) this.state.activeImageId = null;
    },

    tagObject(obj, assetId, productionRole = 'design') {
      if (!obj) return obj;
      obj.data = Object.assign({}, obj.data, { assetId, productionRole });
      return obj;
    },
  };

  global.UploadStore = UploadStore;
})(typeof window !== 'undefined' ? window : globalThis);
