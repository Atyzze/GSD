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
    return `<div class=muted>study <b>${esc(f.study)}</b> · ${f.stopped?'<b class=warn>stopped</b>':'running'} · neighbours in campaign ${esc(camps.N)}, seeds in ${esc(camps.S)} (group N), depth in ${esc(camps.D)} (group D) · shares: ${shares}</div>
      <div class=toolbar>${f.stopped?'<button type=button class=gsd-control data-admin-write data-map-do=start>start again</button>':'<button type=button class=gsd-control data-admin-write data-map-do=stop title="pause the three campaigns; the blind draw goes on">stop the focus</button>'}
        <label class=muted>split <input id=mapSplit data-admin-write type=text value="${esc(w.split||'')}" placeholder="A=2,N=1,D=1" style="width:10em"></label><button type=button class=gsd-control data-admin-write data-map-do=split>set</button>
        <label class=muted>law <input id=mapLaw data-admin-write type=text placeholder="C1-G6940 or an id" style="width:12em"></label><button type=button class=gsd-control data-admin-write data-map-do=law title="set the law in focus aside and take this one now">focus now</button></div>
      <div class=toolbar><label class=muted>rings <input id=mapRings data-admin-write type=text value="${esc(ringsText((next||s).radii))}" style="width:26em"></label>
        <label class=muted>confirm at ${esc(radiusText(s.confirm_radius))} by <input id=mapConfirm data-admin-write type=number min=0.5 max=1 step=0.01 value="${esc((next||s).confirm_share)}" style="width:5em"></label>
        <label class=muted>deep laws <input id=mapContenders data-admin-write type=number min=0 max=20 step=1 value="${esc((next||s).contenders)}" style="width:4em"></label>
        <label class=muted>widest ring <input id=mapOutward data-admin-write type=number min=0.1 max=0.95 step=0.05 value="${esc((next||s).outward_most)}" style="width:5em"></label>
        <label class=muted>inside a region below <input id=mapInside data-admin-write type=number min=0 max=1 step=0.05 value="${esc((next||s).inside_share)}" style="width:5em"> of its reach</label>
        <button type=button class=gsd-control data-admin-write data-map-do=settings>apply from the next law</button></div>
      ${next?`<div class=muted>the next law takes: rings ${esc(ringsText(next.radii))}, confirmed by ${esc(next.confirm_share)}, ${esc(next.contenders)} deep laws, rings to ${esc(next.outward_most)}</div>`:''}${said}`}
  function current(d){
    const c=d&&d.focus&&d.focus.current;
    if(!c)return `<div class=empty>${d&&d.focus?'no law is in focus now: every scoring law is mapped, inside a mapped region, or skipped':'no focus in this folder'}</div>`;
    const rows=Object.entries(c.radii||{}).sort((a,b)=>+a[0]-+b[0]).map(([r,row])=>`<tr><td>${esc(radiusText(r))}</td><td>${esc(row.laws)}</td><td>${esc(row.alike)}</td><td>${esc(row.other)}</td><td>${esc(row.waiting)}</td><td>${bar(row)}</td></tr>`).join('');
    const seeds=c.seeds, sens=c.sensitivity;
    const seedLine=seeds?`its own campaign's seeds: ${Object.entries(seeds.own||{}).map(([k,v])=>`${esc(k)} ${esc(v)}`).join(', ')} · on more seeds: ${Object.entries(seeds.more||{}).map(([k,v])=>`${esc(k)} ${esc(v)}`).join(', ')} · ${seeds.reproduced?'its own seeds reproduced':'<b class=warn>its own seeds did not reproduce</b>'}`:'its seeds: waiting for the seeds campaign to decide';
    const lines=Object.entries(c.boundaries||{}).map(([p,b])=>`<li>toward ${esc(short(p))}: between ${esc(b.between[0])} and ${esc(b.between[1])} of the line, ${esc(b.kinds[0])} to ${esc(b.kinds[1])}${b.why?` (${esc(b.why)})`:''}</li>`).join('');
    const depth=c.depth||{};
    return `<div class=toolbar><b>${esc(c.label)}</b><span class=muted>score ${esc(c.score)} · its kind at 16,384: ${esc(c.kind)} · ${esc(stageText(c.stage))}${c.why?` (${esc(c.why)})`:''}</span><button type=button class=gsd-control data-admin-write data-map-do=skip data-map-law="${esc(c.law)}">skip this law</button></div>
      <table class=map-rings><thead><tr><th>ring</th><th>laws</th><th>alike</th><th>other</th><th>waiting</th><th></th></tr></thead><tbody>${rows||'<tr><td colspan=6 class=muted>no ring yet</td></tr>'}</tbody></table>
      <div class=muted>${seedLine}</div>
      <div>${sens?`sensitive to <b>${esc(sens.on)}</b>: ${esc(sens.words)}`:'<span class=muted>sensitive to: not read yet (its seeds and the rings of 1e-3 or less)</span>'}</div>
      <div class=muted>its region reaches ${c.alike_to!=null?esc(c.alike_to):'no ring yet'} · its depth: deepest ${esc(size(depth.deepest))}, holds to ${esc(size(depth.holds_to))}${depth.invalidated_at!=null?`, <b class=warn>invalidated at ${esc(num(depth.invalidated_at))}</b>`:''}</div>
      ${lines?`<ul class=map-lines>${lines}</ul>`:''}`}
  function rangeText(lo,hi){return lo===hi?esc(Number(lo).toPrecision(4)):`${esc(Number(lo).toPrecision(4))} to ${esc(Number(hi).toPrecision(4))}`}
  function regions(d){
    const list=(d&&d.focus&&d.focus.regions)||[];
    if(!list.length)return '<div class=empty>no region mapped yet: a region is named once its law is mapped</div>';
    const touch=((d.focus.touching)||[]).map(t=>`<li>${esc(t.regions[0])} (${esc(t.kinds[0])}) and ${esc(t.regions[1])} (${esc(t.kinds[1])}) overlap in every coupling: a boundary lies between them</li>`).join('');
    return list.map(r=>`<div class=map-region><div><b>${esc(r.name)}</b> <span class=muted>${esc(r.kind)} · ${esc(r.members)} laws read its kind · from ${esc((r.labels||[]).join(', '))}${r.alike_to!=null?` · every ring to ${esc(r.alike_to)} alike`:''} · ${esc((r.boundaries||[]).length)} boundaries</span></div>
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
      return `<tr><td class=muted>${i+1}</td><td>${esc(e.label||short(e.law))}</td><td>${esc(e.score)}</td><td>${esc(e.status)}${e.region?` · ${esc(e.region)}`:''}</td><td>${free?`<button type=button class=chip data-admin-write data-map-do=law data-map-law="${esc(e.law)}">focus now</button> <button type=button class=chip data-admin-write data-map-do=skip data-map-law="${esc(e.law)}">skip</button>`:''}${back?`<button type=button class=chip data-admin-write data-map-do=back data-map-law="${esc(e.law)}">put back</button>`:''}</td></tr>`}).join('')}</tbody></table>`}
  function done(d){
    const list=((d&&d.focus&&d.focus.done)||[]).slice().reverse();
    if(!list.length)return '<div class=empty>no law’s focus has ended yet</div>';
    return `<ul class=map-done>${list.map(e=>`<li><b>${esc(e.label||short(e.law))}</b> ${esc(e.stage)}${e.region?` as ${esc(e.region)}`:''}${e.why?`: ${esc(e.why)}`:''}${e.sensitivity?` · sensitive to ${esc(e.sensitivity.on)}`:''}</li>`).join('')}</ul>`}
  function render(d){
    data=d||data;
    const put=(id,html)=>{const el=document.getElementById(id);if(el)el.innerHTML=html};
    const scope=document.getElementById('mapScope');if(scope)scope.textContent=data&&data.focus?`study ${data.focus.study}`:'';
    const typing=['mapSplit','mapLaw','mapRings','mapConfirm','mapContenders','mapOutward','mapInside','mapStudy'].some(id=>{const el=document.getElementById(id);return el&&document.activeElement===el});
    if(!typing)put('mapControls',controls(data));
    put('mapCurrent',current(data));put('mapRegions',regions(data));put('mapDepth',depthTable(data));put('mapQueue',queue(data));put('mapDone',done(data));
    wire()}
  function value(id){const el=document.getElementById(id);return el?el.value:''}
  function bodyFor(button){
    const what=button.getAttribute('data-map-do'), law=button.getAttribute('data-map-law');
    if(what==='start')return {do:'start',study:value('mapStudy')||undefined};
    if(what==='stop')return {do:'stop'};
    if(what==='split')return {do:'split',split:value('mapSplit')};
    if(what==='law')return {do:'law',law:law||value('mapLaw')};
    if(what==='skip'||what==='back')return {do:what,law};
    return {do:'settings',settings:{radii:parseRings(value('mapRings')),confirm_share:+value('mapConfirm'),contenders:+value('mapContenders'),outward_most:+value('mapOutward'),inside_share:+value('mapInside')}}}
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
      act(body)})}
  async function refresh(force){
    if(busy&&!force)return;busy=true;
    try{data=await SYS.getJson('/api/focus')}
    catch(e){note=String((e&&e.message)||e)}
    finally{busy=false;render(data)}}
  window.GSD_MAP={refresh,render,act,bodyFor,parseRings,ringsText,get data(){return data},set data(v){data=v},get note(){return note}};
})();
