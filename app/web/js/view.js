// 右側：開いているファイルの見出しと、差分／ファイル全体の表示
function headHTML(s,eff,canView){
  const f=s.f;
  const kind={commit:'commit済',wip:f.untracked?'新規（未追跡）':'未コミット',both:'commit済 + 未コミット'}[f.kind]
    +(f.sx==='all'?' · staged 済み':f.sx==='more'?' · staged の後に変更あり':'');
  const canStage=f.kind!=='commit'&&f.sx!=='all', canUnstage=!!f.sx;
  const stat=f.add&&f.add!=='-'?`<span class="st-A">+${f.add}</span> <span class="st-D">−${f.del}</span>`:'';
  const on=(a,b)=>a===b?'on':'';
  const cmpSeg=f.sx==='more'?`<span class="vs cmp" style="margin-left:auto" title="何と比べるか"><button data-c="stage" class="${on(eff,'stage')}" title="staged した版から、その後の変更だけ">staged から</button><button data-c="base" class="${on(eff,'base')}" title="ベースブランチからの変更すべて">ベースから</button></span>`:'';
  const modeSeg=`<span class="vs mode"${f.sx==='more'?' style="margin-left:0"':''}><button data-m="diff" class="${on(view,'diff')}">1列</button><button data-m="split" class="${on(view,'split')}">左右</button>${canView?`<button data-m="file" class="${on(view,'file')}">ファイル全体</button>`:''}</span>`;
  const stg=canStage?'<button class="stg pri" data-op="add" title="確認済みの印として staged にする（s）">staged にする</button>'
    :canUnstage?'<button class="stg" data-op="unstage" title="staged を外す">staged を外す</button>':'';
  return `<div class="crumb">${esc(s.repo||'')} <span>›</span> ${BRANCH} ${esc(s.branch||'')}</div>
   <div class="line2"><span class="p st-${f.st}" title="${esc((ST[f.st]||'')+'：'+s.path)}"><span dir="ltr">${esc(s.path)}</span></span>${stat}<span class="crumb">${kind}</span>
   ${cmpSeg}${modeSeg}${stg}</div>`;
}

