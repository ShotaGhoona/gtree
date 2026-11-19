// 左のツリー：リポジトリ → worktree → フォルダ → ファイル
const INFO={}, WTMAP={};
let msel=new Set(), anchor=null;

function buildTree(files){
  const root={d:{},f:[]};
  for(const f of files){
    const parts=f.path.split('/'); let n=root;
    for(const p of parts.slice(0,-1)) n=n.d[p]??=({d:{},f:[]});
    const last=parts[parts.length-1];
    if(f.dir) n.d[last]={d:{},f:[],udir:f}; else n.f.push({...f,name:last});
  }
  return root;
}
function passFilter(f){
  const q=$('#q').value.trim().toLowerCase();
  if(filter==='wip'&&f.kind==='commit') return false;
  if(filter==='commit'&&f.kind==='wip') return false;
  return !q||f.path.toLowerCase().includes(q);
}
function countFiles(n){ let c=n.f.length+(n.udir?(n.udir.count||0):0); for(const k in n.d) c+=countFiles(n.d[k]); return c; }
function saveClosed(){ LS.set('gt.closed',[...closed]); }
function toggle(key){ closed.has(key)?closed.delete(key):closed.add(key); saveClosed(); render(); }

// ---- 行と複数選択（クリック／shift／cmd）
function row(depth,html,cls,key,onclick,info){
  const d=el('div','row '+(cls||''),html); d.style.paddingLeft=(6+depth*14)+'px';
  if(key) d.dataset.key=key;
  if(info){ const p=info.wt+'::'+info.path+(info.dir?'/':''); d.dataset.p=p; INFO[p]=info; if(msel.has(p)) d.classList.add('msel'); }
  d.onclick=e=>clickRow(e,d,onclick); return d;
}
function paintSel(){ document.querySelectorAll('.row[data-p]').forEach(r=>r.classList.toggle('msel',msel.has(r.dataset.p))); }
function clickRow(e,d,action){
  const p=d.dataset.p;
  if(p&&(e.metaKey||e.ctrlKey)){ msel.has(p)?msel.delete(p):msel.add(p); anchor=p; paintSel(); return; }
  if(p&&e.shiftKey&&anchor){
    const rows=[...document.querySelectorAll('.row[data-p]')].map(r=>r.dataset.p), a=rows.indexOf(anchor), b=rows.indexOf(p);
    if(a>=0&&b>=0){ msel=new Set(rows.slice(Math.min(a,b),Math.max(a,b)+1)); paintSel(); return; }
  }
  if(p){ msel=new Set([p]); anchor=p; paintSel(); }
  action&&action(e);
}
function selected(){ return [...document.querySelectorAll('.row[data-p]')].map(r=>r.dataset.p).filter(p=>msel.has(p)).map(p=>INFO[p]); }

// ---- フォルダとファイル
const rowInfo=(wt,path,dir)=>({wt:wt.path,repo:wt._repo,branch:wt.branch,remote:wt._remote,path,dir});
function renderDir(box,wt,node,depth,prefix){
  for(let name of Object.keys(node.d).sort()){
    let child=node.d[name], full=prefix+name;
    // 子が1つだけのフォルダは a/b/c のようにまとめる
    while(!child.udir&&child.f.length===0&&Object.keys(child.d).length===1){
      const k=Object.keys(child.d)[0]; name+='/'+k; full+='/'+k; child=child.d[k];
    }
    const key=wt.path+'::'+full+'/';
    if(child.udir){ renderNewDir(box,wt,child,depth,name,full,key); continue; }
    const isClosed=closed.has(key);
    const sub=el('div'); renderDir(sub,wt,child,depth+1,full+'/');
    if(!sub.childElementCount) continue;
    box.append(row(depth,`<span class="tw">${isClosed?'▸':'▾'}</span><span class="nm dir">${esc(name)}/</span><span class="cnt">${countFiles(child)}</span>`,'',null,()=>toggle(key),rowInfo(wt,full,true)));
    if(!isClosed) box.append(...sub.childNodes);
  }
  for(const f of node.f.sort((a,b)=>a.name.localeCompare(b.name))){
    const path=prefix+f.name, ff={...f,path};
    if(passFilter(ff)) box.append(fileRow(wt,f,ff,path,depth));
  }
}
// 新しい（未追跡の）フォルダは、開いたときに中身を読みに行く
function renderNewDir(box,wt,child,depth,name,full,key){
  const open=closed.has(key+'!open'), list=loadedDirs[key];
  box.append(row(depth,`<span class="tw">${open?'▾':'▸'}</span><span class="nm st-A" title="新しいフォルダ">${esc(name)}/</span><span class="cnt">${child.udir.count||0}</span>`,'',null,async()=>{
    open?closed.delete(key+'!open'):closed.add(key+'!open'); saveClosed();
    if(!open&&!loadedDirs[key]) await loadDir(wt,full,key); render();
  },rowInfo(wt,full,true)));
  if(open&&list){
    const sub=buildTree(list.map(p=>({path:p.slice(full.length+1),st:'A',kind:'wip',untracked:true,add:'',del:''})));
    renderDir(box,wt,sub,depth+1,full+'/');
  } else if(open) loadDir(wt,full,key).then(render);
}
async function loadDir(wt,d,key){ loadedDirs[key]=await (await fetch('/api/ls?'+new URLSearchParams({wt:wt.path,d}))).json(); }
function fileRow(wt,f,ff,path,depth){
  const key=wt.path+'::'+path;
  const stat=f.add&&f.add!=='-'?`<span class="cnt"><span class="st-A">+${f.add}</span> <span class="st-D">−${f.del}</span></span>`:'<span class="cnt"></span>';
  const dot=f.kind==='commit'?'<span class="wd cm" title="commit 済み"></span>':f.sx==='all'?'<span class="wd ok" title="staged 済み（確認済み）"></span>':'<span class="wd" title="まだ staged していない変更あり"></span>';
  return row(depth,`<span class="tw">${dot}</span><span class="nm st-${f.st}" title="${ST[f.st]||''}">${esc(f.name)}</span>${stat}`,
    (sel&&sel.key===key?'sel ':'')+(freshKeys.has(key)?'new':''),key,
    ()=>{ freshKeys.delete(key); show({key,wt:wt.path,path,f:ff,repo:wt._repo,branch:wt.branch},{scroll:true}); },rowInfo(wt,path,false));
}

