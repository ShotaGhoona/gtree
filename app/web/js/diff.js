// git diff の文字を表にする。rows には「選べる行」ごとの中身を入れる（行のコピーで使う）
const META=/^(diff --git|index |--- |\+\+\+ |new file|deleted file|similarity|rename |old mode|new mode)/;
const NO_DIFF='<div class="empty">差分はありません（バイナリか、空ファイルです）</div>';

// 1行ずつ { hunk } / { bin } / { k:'+'|'-'|' ', o:元の行番号, n:今の行番号, t:中身 } にする
function parseDiff(text){
  const out=[]; let o=0, n=0;
  for(const l of (text||'').split('\n')){
    if(META.test(l)||l.startsWith('\\')) continue;
    const m=l.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if(m){ o=+m[1]; n=+m[2]; out.push({hunk:l}); continue; }
    if(l.startsWith('Binary')){ out.push({bin:true}); continue; }
    const k=l[0], t=l.slice(1);
    if(k==='+') out.push({k,n:n++,t});
    else if(k==='-') out.push({k,o:o++,t});
    else if(k===' ') out.push({k,o:o++,n:n++,t});
  }
  return out;
}
// 今のファイルで変わった行の行番号（「ファイル全体」の色付けに使う）
const addedLines=text=>new Set(parseDiff(text).filter(e=>e.k==='+').map(e=>e.n));

function diffTable(text,rows=[]){
  if(!text||!text.trim()) return NO_DIFF;
  const h=parseDiff(text).map(e=>{
    if(e.hunk!=null) return `<tr class="h"><td class="n"></td><td class="n"></td><td class="c">${esc(e.hunk)}</td></tr>`;
    if(e.bin) return '<tr class="h"><td class="n"></td><td class="n"></td><td class="c">バイナリファイル</td></tr>';
    const i=rows.push([e])-1, cls=e.k==='+'?'a':e.k==='-'?'r':'';
    return `<tr class="${cls}" data-i="${i}"><td class="n">${e.o??''}</td><td class="n">${e.n??''}</td><td class="c">${e.k}${esc(e.t)}</td></tr>`;
  });
  return `<table class="d">${h.join('')}</table>`;
}

function diffSplit(text,rows=[]){
  if(!text||!text.trim()) return NO_DIFF;
  const out=[]; let dels=[], adds=[];
  const cell=(e,cls)=>e?`<td class="n ${cls}">${cls==='a'?e.n:e.o}</td><td class="c ${cls}">${esc(e.t)}</td>`:'<td class="n e"></td><td class="c e"></td>';
  // 続けて消した行と足した行を、左右に1段ずつ並べる
  const flush=()=>{
    for(let i=0;i<Math.max(dels.length,adds.length);i++){
      const d=dels[i], a=adds[i];
      out.push(`<tr data-i="${rows.length}">${cell(d,'r')}${cell(a,'a')}</tr>`);
      rows.push([d,a].filter(Boolean));
    }
    dels=[]; adds=[];
  };
  for(const e of parseDiff(text)){
    if(e.k==='-'){ dels.push(e); continue; }
    if(e.k==='+'){ adds.push(e); continue; }
    flush();
    if(e.hunk!=null) out.push(`<tr class="h"><td class="n"></td><td class="c" colspan="3">${esc(e.hunk)}</td></tr>`);
    else if(e.bin) out.push('<tr class="h"><td class="n"></td><td class="c" colspan="3">バイナリファイル</td></tr>');
    else{ const t=esc(e.t); out.push(`<tr data-i="${rows.length}"><td class="n ">${e.o}</td><td class="c ">${t}</td><td class="n ">${e.n}</td><td class="c ">${t}</td></tr>`); rows.push([e]); }
  }
  flush();
  return `<table class="d s"><colgroup><col style="width:52px"><col><col style="width:52px"><col></colgroup>${out.join('')}</table>`;
}