async function show(s,opt={}){
  sel=s; LS.set('gt.sel',s);
  document.querySelectorAll('.row.sel').forEach(e=>e.classList.remove('sel'));
  const r=document.querySelector(`.row[data-key="${CSS.escape(s.key)}"]`); r?.classList.add('sel');
  if(opt.scroll) r?.scrollIntoView({block:'nearest'});
  const f=s.f, canView=f.st!=='D';
  const eff=f.sx==='more'&&cmp==='stage'?'stage':'base';  // 何と比べるか
  const head=$('#head'); head.hidden=false; head.innerHTML=headHTML(s,eff,canView);
  head.querySelectorAll('.vs.mode button').forEach(b=>b.onclick=()=>{ view=b.dataset.m; LS.set('gt.view',view); show(sel); });
  head.querySelectorAll('.vs.cmp button').forEach(b=>b.onclick=()=>{ cmp=b.dataset.c; LS.set('gt.cmp',cmp); show(sel); });
  head.querySelectorAll('.stg').forEach(b=>b.onclick=()=>stageOp(b.dataset.op,'head'));

  const body=$('#body'), keepTop=opt.keep?body.scrollTop:0;
  const q=new URLSearchParams({wt:s.wt,f:s.path});
  const dq=new URLSearchParams(q); if(f.untracked) dq.set('u','1'); if(eff==='stage') dq.set('m','stage');
  const rows=[], imgHTML=`<div class="img"><img src="/api/raw?${q}&t=${Date.now()}"></div>`;
  let html, keepFrame=false;
  if(canView&&IMG.test(s.path)) html=imgHTML;
  else if(view==='file'&&canView&&HTML.test(s.path)){
    // 別のサイトとして動かす（sandbox）。中身が変わったときだけ読み込み直して、スクロール位置を保つ
    const t=await fetch('/api/raw?'+q).then(r=>r.text()), fr=body.querySelector('iframe.htmlv');
    keepFrame=opt.keep&&fr&&fr.dataset.key===s.key&&fr._t===t;
    html=`<iframe class="htmlv" sandbox="allow-scripts allow-forms allow-popups allow-modals" data-key="${esc(s.key)}" src="${rawPath(s.wt,s.path)}?t=${Date.now()}"></iframe>`;
    body._t=t;
  }
  else if(view==='file'&&canView){
    // 色を付けるのは「まだ見ていない変更」だけ。全部 staged 済みなら付けない。ベースと比べて丸ごと新しいファイルも、全体が塗られるだけなので付けない
    const hl=!f.untracked&&f.sx!=='all'&&(eff==='stage'||f.st!=='A');
    const [t,d]=await Promise.all([fetch('/api/raw?'+q).then(r=>r.text()), hl?fetch('/api/diff?'+dq).then(r=>r.json()):null]);
    const chg=d?addedLines(d.diff):new Set();
    html=MD.test(s.path)&&window.marked?`<div class="md">${mdMarked(t,chg)}</div>`:rawHTML(t,chg,rows);
  }
  else{
    const d=await (await fetch('/api/diff?'+dq)).json();
    html=(view==='split'?diffSplit(d.diff,rows):diffTable(d.diff,rows))+(d.truncated?'<div class="empty">長いので途中で切っています</div>':'');
  }
  if(sel!==s||keepFrame) return;  // 待っている間に別のファイルを開いた／HTML が変わっていない

  body.innerHTML=html; setLineRows(rows,s.key);
  const fr=body.querySelector('iframe.htmlv'); if(fr) fr._t=body._t;
  fixMdImages(body,s);
  body.scrollTop=keepTop;
}
// 行番号付きのそのままの文字
function rawHTML(t,chg,rows){
  return `<pre class="raw">${t.split('\n').map((l,i)=>{
    rows.push([{k:' ',o:i+1,n:i+1,t:l}]);
    return `<span class="ln${chg.has(i+1)?' chg':''}" data-i="${i}"><i class="g">${i+1}</i>${esc(l)||' '}</span>`;
  }).join('')}</pre>`;
}
// md の中の相対パスの画像を、GTREE から読めるようにする
function fixMdImages(body,s){
  const dir=s.path.includes('/')?s.path.slice(0,s.path.lastIndexOf('/')+1):'';
  body.querySelectorAll('.md img').forEach(img=>{
    const src=img.getAttribute('src')||''; if(/^(https?:|data:|\/)/.test(src)) return;
    const parts=[]; for(const p of (dir+decodeURI(src)).split('/')){ if(p==='..') parts.pop(); else if(p&&p!=='.') parts.push(p); }
    img.src='/api/raw?'+new URLSearchParams({wt:s.wt,f:parts.join('/')});
  });
}
// md を整形しつつ、変わった行を含むかたまりに色を付ける
function mdMarked(t,chg){
  let ln=1, out='';
  const hit=(from,n)=>{ for(let i=from;i<from+n;i++) if(chg.has(i)) return true; return false; };
  const fm=t.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n/); // 先頭のメタ情報（front matter）はそのままの文字で出す
  if(fm){
    const n=(fm[0].match(/\n/g)||[]).length;
    const h=`<pre class="fm">${esc(fm[0].replace(/^---\r?\n|\r?\n---\r?\n$/g,''))}</pre>`;
    out+=hit(1,n)?`<div class="chg">${h}</div>`:h; ln+=n; t=t.slice(fm[0].length);
  }
  if(!chg.size) return out+marked.parse(t);
  const toks=marked.lexer(t);
  for(const tk of toks){
    const raw=tk.raw||'', body=raw.replace(/\n+$/,''), n=body?body.split('\n').length:0;
    const one=[tk]; one.links=toks.links; const h=marked.parser(one);
    out+=hit(ln,n)?`<div class="chg">${h}</div>`:h;
    ln+=(raw.match(/\n/g)||[]).length;
  }
  return out;
}
