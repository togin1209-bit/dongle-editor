window.API_MODE = "production";
window.ProductionAPI = {
  async _json(url, options={}) {
    const res = await fetch(url, options); const ct=res.headers.get('content-type')||'';
    const data=ct.includes('application/json')?await res.json():null;
    if(!res.ok){const e=new Error((data&&data.error)||`HTTP ${res.status}`);e.payload=data;e.status=res.status;throw e;} return data;
  },
  async getProducts(){return this._json('/api/products');},
  async getProductGroups(){return this._json('/api/product-groups');},
  async createJob(product,widthMm,heightMm,fitPolicy='contain'){
    return this._json('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product,width_mm:widthMm,height_mm:heightMm,fit_policy:fitPolicy})});
  },
  async upload(jobId,file){const fd=new FormData();fd.append('image',file);return this._json(`/api/jobs/${jobId}/upload`,{method:'POST',body:fd});},
  async preflight(jobId,payload={}){return this._json(`/api/jobs/${jobId}/preflight`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});},
  async resizeJob(jobId,widthMm,heightMm,repositionMode='PROPORTIONAL_STRETCH',objects=[]){return this._json(`/api/jobs/${jobId}/resize`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({width_mm:widthMm,height_mm:heightMm,reposition_mode:repositionMode,objects})});},
  async getGuideHelp(){return this._json('/api/guide-help');},
  async removeBackground(jobId,file){const fd=new FormData();fd.append('image',file);const r=await fetch(`/api/jobs/${jobId}/remove-background`,{method:'POST',body:fd});if(!r.ok){let j={};try{j=await r.json()}catch{};throw new Error(j.error||'배경제거 실패');}return r.blob();},
  async previewAcrylicContour(file,productId='acrylic_keyring'){const fd=new FormData();fd.append('image',file);fd.append('product_id',productId);return this._json('/api/acrylic/preview-contour',{method:'POST',body:fd});},
  async previewStandStructure(payload={}){return this._json('/api/acrylic/stand/structure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});},
  async exportPrintPdf(jobId,artworkBlob,opts={}){
    const fd=new FormData();fd.append('artwork',artworkBlob,'editor_render.png');fd.append('fit_policy',opts.fitPolicy||'contain');fd.append('force',opts.force?'true':'false');
    ['order_number','channel','customer_name','quantity','finishing','memo'].forEach(k=>{if(opts[k]!==undefined)fd.append(k,opts[k]);});
    const r=await fetch(`/api/jobs/${jobId}/export`,{method:'POST',body:fd});if(!r.ok){let j={};try{j=await r.json()}catch{};const e=new Error(j.error||'PDF 생성 실패');e.payload=j;e.status=r.status;throw e;}return r.blob();
  },
  manifestUrl(jobId){return `/api/jobs/${jobId}/manifest`;},
  async proofBlob(jobId,payload={}){const r=await fetch(`/api/jobs/${jobId}/proof`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok){let j={};try{j=await r.json()}catch{};throw new Error(j.error||'고객 시안 생성 실패');}return r.blob();},
  async packageBlob(jobId){const r=await fetch(`/api/jobs/${jobId}/package`,{method:'POST'});if(!r.ok){let j={};try{j=await r.json()}catch{};throw new Error(j.error||'Production Package 생성 실패');}return r.blob();}
};