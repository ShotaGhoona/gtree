// キー操作・絞り込み・左右の幅を整えて、読み込みを始める
function step(dir){
  const rows=[...document.querySelectorAll('.row[data-key]')]; if(!rows.length) return;
  const i=rows.findIndex(r=>r.classList.contains('sel')); rows[Math.max(0,Math.min(rows.length-1,i+dir))]?.click();
}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'){ if(e.key==='Escape') e.target.blur(); return; }
  const mod=e.metaKey||e.ctrlKey;
  // ⌘C：文字を選んでいなければ、選んだ行 → 左で選んだファイルのパス の順でコピー
  if(mod&&e.key==='c'&&!getSelection().toString()){
    if(copyLines()) e.preventDefault();
    else if(msel.size){ e.preventDefault(); copy('repo'); }
    return;
  }
  if(e.key==='Escape'){
    clearLines(); closeMenu();
    if(msel.size>1){ msel=new Set(sel?[sel.wt+'::'+sel.path]:[]); paintSel(); }
  }
  if(mod) return;
  if(e.key==='j'||e.key==='ArrowDown'){ step(1); e.preventDefault(); }
  if(e.key==='k'||e.key==='ArrowUp'){ step(-1); e.preventDefault(); }
  if(e.key==='/'){ $('#q').focus(); e.preventDefault(); }
  if(e.key==='r'){ RAW=''; load(true); }
  if(e.key==='s') stageOp('add');
});
$('#q').addEventListener('input',render);
$('#seg').querySelectorAll('button').forEach(b=>{
  b.classList.toggle('on',b.dataset.v===filter);
  b.onclick=()=>{ filter=b.dataset.v; LS.set('gt.filter',filter); $('#seg').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b)); render(); };
});
// 左右の境目をドラッグして、左の幅を変える
(()=>{
  const app=$('#app'); app.style.setProperty('--lw',LS.get('gt.lw',340)+'px');
  $('#drag').onmousedown=e=>{
    e.preventDefault();
    const mv=ev=>{ const x=Math.max(220,Math.min(800,ev.clientX)); app.style.setProperty('--lw',x+'px'); LS.set('gt.lw',x); };
    document.addEventListener('mousemove',mv);
    document.addEventListener('mouseup',()=>document.removeEventListener('mousemove',mv),{once:true});
  };
})();

setInterval(tick,1000);
setInterval(()=>{ if(document.visibilityState==='visible') load(); },5000);
document.addEventListener('visibilitychange',()=>{ if(document.visibilityState==='visible') load(); });
load();
