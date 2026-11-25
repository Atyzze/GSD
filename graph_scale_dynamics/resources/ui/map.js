(function(){
  const SYS=window.GSD_SYSTEM, esc=SYS.esc;
  let data=null, busy=false, note='', wired=false;
  const num=v=>Number(v).toLocaleString('en-US');
  const size=v=>v==null?'not yet':num(v);
  const radiusText=r=>{const x=Number(r);return x<1e-3?x.toExponential(0):String(x)};
  const short=id=>String(id||'').slice(0,10);
  function ringsText(rings){return (rings||[]).map(([r,c])=>`${radiusText(r)}:${c}`).join(', ')}
  function parseRings(text){
    const rings=String(text||'').split(',').map(part=>part.trim()).filter(Boolean).map(part=>{
      const m=/^([0-9.eE+-]+)\s*:\s*(\d+)$/.exec(part);
      if(!m||!isFinite(+m[1]))throw new Error(`"${part}" is not radius:laws`);
      return [+m[1],+m[2]]});
    if(!rings.length)throw new Error('give at least one ring, as radius:laws');
    return rings}
  function bar(row){
    const all=Math.max(1,row.laws),part=(k,cls)=>row[k]?`<span class="map-bar-${cls}" style="width:${(100*row[k]/all).toFixed(1)}%"></span>`:'';
    return `<span class=map-bar title="${esc(row.alike)} alike, ${esc(row.other)} other, ${esc(row.waiting)} waiting">${part('alike','alike')}${part('other','other')}${part('waiting','waiting')}</span>`}
  function stageText(s){return {neighbourhood:'reading its neighbourhood',boundaries:'halving its boundaries',mapped:'mapped',unconfirmed:'unconfirmed',invalidated:'invalidated'}[s]||String(s||'')}
  function controls(d){
    const f=d&&d.focus, w=(d&&d.workload)||{}, studies=(d&&d.studies)||[];
    const shares=Object.entries(w.shares||{}).map(([g,v])=>`${esc(g)} ${Math.round(100*v)}%`).join(' · ')||'every campaign alike';
    const said=note?`<div class="muted map-note">${esc(note)}</div>`:'';
    if(!f){
      const options=studies.map(s=>`<option value="${esc(s.study)}">study ${esc(s.study)} (${esc(s.campaigns)} campaigns)</option>`).join('');
      return `<div class=toolbar><span class=muted>no focus in this folder</span>${studies.length?`<select id=mapStudy data-admin-write>${options}</select><button type=button class=gsd-control data-admin-write data-map-do=start>start the focus</button>`:'<span class=muted>and no study to focus on</span>'}</div>${said}`}
    const s=f.settings||{}, next=f.next_settings;
    const camps=f.campaigns||{};
    const lean=leanOf(f,w), work=(d&&d.work)||{};
    const workText=[['N','neighbours'],['S','seeds'],['D','depth']].map(([k,name])=>{const r=work[k]||{};return `${name} (C${esc(r.campaign||camps[k]||'?')}): running ${esc(num(r.running||0))}, queued ${esc(num(r.queued||0))}, ${esc(num(r.done||0))} done${r.deepest?`, deepest N=${esc(num(r.deepest))}`:''}`}).join(' · ');
    return `<div class=muted>study <b>${esc(f.study)}</b> · ${f.stopped?'<b class=warn>the focus is off</b>':'the focus runs'} · shares: ${shares}</div>
      <div class="toolbar map-lean"><span>random draw</span><input id=mapLean data-admin-write type=range min=0 max=100 step=5 value="${esc(Math.round(100*lean))}" title="the share of the workers the focus's neighbours and seeds take against the blind draw; the depth seeker always holds one worker; at 0 the focus is off" style="width:22em"><span>in focus</span><b id=mapLeanValue>${esc(100-Math.round(100*lean))}% random · ${esc(Math.round(100*lean))}% focus · depth 1 worker</b></div>
      <div class=muted>${workText}</div>
      <div class=toolbar><label class=muted>rings <input id=mapRings data-admin-write type=text value="${esc(ringsText((next||s).radii))}" style="width:26em"></label>
        <label class=muted>confirm at ${esc(radiusText(s.confirm_radius))} by <input id=mapConfirm data-admin-write type=number min=0.5 max=1 step=0.01 value="${esc((next||s).confirm_share)}" style="width:5em"></label>
        <label class=muted>deep laws <input id=mapContenders data-admin-write type=number min=0 max=20 step=1 value="${esc((next||s).contenders)}" style="width:4em"></label>
        <label class=muted>widest ring <input id=mapOutward data-admin-write type=number min=0.1 max=0.95 step=0.05 value="${esc((next||s).outward_most)}" style="width:5em"></label>
        <label class=muted>inside a region below <input id=mapInside data-admin-write type=number min=0 max=1 step=0.05 value="${esc((next||s).inside_share)}" style="width:5em"> of its reach</label>
        <label class=muted title="the focus takes first the law whose type is least known; a type counts as known once this many of its laws are mapped, a one-dimensional form (a ring or a line) counting one from the start">a type known after <input id=mapPerType data-admin-write type=number min=1 max=50 step=1 value="${esc((next||s).mapped_per_type??3)}" style="width:4em"> laws</label>
        <button type=button class=gsd-control data-admin-write data-map-do=settings>apply from the next law</button></div>
      ${next?`<div class=muted>the next law takes: rings ${esc(ringsText(next.radii))}, confirmed by ${esc(next.confirm_share)}, ${esc(next.contenders)} deep laws, rings to ${esc(next.outward_most)}</div>`:''}${said}`}
  function leanOf(f,w){const sh=(w&&w.shares)||{};if(f&&f.stopped)return 0;if(f&&f.lean&&f.lean.focus!=null)return +f.lean.focus;const a=+sh.A||0,n=+sh.N||0;return a+n>0?n/(a+n):0.5}
  function listTable(d,which){
    const rows=((d&&d.focus&&d.focus.lists)||{})[which]||[];
    if(!rows.length)return `<div class=empty>${which==='focus'?'no scoring law waits for the focus':'no law to take deeper yet'}</div>`;
    return `<table class=map-queue><thead><tr><th></th><th>law</th><th>score</th><th>type</th><th>identified from</th><th></th></tr></thead><tbody>${rows.map((e,i)=>`<tr><td class=muted>${i+1}</td><td>${esc(e.label||short(e.law))}${e.placed?' <span class=muted title="placed by hand">\u2022</span>':''}</td><td>${esc(e.score)}</td><td>${esc(e.type||'not read yet')}</td><td>${e.identified_from?`N=${esc(num(e.identified_from))}`:'<span class=muted>not yet</span>'}</td><td><button type=button class=chip data-admin-write data-map-do=order data-map-list="${which}" data-map-move=up data-map-law="${esc(e.law)}" ${i?'':'disabled'}>\u2191</button> <button type=button class=chip data-admin-write data-map-do=order data-map-list="${which}" data-map-move=down data-map-law="${esc(e.law)}" ${i<rows.length-1?'':'disabled'}>\u2193</button>${which==='focus'?` <button type=button class=chip data-admin-write data-map-do=skip data-map-law="${esc(e.law)}">skip</button>`:(e.in_depth?' <span class=muted>in the depth campaign</span>':'')}</td></tr>`).join('')}</tbody></table><div class=toolbar><button type=button class=chip data-admin-write data-map-do=order data-map-list="${which}" data-map-move=reset title="forget the order set by hand and take the suggested one">the suggested order</button></div>`}
  function current(d){
    const c=d&&d.focus&&d.focus.current;
    if(!c)return `<div class=empty>${d&&d.focus?'no law is in focus now: every scoring law is mapped, inside a mapped region, or skipped':'no focus in this folder'}</div>`;
    const rows=Object.entries(c.radii||{}).sort((a,b)=>+a[0]-+b[0]).map(([r,row])=>`<tr><td>${esc(radiusText(r))}</td><td>${esc(row.laws)}</td><td>${esc(row.alike)}</td><td>${esc(row.other)}</td><td>${esc(row.waiting)}</td><td>${bar(row)}</td></tr>`).join('');
    const seeds=c.seeds, sens=c.sensitivity;
    const seedLine=seeds?`its own campaign's seeds: ${Object.entries(seeds.own||{}).map(([k,v])=>`${esc(k)} ${esc(v)}`).join(', ')} · on more seeds: ${Object.entries(seeds.more||{}).map(([k,v])=>`${esc(k)} ${esc(v)}`).join(', ')} · ${seeds.reproduced?'its own seeds reproduced':'<b class=warn>its own seeds did not reproduce</b>'}`:'its seeds: waiting for the seeds campaign to decide';
    const lines=Object.entries(c.boundaries||{}).map(([p,b])=>`<li>toward ${esc(short(p))}: between ${esc(b.between[0])} and ${esc(b.between[1])} of the line, ${esc(b.kinds[0])} to ${esc(b.kinds[1])}${b.why?` (${esc(b.why)})`:''}</li>`).join('');
    const depth=c.depth||{};
    const early=c.early_call;
    return `<div class=toolbar><b>${esc(c.label)}</b><span class=muted>score ${esc(c.score)} · its kind at 16,384: ${esc(c.kind)}${c.identified_from?`, read so from N=${esc(num(c.identified_from))}`:''} · ${esc(stageText(c.stage))}${c.why?` (${esc(c.why)})`:''}</span><button type=button class=gsd-control data-admin-write data-map-do=skip data-map-law="${esc(c.law)}">skip this law</button></div>
      ${early?`<div class=muted title="each neighbour's kind at the size this law is identified from, against its kind at 16,384: how far a smaller read would have called it">the call at N=${esc(num(early.at_n))} agrees with 16,384 on ${esc(num(early.agreed))} of ${esc(num(early.of))} neighbours read</div>`:''}
      <table class=map-rings><thead><tr><th>ring</th><th>laws</th><th>alike</th><th>other</th><th>waiting</th><th></th></tr></thead><tbody>${rows||'<tr><td colspan=6 class=muted>no ring yet</td></tr>'}</tbody></table>
      <div class=muted>${seedLine}</div>
      <div>${sens?`sensitive to <b>${esc(sens.on)}</b>: ${esc(sens.words)}`:'<span class=muted>sensitive to: not read yet (its seeds and the rings of 1e-3 or less)</span>'}</div>
      <div class=muted>its region reaches ${c.alike_to!=null?esc(c.alike_to):'no ring yet'} · its depth: deepest ${esc(size(depth.deepest))}, holds to ${esc(size(depth.holds_to))}${depth.invalidated_at!=null?`, <b class=warn>invalidated at ${esc(num(depth.invalidated_at))}</b>`:''}</div>
      ${lines?`<ul class=map-lines>${lines}</ul>`:''}${termsLine(c)}`}
  function termsLine(e){
    const t=Object.entries(e.terms||{});
    if(!t.length)return '';
    const each=t.map(([name,row])=>`${esc(name)}: ${row.load_bearing==null?'waiting':row.load_bearing?`<b>load-bearing</b> (off, it reads ${esc(row.kind)})`:'not load-bearing'}`).join(' · ');
    return `<div class=muted>each term switched off: ${each}${e.core?` · <b>its core: ${esc(e.core.join(', ')||'none of its terms alone')}</b>`:''}</div>`}
  function rangeText(lo,hi){return lo===hi?esc(Number(lo).toPrecision(4)):`${esc(Number(lo).toPrecision(4))} to ${esc(Number(hi).toPrecision(4))}`}
  function regions(d){
    const list=(d&&d.focus&&d.focus.regions)||[];
    if(!list.length)return '<div class=empty>no region mapped yet: a region is named once its law is mapped</div>';
    const touch=((d.focus.touching)||[]).map(t=>`<li>${esc(t.regions[0])} (${esc(t.kinds[0])}) and ${esc(t.regions[1])} (${esc(t.kinds[1])}) overlap in every coupling: a boundary lies between them</li>`).join('');
    return list.map(r=>`<div class=map-region><div><b>${esc(r.name)}</b> <span class=muted>${esc(r.kind)} · ${esc(r.members)} laws read its kind · from ${esc((r.labels||[]).join(', '))}${r.alike_to!=null?` · every ring to ${esc(r.alike_to)} alike`:''} · ${esc((r.boundaries||[]).length)} boundaries${Object.keys(r.cores||{}).length?` · core terms: ${Object.entries(r.cores).map(([l,c])=>`${esc(c.join(', ')||'none alone')} (${esc(l)})`).join('; ')}`:''}${r.seeded_from?` · seeded from ${esc(r.seeded_from.bundle)}`:''}</span></div>
      <table class=map-ranges><tbody>${Object.entries(r.ranges||{}).map(([axis,[lo,hi]])=>`<tr><td>${esc(axis)}</td><td>${rangeText(lo,hi)}</td></tr>`).join('')}</tbody></table></div>`).join('')+(touch?`<ul class=map-touching>${touch}</ul>`:'')}
  function depthTable(d){
    const all=Object.entries((d&&d.focus&&d.focus.contenders)||{});
    if(!all.length)return '<div class=empty>no law is being taken deeper yet</div>';
    return `<table class=map-depth><thead><tr><th>law</th><th>deepest</th><th>holds its kind to</th><th>invalidated at</th><th>its kinds in the depth campaign</th></tr></thead><tbody>${all.map(([law,e])=>`<tr><td>${esc(e.label||short(law))}</td><td>${esc(size(e.deepest))}</td><td>${esc(size(e.holds_to))}</td><td>${e.invalidated_at!=null?`<b class=warn>${esc(num(e.invalidated_at))}</b>`:'no'}</td><td class=muted>${Object.entries(e.kinds||{}).map(([n,k])=>`${esc(num(n))} ${esc(k)}`).join(' · ')}</td></tr>`).join('')}</tbody></table>`}
  function queue(d){
    const q=(d&&d.focus&&d.focus.queue)||[];
    if(!q.length)return '<div class=empty>the queue arrives with the focus’s first step</div>';
    return `<table class=map-queue><thead><tr><th></th><th>law</th><th>score</th><th>where it stands</th><th></th></tr></thead><tbody>${q.map((e,i)=>{
      const free=e.status==='waiting', back=e.status==='skipped'||!['waiting','in focus'].includes(e.status);
      return `<tr><td class=muted>${i+1}</td><td>${esc(e.label||short(e.law))}</td><td>${esc(e.score)}</td><td>${esc(e.status)}${e.region?` · ${esc(e.region)}`:''}${e.type?` <span class=muted>· ${esc(e.type)}</span>`:''}</td><td>${free?`<button type=button class=chip data-admin-write data-map-do=skip data-map-law="${esc(e.law)}">skip</button>`:''}${back?`<button type=button class=chip data-admin-write data-map-do=back data-map-law="${esc(e.law)}">put back</button>`:''}</td></tr>`}).join('')}</tbody></table>`}
  function done(d){
    const list=((d&&d.focus&&d.focus.done)||[]).slice().reverse();
    if(!list.length)return '<div class=empty>no law’s focus has ended yet</div>';
    return `<ul class=map-done>${list.map(e=>`<li><b>${esc(e.label||short(e.law))}</b> ${esc(e.stage)}${e.region?` as ${esc(e.region)}`:''}${e.type?` (${esc(e.type)})`:''}${e.why?`: ${esc(e.why)}`:''}${e.sensitivity?` · sensitive to ${esc(e.sensitivity.on)}`:''}${e.core?` · core: ${esc(e.core.join(', ')||'none alone')}`:''}</li>`).join('')}</ul>`}
  function seeds(d){
    const f=d&&d.focus;
    if(!f)return '<div class=empty>a seed joins a focus: start one first</div>';
    const made=(f.seeded||[]).map(e=>`<li><b>${esc(e.bundle)}</b> <span class=muted>(study ${esc(e.study)}, built ${esc(e.built_utc||'')}): ${esc(num(e.scoring))} scoring laws, ${esc(num(e.laws_added))} new here, regions ${esc((e.regions||[]).join(', ')||'none')}${e.mismatched?`, <b class=warn>${esc(num(e.mismatched))} laws whose spec is not their id, left out</b>`:''}</span></li>`).join('');
    return `<div class=toolbar><label class=muted>bundle on this host <input id=mapBundle data-admin-write type=text placeholder="/path/to/study_174_....tar.zst or its folder" style="width:34em"></label><button type=button class=gsd-control data-admin-write data-map-do=seed title="its scoring laws run again here in the seeded campaign and its GG regions join the map; a bundle read by another science is refused; a second seed appends">seed from a bundle</button></div>${made?`<ul class=map-done>${made}</ul>`:'<div class=empty>no seed yet: the study maps from its own laws alone</div>'}`}
  function runOn(d){
    const lists=(d&&d.run_on_lists)||[], now=d&&d.run_on;
    if(now){
      const st=now.stages||{}, rows=(now.laws||[]).map(e=>`<tr><td>C${esc(e.campaign)}</td><td><code>${esc(short(e.law))}</code></td><td>${esc(e.class||'')}</td><td>${esc(e.stage)}</td><td class=muted>${esc(e.rule||'')}${e.at_n!=null?` at N=${esc(num(e.at_n))}`:''}</td></tr>`).join('');
      return `<div class=toolbar><span>${esc(num((now.laws||[]).length))} laws named by <code>${esc(now.list)}</code>: ${esc(num(st.waiting||0))} waiting to be decided again, ${esc(num(st['running on']||0))} running on, ${esc(num(st.settled||0))} settled again</span><button type=button class=gsd-control data-admin-write data-map-do=run_on_clear title="name no more laws; a law already run on goes on">name no more</button></div>
        <table class=map-run-on><thead><tr><th>campaign</th><th>law</th><th>class at the gate</th><th>where it stands</th><th>its latest decision</th></tr></thead><tbody>${rows}</tbody></table>`}
    if(!lists.length)return '<div class=empty>no run-on list for this folder\u2019s study</div>';
    return lists.map(l=>`<div class=toolbar><span>study ${esc(l.study)}: ${esc(num(l.held))} laws ${esc(l.gate)} holds at N=${esc(num(l.at_n))} in ${esc(l.bundle||'its bundle')}, ${esc(num(l.run_on))} of them read something (${Object.entries(l.classes||{}).map(([k,v])=>`${esc(k)} ${esc(num(v))}`).join(', ')})</span><button type=button class=gsd-control data-admin-write data-map-do=run_on data-map-study="${esc(l.study)}" title="each named law is decided again at the size its gate held it and goes to the next size; the gate's own counts do not move">run them on</button></div>`).join('')}
  function render(d){
    data=d||data;
    const put=(id,html)=>{const el=document.getElementById(id);if(el)el.innerHTML=html};
    const scope=document.getElementById('mapScope');if(scope)scope.textContent=data&&data.focus?`study ${data.focus.study}`:'';
    const typing=['mapLean','mapRings','mapConfirm','mapContenders','mapOutward','mapInside','mapPerType','mapStudy','mapBundle'].some(id=>{const el=document.getElementById(id);return el&&document.activeElement===el});
    if(!typing)put('mapControls',controls(data));
    put('mapCurrent',current(data));put('mapRegions',regions(data));put('mapDepth',depthTable(data));put('mapQueue',queue(data));put('mapFocusList',listTable(data,'focus'));put('mapDepthList',listTable(data,'depth'));put('mapDone',done(data));put('mapRunOn',runOn(data));if(!typing)put('mapSeed',seeds(data));
    wire()}
  function value(id){const el=document.getElementById(id);return el?el.value:''}
  function bodyFor(button){
    const what=button.getAttribute('data-map-do'), law=button.getAttribute('data-map-law');
    if(what==='start')return {do:'start',study:value('mapStudy')||undefined};
    if(what==='stop')return {do:'stop'};
    if(what==='split')return {do:'split',split:value('mapSplit')};
    if(what==='law')return {do:'law',law:law||value('mapLaw')};
    if(what==='skip'||what==='back')return {do:what,law};
    if(what==='run_on')return {do:'run_on',study:button.getAttribute('data-map-study')||undefined};
    if(what==='seed')return {do:'seed',bundle:value('mapBundle')};
    if(what==='order')return {do:'order',list:button.getAttribute('data-map-list'),law:law||'',move:button.getAttribute('data-map-move')};
    if(what==='run_on_clear')return {do:'run_on',clear:true};
    return {do:'settings',settings:{radii:parseRings(value('mapRings')),confirm_share:+value('mapConfirm'),contenders:+value('mapContenders'),outward_most:+value('mapOutward'),inside_share:+value('mapInside'),mapped_per_type:+value('mapPerType')||3}}}
  async function act(body){
    note='';
    try{data=await SYS.postJson('/api/focus',body);note=`done: ${body.do}`}
    catch(e){note=String((e&&e.message)||e)}
    render(data)}
  function wire(){
    if(wired)return;const root=document.getElementById('gsdMap');if(!root)return;wired=true;
    root.addEventListener('click',e=>{
      const reload=e.target.closest&&e.target.closest('#mapReload');if(reload){refresh(true);return}
      const button=e.target.closest&&e.target.closest('[data-map-do]');if(!button)return;
      let body;try{body=bodyFor(button)}catch(err){note=String(err.message||err);render(data);return}
      act(body)});
    root.addEventListener('input',e=>{if(e.target&&e.target.id==='mapLean'){const v=+e.target.value,out=document.getElementById('mapLeanValue');if(out)out.textContent=`${100-v}% random \u00b7 ${v}% focus \u00b7 depth 1 worker`}});
    root.addEventListener('change',e=>{if(e.target&&e.target.id==='mapLean')act({do:'lean',focus:(+e.target.value)/100})})}
  async function refresh(force){
    if(busy&&!force)return;busy=true;
    try{data=await SYS.getJson('/api/focus')}
    catch(e){note=String((e&&e.message)||e)}
    finally{busy=false;render(data)}}
  window.GSD_MAP={refresh,render,act,bodyFor,parseRings,ringsText,get data(){return data},set data(v){data=v},get note(){return note}};
})();
