(function(){
  const SYS=window.GSD_SYSTEM, esc=SYS.esc;
  let data=null, busy=false, note='', wired=false, settingsOpen=false, pendingTicks={};
  const num=v=>Number(v).toLocaleString('en-US');
  const size=v=>v==null?'not yet':num(v);
  const radiusText=r=>{const x=Number(r);return x<1e-3?x.toExponential(0):String(x)};
  const short=id=>String(id||'').slice(0,10);
  function lawHref(law,camp){const raw=SYS.route('/candidate'),parts=raw.split('#');let u=parts[0]+'?candidate='+encodeURIComponent(law||'');if(camp!=null&&camp!=='')u+='&campaign='+encodeURIComponent(camp);return u+(parts[1]?'#'+parts[1]:'')}
  function originText(o){return o?`<span class="muted map-origin" title="seeded from ${esc(o.bundle||'its bundle')}: its code and score in study ${esc(o.study||'?')}">from ${esc(o.code||'?')}, ${esc(o.score)} there</span>`:''}
  function lawLink(law,camp,label,origin){return `<a class="candidate-link map-law" href="${esc(lawHref(law,camp))}" title="the law page of ${esc(law||'')}">${esc(label||short(law))}</a>${origin?' '+originText(origin):''}`}
  function scoreText(e){return e&&e.standing==='bundle'&&e.origin?`${esc(e.score)} <span class=muted title="it stands on its bundle's score until this folder reads it at 16,384">in study ${esc(e.origin.study||'?')}'s bundle</span>`:esc(e&&e.score)}
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
    return `<div class=map-doing id=mapDoing title="what the focus does now and why, read every 4 s"><b>${esc(f.doing||'the focus waits for its first step')}</b></div>
      <div class=muted>study <b>${esc(f.study)}</b> · ${f.stopped?'<b class=warn>the focus is off</b>':'the focus runs'} · shares: ${shares}</div>
      <div class="toolbar map-lean"><span>random draw</span><input id=mapLean data-admin-write type=range min=0 max=100 step=5 value="${esc(Math.round(100*lean))}" title="the share of the workers the focus's neighbours and seeds take against the blind draw; the depth seeker always holds one worker; at 0 the focus is off" style="width:22em"><span>in focus</span><b id=mapLeanValue>${esc(100-Math.round(100*lean))}% random · ${esc(Math.round(100*lean))}% focus</b></div>
      <div class=muted>${workText}</div>
      <details class=map-settings id=mapSettings${settingsOpen?' open':''}><summary>the focus’s settings: how it maps a law (rarely changed; a change applies from the next law)</summary>
      <ul class="muted map-settings-words">
        <li><b>rings</b>: how far from the law its neighbours are drawn, and how many on each ring: <code>0.1:8</code> is 8 laws whose couplings differ by up to 10%.</li>
        <li><b>confirm at 0.1 by</b>: the share of the 0.1 ring that must read the law’s own kind before its kind counts as confirmed.</li>
        <li><b>deep laws</b>: how many of the best laws the depth seeker takes to larger sizes.</li>
        <li><b>widest ring</b>: the farthest the rings go out when a region is mapped outward.</li>
        <li><b>inside a region below</b>: a law closer than this share of a mapped region’s reach to it counts as inside it, and is not focused on again.</li>
        <li><b>a type known after</b>: how many laws of a type must be mapped before the focus prefers types it knows less.</li></ul>
      <div class=toolbar><label class=muted>rings <input id=mapRings data-admin-write type=text value="${esc(ringsText((next||s).radii))}" style="width:26em"></label>
        <label class=muted>confirm at ${esc(radiusText(s.confirm_radius))} by <input id=mapConfirm data-admin-write type=number min=0.5 max=1 step=0.01 value="${esc((next||s).confirm_share)}" style="width:5em"></label>
        <label class=muted>deep laws <input id=mapContenders data-admin-write type=number min=0 max=20 step=1 value="${esc((next||s).contenders)}" style="width:4em"></label>
        <label class=muted>widest ring <input id=mapOutward data-admin-write type=number min=0.1 max=0.95 step=0.05 value="${esc((next||s).outward_most)}" style="width:5em"></label>
        <label class=muted>inside a region below <input id=mapInside data-admin-write type=number min=0 max=1 step=0.05 value="${esc((next||s).inside_share)}" style="width:5em"> of its reach</label>
        <label class=muted title="the focus takes first the law whose type is least known; a type counts as known once this many of its laws are mapped, a one-dimensional form (a ring or a line) counting one from the start">a type known after <input id=mapPerType data-admin-write type=number min=1 max=50 step=1 value="${esc((next||s).mapped_per_type??3)}" style="width:4em"> laws</label>
        <button type=button class=gsd-control data-admin-write data-map-do=settings>apply from the next law</button></div>
      ${next?`<div class=muted>the next law takes: rings ${esc(ringsText(next.radii))}, confirmed by ${esc(next.confirm_share)}, ${esc(next.contenders)} deep laws, rings to ${esc(next.outward_most)}</div>`:''}</details>${said}`}
  function leanOf(f,w){const sh=(w&&w.shares)||{};if(f&&f.stopped)return 0;if(f&&f.lean&&f.lean.focus!=null)return +f.lean.focus;const a=+sh.A||0,n=+sh.N||0;return a+n>0?n/(a+n):0.5}
  function listTable(d,which){
    const rows=((d&&d.focus&&d.focus.lists)||{})[which]||[];
    if(!rows.length)return `<div class=empty>${which==='focus'?'no scoring law waits for the focus':'no law to take deeper yet'}</div>`;
    return `<table class=map-queue><thead><tr><th></th><th>law</th><th>score</th><th>type</th><th>identified from</th><th></th></tr></thead><tbody>${rows.map((e,i)=>`<tr><td class=muted>${i+1}</td><td>${lawLink(e.law,e.campaign,e.label,e.origin)}${e.placed?' <span class=muted title="placed by hand">\u2022</span>':''}</td><td>${scoreText(e)}</td><td>${esc(e.type||'not read yet')}</td><td>${e.identified_from?`N=${esc(num(e.identified_from))}`:'<span class=muted>not yet</span>'}</td><td><button type=button class=chip data-admin-write data-map-do=order data-map-list="${which}" data-map-move=up data-map-law="${esc(e.law)}" ${i?'':'disabled'}>\u2191</button> <button type=button class=chip data-admin-write data-map-do=order data-map-list="${which}" data-map-move=down data-map-law="${esc(e.law)}" ${i<rows.length-1?'':'disabled'}>\u2193</button>${which==='focus'?` <button type=button class=chip data-admin-write data-map-do=skip data-map-law="${esc(e.law)}">skip</button>`:(e.in_depth?' <span class=muted>in the depth campaign</span>':'')}</td></tr>`).join('')}</tbody></table><div class=toolbar><button type=button class=chip data-admin-write data-map-do=order data-map-list="${which}" data-map-move=reset title="forget the order set by hand and take the suggested one">the suggested order</button></div>`}
  function current(d){
    const c=d&&d.focus&&d.focus.current;
    if(!c)return `<div class=empty>${d&&d.focus?'no law is in focus now: every scoring law is mapped, inside a mapped region, or skipped':'no focus in this folder'}</div>`;
    const rows=Object.entries(c.radii||{}).sort((a,b)=>+a[0]-+b[0]).map(([r,row])=>`<tr><td>${esc(radiusText(r))}</td><td>${esc(row.laws)}</td><td>${esc(row.alike)}</td><td>${esc(row.other)}</td><td>${esc(row.waiting)}</td><td>${bar(row)}</td></tr>`).join('');
    const seeds=c.seeds, sens=c.sensitivity;
    const seedLine=seeds?`its own campaign's seeds: ${Object.entries(seeds.own||{}).map(([k,v])=>`${esc(k)} ${esc(v)}`).join(', ')} · on more seeds: ${Object.entries(seeds.more||{}).map(([k,v])=>`${esc(k)} ${esc(v)}`).join(', ')} · ${seeds.reproduced?'its own seeds reproduced':'<b class=warn>its own seeds did not reproduce</b>'}`:'its seeds: waiting for the seeds campaign to decide';
    const lines=Object.entries(c.boundaries||{}).map(([p,b])=>`<li>toward ${esc(short(p))}: between ${esc(b.between[0])} and ${esc(b.between[1])} of the line, ${esc(b.kinds[0])} to ${esc(b.kinds[1])}${b.why?` (${esc(b.why)})`:''}</li>`).join('');
    const depth=c.depth||{};
    const early=c.early_call;
    return `<div class=toolbar><b>${lawLink(c.law,c.of,c.label,c.origin)}</b><span class=muted>score ${scoreText(c)} · its kind at 16,384: ${esc(c.kind??'not read here yet')}${c.identified_from?`, read so from N=${esc(num(c.identified_from))}`:''} · ${esc(stageText(c.stage))}${c.why?` (${esc(c.why)})`:''}</span><button type=button class=gsd-control data-admin-write data-map-do=skip data-map-law="${esc(c.law)}">skip this law</button></div>
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
    return `<table class=map-depth><thead><tr><th>law</th><th>deepest</th><th>holds its kind to</th><th>invalidated at</th><th>its kinds in the depth campaign</th></tr></thead><tbody>${all.map(([law,e])=>`<tr><td>${lawLink(law,e.of,e.label,e.origin)}</td><td>${esc(size(e.deepest))}</td><td>${esc(size(e.holds_to))}</td><td>${e.invalidated_at!=null?`<b class=warn>${esc(num(e.invalidated_at))}</b>`:'no'}</td><td class=muted>${Object.entries(e.kinds||{}).map(([n,k])=>`${esc(num(n))} ${esc(k)}`).join(' · ')}</td></tr>`).join('')}</tbody></table>`}
  function queue(d){
    const q=(d&&d.focus&&d.focus.queue)||[];
    if(!q.length)return '<div class=empty>the queue arrives with the focus’s first step</div>';
    return `<table class=map-queue><thead><tr><th></th><th>law</th><th>score</th><th>where it stands</th><th></th></tr></thead><tbody>${q.map((e,i)=>{
      const free=e.status==='waiting', back=e.status==='skipped'||!['waiting','in focus'].includes(e.status);
      return `<tr><td class=muted>${i+1}</td><td>${lawLink(e.law,e.campaign,e.label,e.origin)}</td><td>${scoreText(e)}</td><td>${esc(e.status)}${e.region?` · ${esc(e.region)}`:''}${e.type?` <span class=muted>· ${esc(e.type)}</span>`:''}</td><td>${free?`<button type=button class=chip data-admin-write data-map-do=skip data-map-law="${esc(e.law)}">skip</button>`:''}${back?`<button type=button class=chip data-admin-write data-map-do=back data-map-law="${esc(e.law)}">put back</button>`:''}</td></tr>`}).join('')}</tbody></table>`}
  function done(d){
    const list=((d&&d.focus&&d.focus.done)||[]).slice().reverse();
    if(!list.length)return '<div class=empty>no law’s focus has ended yet</div>';
    return `<ul class=map-done>${list.map(e=>`<li><b>${lawLink(e.law,e.of,e.label,e.origin)}</b> ${esc(e.stage)}${e.region?` as ${esc(e.region)}`:''}${e.type?` (${esc(e.type)})`:''}${e.why?`: ${esc(e.why)}`:''}${e.sensitivity?` · sensitive to ${esc(e.sensitivity.on)}`:''}${e.core?` · core: ${esc(e.core.join(', ')||'none alone')}`:''}</li>`).join('')}</ul>`}
  function bytesText(n){n=+n||0;const u=['B','KiB','MiB','GiB','TiB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return `${n<10&&i?n.toFixed(1):Math.round(n)} ${u[i]}`}
  function seedState(b){
    const m=b.seeded;
    if(m&&m.selected)return `<span class=good>in the map since ${esc(String(m.at||'').replace('T',' ').slice(0,16))}</span>${m.laws_recorded===false?' <span class=muted title="read before its laws were recorded one by one: synchronize reads it again for each law\u2019s score and code">(synchronize to read its scores)</span>':` <span class=muted>${esc(num(m.laws_standing||0))} laws, regions ${esc((m.regions||[]).join(', ')||'none')}</span>`}`;
    if(m)return `<span class=muted>let go ${esc(String(m.let_go_utc||'').replace('T',' ').slice(0,16))}; its readings kept</span>`;
    if(b.identical_to)return `<b class=warn>identical to ${esc(b.identical_to)}: refused</b>`;
    return '<span class=muted>not in the map</span>'}
  function importRow(b){
    if(!b.readable)return `<tr class=map-import-unread><td></td><td><code>${esc(b.name)}</code></td><td colspan=6 class=muted>not readable yet${b.why?`: ${esc(b.why)}`:''} (still being copied?)</td></tr>`;
    const same=b.science_same?'<span class=good>same</span>':`<b class=warn title="${esc((b.science_differ||[]).join(', '))}">another science: refused</b>`;
    const on=!!(b.seeded&&b.seeded.selected), can=b.science_same&&!b.identical_to&&(b.in_folder!==false||b.seeded);
    const where=b.in_folder===false?' <span class=muted title="read from its path or no longer in the import folder">(not in the folder)</span>':'';
    return `<tr><td><input type=checkbox class=map-import-tick data-admin-write data-import-name="${esc(b.bundle||b.name)}" ${on?'checked ':''}${can?'':'disabled'}></td><td><code>${esc(b.name)}</code>${where}</td><td>study ${esc(b.study)}</td><td>${b.build!=null?`build ${esc(b.build)}`:'<span class=muted>-</span>'}</td><td>${esc(String(b.built_utc||'').replace('T',' ').replace('Z',' UTC'))}</td><td>${b.bytes!=null?esc(bytesText(b.bytes)):'<span class=muted>-</span>'}</td><td>${esc(num(b.scoring||0))} scoring laws${b.laws!=null?` of ${esc(num(b.laws))}`:''}${b.regions!=null?`, ${esc(num(b.regions))} region${+b.regions===1?'':'s'}`:''}</td><td>${same} ${seedState(b)}</td></tr>`}
  function seeds(d){
    const f=d&&d.focus, im=(d&&d.imports)||{};
    const where=im.folder?`<div class="toolbar map-import-where"><span>the import folder:</span> <code id=mapImportFolder>${esc(im.folder)}</code><button type=button class=gsd-control data-admin-write data-map-do=open_import title="open this folder in the file manager of the machine GSD runs on">open the folder</button><button type=button class=chip data-map-copy="${esc(im.folder)}" title="copy the folder's path">copy the path</button></div>
      <div class=muted>Put a study bundle into it, its <code>.tar.zst</code> as downloaded or its unpacked folder; it is listed below within a few seconds. Nothing in the folder is changed.</div>`
      :`<div class=empty>${esc(im.why||'no import folder')}</div>`;
    const list=(im.bundles||[]);
    const table=list.length?`<table class=map-imports><thead><tr><th title="ticked: its laws and regions are in this study's map">in the map</th><th>bundle</th><th>study</th><th>build</th><th>built</th><th>size</th><th>its laws</th><th>science and state</th></tr></thead><tbody>${list.map(importRow).join('')}</tbody></table>
      <div class=toolbar><button type=button class=gsd-control data-admin-write data-map-do=synchronize ${f?'':'disabled'} title="read in what is newly ticked and let go of what is unticked: its laws no longer focused on or taken deeper, its regions off the map; the readings already taken are kept">synchronize</button>${f?'':'<span class=muted>a seed joins a focus: start one first</span>'}</div>
      <div class="muted map-merge-line">A merged set is a new bundle, made on Reports.</div>`
      :(im.folder?'<div class=empty>no study bundle in the import folder yet</div>':'');
    return `${where}${table}${!list.length&&f?'<div class=empty>no seed yet: the study maps from its own laws alone</div>':''}`}
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
    const typing=['mapLean','mapRings','mapConfirm','mapContenders','mapOutward','mapInside','mapPerType','mapStudy'].some(id=>{const el=document.getElementById(id);return el&&document.activeElement===el});
    const box=document.getElementById('mapSettings');if(box)settingsOpen=!!box.open;
    if(!typing)put('mapControls',controls(data));
    put('mapCurrent',current(data));put('mapRegions',regions(data));put('mapDepth',depthTable(data));put('mapQueue',queue(data));put('mapFocusList',listTable(data,'focus'));put('mapDepthList',listTable(data,'depth'));put('mapDone',done(data));put('mapRunOn',runOn(data));put('mapSeed',seeds(data));
    document.querySelectorAll('.map-import-tick').forEach(t=>{const k=t.getAttribute('data-import-name');if(k in pendingTicks)t.checked=!!pendingTicks[k]});
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
    if(what==='synchronize')return {do:'synchronize',ticked:[...document.querySelectorAll('.map-import-tick')].filter(t=>t.checked).map(t=>t.getAttribute('data-import-name'))};
    if(what==='open_import')return {do:'open_import'};
    if(what==='order')return {do:'order',list:button.getAttribute('data-map-list'),law:law||'',move:button.getAttribute('data-map-move')};
    if(what==='run_on_clear')return {do:'run_on',clear:true};
    return {do:'settings',settings:{radii:parseRings(value('mapRings')),confirm_share:+value('mapConfirm'),contenders:+value('mapContenders'),outward_most:+value('mapOutward'),inside_share:+value('mapInside'),mapped_per_type:+value('mapPerType')||3}}}
  function doneNote(body,d){
    if(body.do!=='synchronize'||!d)return `done: ${body.do}`;
    const parts=[];
    (d.read_in||[]).forEach(r=>parts.push(`read in ${r.bundle}${r.read_again?' again':''}: ${num(r.laws_added||0)} laws new, ${num(r.laws_standing||0)} standing on its scores`));
    (d.let_go||[]).forEach(r=>parts.push(`let go of ${r.bundle}`));
    (d.refused||[]).forEach(r=>parts.push(`refused ${r.name}: ${r.why}`));
    return parts.length?parts.join(' · '):'synchronized: nothing changed'}
  async function act(body){
    note='';
    try{data=await SYS.postJson('/api/focus',body);note=doneNote(body,data);if(body.do==='synchronize')pendingTicks={}}
    catch(e){note=String((e&&e.message)||e)}
    render(data)}
  function wire(){
    if(wired)return;const root=document.getElementById('gsdMap');if(!root)return;wired=true;
    root.addEventListener('click',e=>{
      const copy=e.target.closest&&e.target.closest('[data-map-copy]');if(copy){const text=copy.getAttribute('data-map-copy');Promise.resolve(navigator.clipboard&&navigator.clipboard.writeText(text)).then(()=>{copy.textContent='copied'}).catch(()=>{});return}
      const button=e.target.closest&&e.target.closest('[data-map-do]');if(!button)return;
      let body;try{body=bodyFor(button)}catch(err){note=String(err.message||err);render(data);return}
      act(body)});
    root.addEventListener('input',e=>{if(e.target&&e.target.id==='mapLean'){const v=+e.target.value,out=document.getElementById('mapLeanValue');if(out)out.textContent=`${100-v}% random \u00b7 ${v}% focus`}});
    root.addEventListener('change',e=>{if(e.target&&e.target.classList&&e.target.classList.contains('map-import-tick'))pendingTicks[e.target.getAttribute('data-import-name')]=!!e.target.checked;if(e.target&&e.target.id==='mapLean')act({do:'lean',focus:(+e.target.value)/100})})}
  async function refresh(force){
    if(busy&&!force)return;busy=true;
    try{data=await SYS.getJson('/api/focus')}
    catch(e){note=String((e&&e.message)||e)}
    finally{busy=false;render(data)}}
  window.GSD_MAP={refresh,render,act,bodyFor,parseRings,ringsText,lawHref,doneNote,get data(){return data},set data(v){data=v},get note(){return note},get pendingTicks(){return pendingTicks}};
})();
