// 右クリックのメニューと、git に書き込む操作（staged にする／外す、worktree を閉じる）
function closeMenu(){ $('#cmenu')?.remove(); }
function openMenu(e,html,onpick){
  closeMenu();
  const m=el('div',null,html); m.id='cmenu'; document.body.append(m);
  m.style.left=Math.min(e.clientX,innerWidth-m.offsetWidth-8)+'px';
  m.style.top=Math.min(e.clientY,innerHeight-m.offsetHeight-8)+'px';
  m.querySelectorAll('button').forEach(b=>b.onclick=()=>{ closeMenu(); onpick(b.dataset); });
}

// ---- ファイル・フォルダ：パスのコピーと staged
function fmt(i,kind){
  const tail=i.dir?'/':'';
  if(kind==='repo') return i.repo+'/'+i.path+tail;
  if(kind==='rel') return i.path+tail;
  if(kind==='abs') return i.wt+'/'+i.path+tail;
  if(kind==='remote') return i.remote?`${i.remote}/${i.dir?'tree':'blob'}/${i.branch.split('/').map(encodeURIComponent).join('/')}/${i.path.split('/').map(encodeURIComponent).join('/')}`:'';
}
function copy(kind){
  const list=selected(); if(!list.length) return;
  copyText(list.map(i=>fmt(i,kind)).filter(Boolean).join('\n'),`${list.length}件のパスをコピーしました`);
}
function fileMenu(e,r){
  if(!msel.has(r.dataset.p)){ msel=new Set([r.dataset.p]); anchor=r.dataset.p; paintSel(); }
  const list=selected(), first=list[0];
  const item=(k,label)=>`<button data-k="${k}"><span>${label}</span><span class="ex">${esc(fmt(first,k)||'')}</span></button>`;
  openMenu(e,`<div class="mh">${list.length}件を選択中</div>${item('repo','リポジトリ名からのパス')}${item('rel','相対パス')}${item('abs','絶対パス')}${list.some(i=>i.remote)?item('remote','リモートの URL'):''}<div class="sep"></div><button data-op="add"><span>staged にする（s）</span></button><button data-op="unstage"><span>staged を外す</span></button>`,
    d=>d.op?stageOp(d.op):copy(d.k));
}
async function stageOp(op,src){
  // 右クリックと s キーは左で選んでいるもの（フォルダを含む）、見出しのボタンは開いているファイルが対象
  const list=src==='head'&&msel.size<=1?(sel?[{wt:sel.wt,path:sel.path}]:[]):selected();
  if(!list.length) return;
  const r=await postJSON('/api/stage',{op,items:list.map(i=>({wt:i.wt,f:i.path}))});
  toast(r.ok?(op==='add'?`${list.length}件を staged にしました`:`${list.length}件の staged を外しました`):'失敗しました');
  RAW=''; await load();
}

// ---- worktree の見出し：PR と「閉じてOK」
const prLine=p=>`${p.title}\n${p.url}`;
function wtMenu(e,wt){
  const all=DATA.flatMap(r=>r.worktrees), ok=all.filter(w=>w.closable), open=all.filter(w=>w.pr&&w.pr.state==='OPEN'&&!w.pr.draft);
  const b=[];
  if(wt.pr) b.push(`<button data-a="open"><span>PR を開く</span><span class="ex">#${wt.pr.number} ${esc(wt.pr.title)}</span></button>`,'<button data-a="copy"><span>title とリンクをコピー</span></button>');
  if(open.length) b.push(`<button data-a="copyall"><span>レビュー待ちの PR をまとめてコピー（${open.length} 件）</span></button>`);
  if(wt.closable||ok.length>1) b.push('<div class="sep"></div>');
  if(wt.closable) b.push(`<button data-a="rm"><span>worktree を閉じる（ブランチは残す）</span><span class="ex">${esc(wt.short)}</span></button>`);
  if(ok.length>1) b.push(`<button data-a="rmall"><span>閉じてOK をまとめて閉じる（${ok.length} 件）</span></button>`);
  openMenu(e,`<div class="mh">${esc(wt.branch)}</div>${b.join('')||'<div class="mh">PR が見つかりません</div>'}`,({a})=>{
    if(a==='open') window.open(wt.pr.url,'_blank','noopener');
    if(a==='copy') copyText(prLine(wt.pr),`#${wt.pr.number} の title とリンクをコピーしました`);
    if(a==='copyall') copyText(open.map(w=>prLine(w.pr)).join('\n\n'),`${open.length}件の PR をコピーしました`);
    if(a==='rm') removeWts([wt]);
    if(a==='rmall') removeWts(ok);
  });
}
async function removeWts(list){
  if(!confirm(`${list.length}件の worktree を閉じます。\n\n${list.map(w=>w.short).join('\n')}\n\nフォルダは消えます。ブランチは残るので、あとから戻せます。`)) return;
  const r=await postJSON('/api/wt-remove',{wts:list.map(w=>w.path)});
  const errs=r.ok?(await r.json()).errors:{x:'失敗しました'}, n=Object.keys(errs).length;
  toast(n?`閉じられなかったものがあります：${Object.values(errs)[0]}`:`${list.length}件の worktree を閉じました`);
  RAW=''; await load();
}

document.addEventListener('contextmenu',e=>{
  const wh=e.target.closest('.wt-h[data-wt]');
  if(wh&&WTMAP[wh.dataset.wt]){ e.preventDefault(); return wtMenu(e,WTMAP[wh.dataset.wt]); }
  const r=e.target.closest('.row[data-p]');
  if(r){ e.preventDefault(); fileMenu(e,r); }
});
document.addEventListener('mousedown',e=>{ if(!e.target.closest('#cmenu')) closeMenu(); });
