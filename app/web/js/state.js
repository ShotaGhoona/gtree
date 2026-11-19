// 画面の状態と、/api/tree の読み込み（5秒ごと）
const _v0=LS.get('gt.view','split');
let DATA=null, RAW='', sel=LS.get('gt.sel',null), closed=new Set(LS.get('gt.closed',[])), loadedDirs={},
    view=_v0==='file'?'diff':_v0, cmp=LS.get('gt.cmp','stage'), filter=LS.get('gt.filter','all'),
    lastAt=0, busy=false, prevKeys=null, freshKeys=new Set();

// manual=true のときは PR の状態もすぐ読み直してもらう
async function load(manual){
  if(busy) return; busy=true; $('#dot').classList.add('busy');
  try{
    const txt=await (await fetch('/api/tree'+(manual?'?pr=1':''))).text(); lastAt=Date.now();
    if(txt===RAW) return;
    const first=!RAW; RAW=txt; DATA=JSON.parse(txt).repos;
    markFresh(first); loadedDirs={}; render();
    if(first&&openFromURL()) return;
    if(sel){
      const wt=DATA.flatMap(r=>r.worktrees).find(w=>w.path===sel.wt);
      const f=wt&&wt.files.find(x=>x.path===sel.path); if(f) sel.f={...f};
      show(sel,{keep:!first});
    }
  }finally{ busy=false; $('#dot').classList.remove('busy'); tick(); }
}
// 前回から変わったファイルに印を付ける
function markFresh(first){
  const keys=new Map();
  for(const r of DATA) for(const w of r.worktrees) for(const f of w.files) keys.set(w.path+'::'+f.path,f.add+'/'+f.del+'/'+f.kind+'/'+(f.sx||''));
  if(prevKeys&&!first) for(const [k,v] of keys) if(prevKeys.get(k)!==v) freshKeys.add(k);
  prevKeys=keys;
}
// ?open=パス&branch=ブランチ で最初に開くファイルを指定できる
function openFromURL(){
  const q=new URLSearchParams(location.search), op=q.get('open'), br=q.get('branch'); if(!op) return false;
  const r=[...document.querySelectorAll('.row[data-key]')].find(x=>{ const i=INFO[x.dataset.p]; return i&&i.path===op&&(!br||i.branch===br); });
  if(!r) return false; sel=null; r.click(); return true;
}
function tick(){ if(!lastAt) return; const s=Math.round((Date.now()-lastAt)/1000); $('#ago').textContent=s<3?'最新':s+'秒前'; }
