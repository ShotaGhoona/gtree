// 行番号をクリック・ドラッグ（shift＋クリックで広げる）して行を選び、⌘C で「パス:行」と中身をコピーする
let LROWS=[], LSEL=null, ldrag=false;

// 表示を描き直したとき：同じファイル・同じ表示なら選択を残す
function setLineRows(rows,key){
  LROWS=rows;
  if(LSEL&&(LSEL.key!==key||LSEL.view!==view||LSEL.b>=rows.length)) LSEL=null;
  paintL();
}
function clearLines(){ if(LSEL){ LSEL=null; paintL(); } }
function paintL(){
  const a=LSEL?Math.min(LSEL.a,LSEL.b):-1, b=LSEL?Math.max(LSEL.a,LSEL.b):-2;
  $('#body').querySelectorAll('[data-i]').forEach(r=>{ const i=+r.dataset.i; r.classList.toggle('lsel',i>=a&&i<=b); });
}
function lineText(){
  if(!LSEL||!sel||LSEL.key!==sel.key) return null;
  const a=Math.min(LSEL.a,LSEL.b), b=Math.max(LSEL.a,LSEL.b);
  // 左右表示では - と + が同じ段に並ぶので、差分の順（消した行 → 足した行）に並べ直す
  const out=[]; let dels=[], adds=[]; const fl=()=>{ out.push(...dels,...adds); dels=[]; adds=[]; };
  for(const r of LROWS.slice(a,b+1)) for(const e of r){ if(e.k==='-') dels.push(e); else if(e.k==='+') adds.push(e); else { fl(); out.push(e); } }
  fl(); if(!out.length) return null;
  // 行番号は今のファイルのもの。消した行だけを選んだときは元のファイルの行番号
  const nn=out.filter(e=>e.k!=='-').map(e=>e.n), nums=nn.length?nn:out.map(e=>e.o);
  const lo=Math.min(...nums), hi=Math.max(...nums), at=`${sel.path}:${lo===hi?lo:lo+'-'+hi}${nn.length?'':'（変更前）'}`;
  // 消した行が混じるときだけ、+ / - を付けた差分の形にする
  const diff=out.some(e=>e.k==='-');
  return {at, text:at+'\n'+out.map(e=>(diff?e.k:'')+e.t).join('\n')};
}
function copyLines(){ const t=lineText(); if(!t) return false; copyText(t.text,`${t.at} をコピーしました`); return true; }

$('#body').addEventListener('mousedown',e=>{
  const g=e.target.closest('td.n,i.g'), r=g&&g.closest('[data-i]');
  if(!r){ if(e.button===0) clearLines(); return; }
  e.preventDefault(); getSelection().removeAllRanges();
  const i=+r.dataset.i;
  if(e.shiftKey&&LSEL&&LSEL.key===sel?.key) LSEL.b=i; else LSEL={key:sel?.key,view,a:i,b:i};
  ldrag=true; paintL();
});
$('#body').addEventListener('mouseover',e=>{ if(!ldrag) return; const r=e.target.closest('[data-i]'); if(r&&LSEL){ LSEL.b=+r.dataset.i; paintL(); } });
document.addEventListener('mouseup',()=>{ if(!ldrag) return; ldrag=false; const t=lineText(); if(t) toast(`${t.at} を選択中（⌘C でコピー）`); });
