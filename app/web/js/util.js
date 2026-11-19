// どこからでも使う小さな道具と定数
const $=s=>document.querySelector(s);
const LS={get(k,d){try{return JSON.parse(localStorage.getItem(k))??d}catch{return d}},set(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch{}}};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function el(tag,cls,html){ const e=document.createElement(tag); if(cls) e.className=cls; if(html!=null) e.innerHTML=html; return e; }

const IMG=/\.(png|jpe?g|gif|webp|svg)$/i, MD=/\.mdx?$/i, HTML=/\.html?$/i;
const ST={A:'追加（新しいファイル）',M:'変更',D:'削除',R:'名前の変更'};
const COLORS=['#3cadba','#f2b51d','#9a7ad8','#2f6fb0','#d16ba5'];
const BRANCH='<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="4" cy="3.5" r="1.6"/><circle cx="4" cy="12.5" r="1.6"/><circle cx="12" cy="5" r="1.6"/><path d="M4 5.1v5.8M12 6.6c0 3-8 1.5-8 4.3"/></svg>';

// /raw/<worktree のパスを base64url にしたもの>/<ファイルのパス>。HTML の中の相対パスがそのまま読める形
const rawPath=(wt,f)=>'/raw/'+btoa(unescape(encodeURIComponent(wt))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')+'/'+f.split('/').map(encodeURIComponent).join('/');

const postJSON=(url,body)=>fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

function toast(msg){
  let t=$('#toast'); if(!t){ t=el('div'); t.id='toast'; document.body.append(t); }
  t.textContent=msg; t.classList.add('on'); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove('on'),1600);
}
async function copyText(text,msg){
  try{ await navigator.clipboard.writeText(text); }
  catch{ const t=el('textarea'); t.value=text; document.body.append(t); t.select(); document.execCommand('copy'); t.remove(); }
  toast(msg);
}