// ---- worktree の見出しに並べる印
const CI={ok:['✓','CI 成功','ci-ok'],fail:['✗','CI 失敗','ci-fail'],run:['●','CI 実行中','ci-run']};
function prState(p){
  if(p.state==='MERGED') return ['マージ済み','mg']; if(p.state==='CLOSED') return ['閉じた','cl'];
  if(p.draft) return ['下書き','dr']; if(p.review==='APPROVED') return ['承認済み','ap']; if(p.review==='CHANGES_REQUESTED') return ['修正依頼','ch'];
  return ['レビュー待ち',''];
}
function prChip(p){
  if(!p) return '';
  const [label,cls]=prState(p), ci=p.state==='OPEN'&&CI[p.ci];
  return `<a class="prc ${cls}" href="${esc(p.url)}" target="_blank" title="${esc(`#${p.number} ${p.title}\n${label}${ci?' · '+ci[1]:''}（クリックで開く）`)}">#${p.number} ${label}${ci?`<span class="${ci[2]}">${ci[0]}</span>`:''}</a>`;
}
function wtChips(wt){
  const nw=wt.files.filter(f=>f.kind!=='commit').length, nc=wt.files.filter(f=>f.kind!=='wip').length;
  const ports=(wt.ports||[]).map(p=>`<a class="port" href="http://localhost:${p.port}" target="_blank" title="${esc(p.cmd)} が http://localhost:${p.port} で動いています（クリックで開く）"><span class="pd"></span>:${p.port}</a>`).join('');
  const push=wt.ahead>0?`<span class="chip w" title="まだ push していないコミットが ${wt.ahead} 個あります">未push ${wt.ahead}</span>`
    :wt.ahead===null?'<span class="chip w" title="このブランチはまだ push していません">未push</span>':'';
  const ok=wt.closable?'<span class="chip ok" title="PR はマージ済み・未コミットの変更なし・push 済み・stash なし・開発サーバーも止まっています。右クリックで閉じられます">閉じてOK</span>':'';
  return ports+prChip(wt.pr)+push+ok+(wt.missing?'<span class="chip">フォルダなし</span>':'')
    +(nw?`<span class="chip w">未 ${nw}</span>`:'')+(nc&&!ok?`<span class="chip">済 ${nc}</span>`:'');
}

// ---- 全体
function repoHead(repo,i,rc){
  const color=repo.color||COLORS[i%COLORS.length];
  const short=(n=>n.length<=3?n:n.slice(0,2))(repo.name.replace(/^[^-]+-/,'')).toUpperCase();
  const icon=repo.icon?`<img class="rl" src="/api/icon?r=${encodeURIComponent(repo.name)}" width="30" height="26" alt="">`:`<span class="ic" style="background:${color}">${esc(short)}</span>`;
  return el('div','repo-h',`${icon}<span class="nm">${esc(repo.name)}</span><span class="base">${esc((repo.base||'').replace('origin/',''))}</span><span class="chev">${rc?'▸':'▾'}</span>`);
}
function wtCard(repo,wt){
  wt._repo=repo.name; wt._remote=repo.remote; WTMAP[wt.path]=wt;
  const wk='wt::'+wt.path, wc=closed.has(wk);
  const card=el('div','wt');
  const head=el('div','wt-h'+(wt===repo.worktrees[0]?' is-main':''),`<span class="tw">${wc?'▸':'▾'}</span>${BRANCH}<span class="br">${esc(wt.branch)}</span><span class="chips">${wtChips(wt)}</span>`);
  head.title=wt.path; head.dataset.wt=wt.path;
  head.onclick=e=>{ if(!e.target.closest('.port,.prc')) toggle(wk); };
  card.append(head);
  if(!wc&&!wt.missing&&wt.files.length){
    const b=el('div','wt-b'); renderDir(b,wt,buildTree(wt.files),0,'');
    if(!b.childElementCount) b.append(el('div','repo-empty','この絞り込みでは該当なし'));
    card.append(b);
  }
  return card;
}
function render(){
  const tree=$('#tree'), top=tree.scrollTop; tree.innerHTML='';
  DATA.forEach((repo,i)=>{
    const rk='repo::'+repo.name, rc=closed.has(rk);
    const sec=el('div','repo-sec'); sec.style.setProperty('--c',repo.color||COLORS[i%COLORS.length]); tree.append(sec);
    const h=repoHead(repo,i,rc); h.onclick=()=>toggle(rk); sec.append(h);
    if(rc) return;
    // 変更・ポート・PR のどれかがある worktree だけ出す
    const live=repo.worktrees.filter(w=>w.files.length||w.missing||(w.ports&&w.ports.length)||w.pr);
    if(!live.length){ sec.append(el('div','repo-empty','変更なし')); return; }
    live.forEach(wt=>sec.append(wtCard(repo,wt)));
  });
  tree.scrollTop=top;
}
