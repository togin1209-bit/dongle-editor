/** DONGLE Studio v1.9.5 — non-invasive 3-product production helper */
window.DongleProductionAdapter={
  getProductProfile(id){const p={indoor_banner:{name:'실내용배너',bleedMm:1,recommendedDpi:300},outdoor_banner:{name:'실외용배너',bleedMm:1,recommendedDpi:300},banner:{name:'현수막',bleedMm:1,recommendedDpi:150},hyeonsumak:{name:'현수막',bleedMm:1,recommendedDpi:150}};return p[id]||null;},
  calculateWorkingSize(id,w,h){const p=this.getProductProfile(id);if(!p)return null;return{workingWidth:Number(w)+p.bleedMm*2,workingHeight:Number(h)+p.bleedMm*2};},
  validateProductSize(id,w,h){w=Number(w);h=Number(h);if(!(w>0&&h>0))return{status:'BLOCK',message:'가로/세로를 확인하세요.'};if(id==='banner'||id==='hyeonsumak'){const s=Math.min(w,h),l=Math.max(w,h);if(w<30||h<30)return{status:'BLOCK',message:'각 변은 최소 30mm 이상이어야 합니다.'};if(s>1800||l>49100)return{status:'BLOCK',message:'현수막 최대 제작 가능 규격을 초과했습니다.'};return{status:'PASS',message:'제작 가능한 규격입니다.'};}return{status:'PASS',message:'입력 규격입니다.',partial:true};},
  calculateEffectiveResolution(asset,printSize){if(!asset||!printSize)return 0;const pw=Number(asset.pixelWidth),ph=Number(asset.pixelHeight),w=Number(printSize.widthMm),h=Number(printSize.heightMm);if(!(pw>0&&ph>0&&w>0&&h>0))return 0;return Math.round(Math.min(pw/(w/25.4),ph/(h/25.4))*10)/10;}
};
