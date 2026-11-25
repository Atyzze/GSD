(function(){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>(+v||0).toLocaleString('en-US');
  const UNDER_WAY='under way',WAITING='waiting',SETTLED='settled';
  function ladder(facts,keep){
    const by=new Map();
    const at=n=>{n=+n;if(!by.has(n))by.set(n,{n,laws:0,under_way:0,settled:{},waiting:0,scoring:0});return by.get(n)};
    for(const row of facts||[]){
      if(keep&&!keep.has(row[0]+'|'+row[1]))continue;
      const [,,rungs,word,rule,atN,nextN,score,scoreN]=row;
      for(const n of rungs||[])at(n).laws++;
      if(word===UNDER_WAY&&nextN!=null)at(nextN).under_way++;
      else if(word===SETTLED&&atN!=null){const s=at(atN).settled,k=rule||'a condition';s[k]=(s[k]||0)+1}
      else if(word===WAITING&&atN!=null)at(atN).waiting++;
      if(score>0&&scoreN!=null)at(scoreN).scoring++;
    }
    return [...by.keys()].sort((a,b)=>a-b).map(n=>by.get(n));
  }
  function deepest(row){const r=row&&row[2]||[];return r.length?Math.max(...r):null}
  function render(rows,opts){
    opts=opts||{};
    if(!rows||!rows.length)return `<div class=empty>${esc(opts.empty||'no law of the selection has a reading yet')}</div>`;
    const rules=new Map();
    for(const r of rows)for(const [k,v] of Object.entries(r.settled||{}))rules.set(k,(rules.get(k)||0)+v);
    const gates=[...rules.keys()].sort((a,b)=>rules.get(b)-rules.get(a)||a.localeCompare(b));
    const cell=v=>(+v||0)?`<b>${esc(num(v))}</b>`:'<span class=muted>0</span>';
    const sum=k=>rows.reduce((t,r)=>t+(+r[k]||0),0);
    const head=`<tr><th title="the graph size N, in nodes">size</th><th title="laws of the selection with a reading at this size">reached</th><th title="laws of the selection whose next size is this one, running or queued">running or queued</th>${gates.map(g=>`<th title="laws of the selection settled at this size by ${esc(g)}">settled: ${esc(g)}</th>`).join('')}<th title="laws of the selection read to this size and waiting to be extended past it">waiting to be extended</th><th title="laws of the selection whose score was read at this size">scoring</th></tr>`;
    const body=rows.map(r=>`<tr><td><code>N=${esc(num(r.n))}</code></td><td class=num>${cell(r.laws)}</td><td class=num>${cell(r.under_way)}</td>${gates.map(g=>`<td class=num>${cell((r.settled||{})[g])}</td>`).join('')}<td class=num>${cell(r.waiting)}</td><td class=num>${cell(r.scoring)}</td></tr>`).join('');
    const foot=`<tr class=ladder-total><td><b>all</b></td><td></td><td class=num>${cell(sum('under_way'))}</td>${gates.map(g=>`<td class=num>${cell(rules.get(g))}</td>`).join('')}<td class=num>${cell(sum('waiting'))}</td><td class=num>${cell(sum('scoring'))}</td></tr>`;
    return `<table class="ladder selection-ladder"><thead>${head}</thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table>`;
  }
  const PART_NAMES={A:'blind',N:'focus',D:'depth',system:'system'};
  function bar(values,unit,names,title){
    const parts=['A','N','D','system'],total=parts.reduce((t,p)=>t+(+values[p]||0),0);
    const whole=v=>Math.round(+v||0).toLocaleString('en-US');
    const share=v=>total>0?Math.round(100*(+v||0)/total):0;
    const track=parts.map(p=>`<span class="hours-part hours-${p==='system'?'system':p.toLowerCase()}" style="width:${total>0?(100*(+values[p]||0)/total).toFixed(2):0}%" title="${esc((names||{})[p]||p)}: ${esc(whole(values[p]))} ${esc(unit)}, ${share(values[p])}%"></span>`).join('');
    const words=parts.map(p=>`<span class="hours-word hours-${p==='system'?'system':p.toLowerCase()}-word"><b>${esc(PART_NAMES[p])}</b> ${esc(whole(values[p]))} ${esc(unit)} <span class=muted>${share(values[p])}%</span></span>`).join(' · ');
    return `<span class=hours-row title="${esc(title)}"><span class=hours-track>${track}</span><span class=hours-words>${words} · <span class=muted>${esc(whole(total))} ${esc(unit)} in all</span></span></span>`;
  }
  function hours(h){
    if(!h||!h.core_hours)return '';
    const read=h.host_read?`the host read since ${String(h.since||'').replace('T',' ').slice(0,16)} UTC, ${h.host_cores} cores`:'the host not read yet: the system’s share waits for the telemetry';
    return bar(h.core_hours,'core-h',h.names,`core-hours, counted from every attempt’s wall time (one worker one core): blind (A), the focus’s neighbours, seeds and seeded laws (N), the depth seeker (D), and the system’s own use, the host’s total less the workers’ (the standing controls among it); ${read}`)
      +bar(h.memory_gib_hours,'GiB-h',h.names,`memory held over time: each attempt’s peak memory times its wall time, in GiB-hours, the same four parts; the system’s is the host’s memory in use less the workers’; ${read}`);
  }
  function chosen(filter,kept,total,names){
    const f=filter||{},said=[];
    if(f.kind)said.push(`kind ${(names||{})[f.kind]||f.kind}`);
    else if(f.off&&f.off.size)said.push(`every kind but ${[...f.off].map(k=>(names||{})[k]||k).join(', ')}`);
    if(f.group)said.push(`group ${f.group}`);
    if(f.batch)said.push(`batch C${f.batch}`);
    if(f.region)said.push({new:'not in a region yet',mapping:'in a region being mapped',known:'in a known region'}[f.region]||f.region);
    if(f.settled)said.push(f.settled==='settled'?'settled':'not settled');
    if(f.scoring)said.push('scoring only');
    if(f.deepest)said.push(`deepest size at least N=${num(f.deepest)}`);
    return `<b>${esc(num(kept))}</b> of ${esc(num(total))} laws: ${said.length?esc(said.join(', ')):'every law of the study'}`;
  }
  window.GSD_SELECTION={ladder,render,hours,bar,chosen,deepest};
})();
