(function(){
  const SYS=window.GSD_SYSTEM, esc=SYS.esc;
  let data=null, busy=false, note='', wired=false, settingsOpen=false, lawsOpen=false, pendingTicks={}, offsetMs=0, ticking=false;
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
  const pad=v=>String(v).padStart(2,'0');
  function forText(s){if(s==null||!isFinite(+s))return '';s=Math.max(0,Math.round(+s));if(s<60)return `${s} s`;if(s<3600)return `${Math.floor(s/60)}:${pad(s%60)}`;return `${Math.floor(s/3600)} h ${pad(Math.floor((s%3600)/60))} min`}
  function longText(s){s=Math.max(0,+s||0);if(s<90)return `${Math.round(s)} s`;const m=Math.round(s/60);return m<90?`${m} min`:`${Math.floor(m/60)} h ${pad(m%60)} min`}
  function clockText(utc){const s=String(utc||'');return s.length>=16?`${s.slice(11,16)} UTC`:s}
  function since(utc,seconds){return `<span class=map-since data-map-since="${esc(utc||'')}">${esc(forText(seconds))}</span>`}
  function secondsOf(utc){const at=Date.parse(String(utc||''));return isFinite(at)?Math.max(0,(Date.now()-offsetMs-at)/1000):null}
  function runBar(r){const share=r.typical?Math.min(1,(+r.seconds||0)/+r.typical):0;return r.typical?`<span class="map-run-bar${(+r.seconds||0)>+r.typical?' over':''}" title="running for its typical time at this size: past the end it runs longer than the median" data-map-since="${esc(r.started_utc||'')}" data-map-typical="${esc(r.typical)}"><span style="width:${(100*share).toFixed(1)}%"></span></span>`:''}
  function tick(){
    const root=document.getElementById('gsdMap');if(!root||root.hidden)return;
    root.querySelectorAll('[data-map-since]').forEach(el=>{const s=secondsOf(el.getAttribute('data-map-since'));if(s==null)return;const typical=+el.getAttribute('data-map-typical');
      if(typical){const fill=el.firstElementChild;if(fill)fill.style.width=`${(100*Math.min(1,s/typical)).toFixed(1)}%`;el.classList.toggle('over',s>typical)}else el.textContent=forText(s)})}
  const STAGE_ORDER=['running','queued','being read','waiting for the decider','its next size due','held','failed','decided','not started','read'];
  function whereText(w,read_n){
    const at=w.n!=null?` N=${num(w.n)}`:'';
    if(w.stage==='running')return `running at${at}: ${num(w.done||0)} of ${num(w.seeds||3)} seeds done, ${num(w.running||0)} running${w.queued?`, ${num(w.queued)} queued`:''}`;
    if(w.stage==='queued')return `queued at${at}: ${num(w.done||0)} of ${num(w.seeds||3)} seeds done, ${num(w.queued||0)} waiting for a worker`;
    if(w.stage==='being read')return `its probes being read at${at}`;
    if(w.stage==='waiting for the decider')return `${at.trim()} done and read, waiting for the decider`;
    if(w.stage==='its next size due')return `sent on to${at}, its runs not made yet`;
    if(w.stage==='held')return `<b class=warn>held at${at}</b> (${esc(w.rule||'')})`;
    if(w.stage==='failed')return `<b class=warn>failed at${at}</b>`;
    if(w.stage==='decided')return `decided at${at} (${esc(w.rule||'')}): read at the focus's next step`;
    if(w.stage==='read')return `read at N=${num(read_n)}`;
    return 'not started: no run made yet'}
  function soFarText(p){const s=p.so_far;if(!s)return '<span class=muted>no size read yet</span>';return `${esc(num(s.n))}: ${esc(s.kind)}${s.alike==null?'':s.alike?' <span class=good title="the law in focus reads the same at this size">✓</span>':` <span class=warn title="the law in focus reads ${esc(s.law_reads)} at this size">✗</span>`}`}
  function partText(p){return p.part==='neighbour'?`ring ${esc(radiusText(p.radius))}`:p.part==='term off'?`${esc(p.term)} off`:'on a line to a boundary'}
  function zoneLaws(z){
    const pts=((z&&z.points)||[]).slice().sort((a,b)=>STAGE_ORDER.indexOf(a.where.stage)-STAGE_ORDER.indexOf(b.where.stage)||(+b.where.seconds||0)-(+a.where.seconds||0));
    if(!pts.length)return '';
    const read_n=(z.ladder||[]).slice(-1)[0]||16384;
    const rows=pts.map(p=>`<tr class="map-stage-${esc(String(p.where.stage).replace(/\s+/g,'-'))}"><td>${lawLink(p.law,z.campaign,p.label)}</td><td>${partText(p)}</td><td>${whereText(p.where,read_n)}</td><td>${p.where.since?since(p.where.since,p.where.seconds):''}</td><td>${soFarText(p)}</td><td>${p.verdict==null?'<span class=muted>not yet</span>':`${esc(p.verdict)} ${p.alike?'<b class=good>alike</b>':'<b class=warn>other</b>'}`}</td></tr>`).join('');
    return `<details class=map-zone-laws id=mapZoneLaws${lawsOpen?' open':''}><summary>every law of the zone, where it stands now (${esc(num(pts.length))})</summary>
      <table class=map-zone-table><thead><tr><th>law</th><th>its part</th><th>where it stands</th><th title="how long it has stood there">for</th><th title="its kind at the largest size all its seeds have read, against the law in focus at that size">so far</th><th>read at ${esc(num(read_n))}</th></tr></thead><tbody>${rows}</tbody></table></details>`}
  function zoneStrip(d){
    const z=d&&d.zone_now;if(!z)return '';
    if(z.error)return `<div class="map-zone-now warn">the zone's live reading failed: ${esc(z.error)}</div>`;
    const w=z.workers||{}, an=z.analyses||{}, zone=z.zone;
    const who=['zone','zone seeds','depth','Dex laws','blind','other'].filter(k=>w[k]).map(k=>`${esc(k)} <b>${esc(num(w[k]))}</b>`).join(' · ')||'<b class=warn>nothing running</b>';
    const asked='';
    const first=z.zone_first||{}, behind=((first.N||{}).waiting||0)+((first.S||{}).waiting||0);
    const earlier=(z.running||[]).filter(r=>/^an earlier law/.test(r.part||'')).length;
    const back=behind||earlier?` · <span title="runs of laws no longer in focus: they wait behind the runs of the law in focus and take a worker only when it has none queued">earlier laws' zones: ${esc(num(earlier))} running, ${esc(num(behind))} queued behind this law's</span>`:'';
    let html=`<div class=map-zone-workers>running now: ${who}${asked}${back} · probes ${esc(num(an.running||0))} running, ${esc(num(an.queued||0))} queued</div>`;
    if(zone){
      const p=zone.pace||{}, lastAt=(zone.points||[]).map(x=>x.read_at).filter(Boolean).sort().slice(-1)[0];
      const probes=zone.probes_waiting||0;
      const eta=zone.eta_seconds!=null?`about <b>${esc(longText(zone.eta_seconds))}</b> of work left at its ${esc(num(w.zone||0))} zone workers now${zone.left_unknown?', some sizes not timed yet':''} <span class=muted>(at most: a law stopped by a rule needs less)</span>`:p.read>=p.of?'every law of the zone read':probes?`its runs are done: <b>${esc(num(probes))}</b> probe readings to come, read before any other work`:w.zone?'':'<b class=warn>no zone worker is running now</b>';
      html=`<div class=map-zone-now>on it for <b>${since(p.began_utc,p.on_it_seconds)}</b>${p.began_utc?` (since ${esc(clockText(p.began_utc))})`:''} · <b>${esc(num(p.read))} of ${esc(num(p.of))}</b> of its laws read, ${esc(num(p.read_last_hour||0))} in the last hour${lastAt?`, the last ${since(lastAt,p.last_read_seconds)} ago`:''} · ${eta}</div>`+html}
    return html}
  function stageText(s){return {neighbourhood:'reading its neighbourhood',boundaries:'halving its boundaries',mapped:'mapped',unconfirmed:'a lucky hit: no zone found around it, kept to revisit',invalidated:'invalidated'}[s]||String(s||'')}
  function controls(d){
    const f=d&&d.focus, studies=(d&&d.studies)||[];
    const said=note?`<div class="muted map-note">${esc(note)}</div>`:'';
    if(!f){
      const options=studies.map(s=>`<option value="${esc(s.study)}">study ${esc(s.study)} (${esc(s.campaigns)} campaigns)</option>`).join('');
      return `<div class=toolbar><span class=muted>no focus in this folder</span>${studies.length?`<select id=mapStudy data-admin-write>${options}</select><button type=button class=gsd-control data-admin-write data-map-do=start>start the focus</button>`:'<span class=muted>and no study to focus on</span>'}</div>${said}`}
    const s=f.settings||{}, next=f.next_settings;
    const camps=f.campaigns||{};
    const work=(d&&d.work)||{};
    const workText=[['N','zone worker, neighbours'],['S','zone worker, more seeds'],['D','depth worker']].map(([k,name])=>{const r=work[k]||{};return `${name} (C${esc(r.campaign||camps[k]||'?')}): running ${esc(num(r.running||0))}, queued ${esc(num(r.queued||0))}, ${esc(num(r.done||0))} done${r.deepest?`, deepest N=${esc(num(r.deepest))}`:''}`}).join(' · ');
    return `<div class="map-doing${f.failing?' warn':''}" id=mapDoing title="what the focus does now and why, read every 4 s"><b>${esc(f.doing||'the focus waits for its first step')}</b></div>
      <div class=muted>study <b>${esc(f.study)}</b> · ${f.stopped?'<b class=warn>the focus is off</b>':'the focus runs'}</div>
      ${orderLine(d)}
      <div class=muted>${workText}</div>
      <details class=map-settings id=mapSettings${settingsOpen?' open':''}><summary>the focus’s settings: how it maps a law (rarely changed; a change applies from the next law)</summary>
      <ul class="muted map-settings-words">
        <li><b>rings</b>: how far from the law its neighbours are drawn, and how many on each ring: <code>0.1:8</code> is 8 laws whose couplings differ by up to 10%.</li>
        <li><b>confirm at 0.1 by</b>: the share of the 0.1 ring that must read the law’s own kind before its kind counts as confirmed.</li>
        <li><b>deep laws</b>: how many of the best laws the depth seeker takes to larger sizes.</li>
        <li><b>widest ring</b>: the farthest the rings go out when a zone is mapped outward.</li>
        <li><b>inside a zone below</b>: a law closer than this share of a mapped zone’s reach to it counts as inside it, and is not focused on again.</li>
        <li><b>a type known after</b>: how many laws of a type must be mapped before the focus prefers types it knows less.</li></ul>
      <div class=toolbar><label class=muted>rings <input id=mapRings data-admin-write type=text value="${esc(ringsText((next||s).radii))}" style="width:26em"></label>
        <label class=muted>confirm at ${esc(radiusText(s.confirm_radius))} by <input id=mapConfirm data-admin-write type=number min=0.5 max=1 step=0.01 value="${esc((next||s).confirm_share)}" style="width:5em"></label>
        <label class=muted>deep laws <input id=mapContenders data-admin-write type=number min=0 max=20 step=1 value="${esc((next||s).contenders)}" style="width:4em"></label>
        <label class=muted>widest ring <input id=mapOutward data-admin-write type=number min=0.1 max=0.95 step=0.05 value="${esc((next||s).outward_most)}" style="width:5em"></label>
        <label class=muted>inside a zone below <input id=mapInside data-admin-write type=number min=0 max=1 step=0.05 value="${esc((next||s).inside_share)}" style="width:5em"> of its reach</label>
        <label class=muted title="the focus takes first the law whose type is least known; a type counts as known once this many of its laws are mapped, a one-dimensional form (a ring or a line) counting one from the start">a type known after <input id=mapPerType data-admin-write type=number min=1 max=50 step=1 value="${esc((next||s).mapped_per_type??3)}" style="width:4em"> laws</label>
        <button type=button class=gsd-control data-admin-write data-map-do=settings>apply from the next law</button></div>
      ${next?`<div class=muted>the next law takes: rings ${esc(ringsText(next.radii))}, confirmed by ${esc(next.confirm_share)}, ${esc(next.contenders)} deep laws, rings to ${esc(next.outward_most)}</div>`:''}</details>${said}`}
  function orderLine(d){
    const o=(d&&d.zone_now&&d.zone_now.order)||{}, names=o.names||['the zone of the law in focus','the depth worker','the Dex laws read again','the blind draw',"earlier laws' leftovers"];
    const queued=o.queued||{};
    const steps=names.map((n,i)=>`${i+1} ${i===o.tier?`<b>${esc(n)}</b>`:esc(n)}${queued[n]!=null?` <span class=muted>(${esc(num(queued[n]))} queued)</span>`:''}`).join(' \u2192 ');
    return `<div class="map-order" title="the fleet takes its work in this order, runs and probes alike: each step takes a worker only when the steps before it have nothing queued, and a run under way is never stopped for one before it; there is no share to set">the fleet\u2019s order: ${steps}${o.name?` \u00b7 now on: <b>${esc(o.name)}</b>`:''}</div>`}
  function listTable(d,which){
    const rows=((d&&d.focus&&d.focus.lists)||{})[which]||[];
    if(!rows.length)return `<div class=empty>${which==='focus'?'no scoring law waits for the focus':'no law to take deeper yet'}</div>`;
    return `<table class=map-queue><thead><tr><th></th><th>law</th><th>score</th><th>type</th><th>identified from</th><th></th></tr></thead><tbody>${rows.map((e,i)=>`<tr><td class=muted>${i+1}</td><td>${lawLink(e.law,e.campaign,e.label,e.origin)}${e.placed?' <span class=muted title="placed by hand">\u2022</span>':''}</td><td>${scoreText(e)}</td><td>${esc(e.type||'not read yet')}</td><td>${e.identified_from?`N=${esc(num(e.identified_from))}`:'<span class=muted>not yet</span>'}</td><td><button type=button class=chip data-admin-write data-map-do=order data-map-list="${which}" data-map-move=up data-map-law="${esc(e.law)}" ${i?'':'disabled'}>\u2191</button> <button type=button class=chip data-admin-write data-map-do=order data-map-list="${which}" data-map-move=down data-map-law="${esc(e.law)}" ${i<rows.length-1?'':'disabled'}>\u2193</button>${which==='focus'?` <button type=button class=chip data-admin-write data-map-do=skip data-map-law="${esc(e.law)}">skip</button>`:(e.in_depth?' <span class=muted>in the depth campaign</span>':'')}</td></tr>`).join('')}</tbody></table><div class=toolbar><button type=button class=chip data-admin-write data-map-do=order data-map-list="${which}" data-map-move=reset title="forget the order set by hand and take the suggested one">the suggested order</button></div>`}
  function current(d){
    const c=d&&d.focus&&d.focus.current;
    if(!c)return `<div class=empty>${d&&d.focus?'no law is in focus now: every scoring law is mapped, inside a mapped zone, or skipped':'no focus in this folder'}</div>`;
    const z=(d.zone_now&&d.zone_now.zone)||null, live=(z&&z.rings)||{};
    const liveCells=k=>{const r=live[k];if(!r)return '<td colspan=6 class=muted>live reading not here</td>';const between=(r['waiting for the decider']||0)+(r['its next size due']||0)+(r.decided||0),stuck=(r.held||0)+(r.failed||0),seen=(r.alike_so_far||0)+(r.other_so_far||0);
      return `<td>${esc(num(r.running||0))}</td><td>${esc(num(r.queued||0))}</td><td>${esc(num((r['being read']||0)+between))}</td><td>${stuck?`<b class=warn>${esc(num(stuck))}</b>`:'0'}</td><td>${esc(num(r['not started']||0))}</td><td>${seen?`${esc(num(r.alike_so_far||0))} of ${esc(num(seen))}`:'<span class=muted>none yet</span>'}</td>`};
    const rows=Object.entries(c.radii||{}).sort((a,b)=>+a[0]-+b[0]).map(([r,row])=>`<tr><td>${esc(radiusText(r))}</td><td>${esc(row.laws)}</td><td>${esc(row.read??'')}</td><td>${esc(row.alike)}</td><td>${esc(row.other)}</td><td>${esc(row.waiting)}</td>${liveCells(r)}<td>${bar(row)}</td></tr>`).join('')
      +['term off','line'].filter(k=>live[k]).map(k=>{const r=live[k];return `<tr><td>${k==='term off'?'terms off':'boundary lines'}</td><td>${esc(r.laws)}</td><td>${esc(r.read)}</td><td colspan=2 class=muted>see below</td><td>${esc(num(r.laws-r.read))}</td>${liveCells(k)}<td></td></tr>`}).join('');
    const seeds=c.seeds, sens=c.sensitivity;
    const at=Object.values(seeds&&seeds.compared_at||{}),atText=at.length?` at N=${esc(num(Math.max(...at)))}`:'';
    const seedLine=seeds?`its own campaign's seeds: ${Object.entries(seeds.own||{}).map(([k,v])=>`${esc(k)} ${esc(v)}`).join(', ')} · on more seeds: ${Object.entries(seeds.more||{}).map(([k,v])=>`${esc(k)} ${esc(v)}`).join(', ')} · ${seeds.reproduced?`its own seeds reproduced${atText}`:at.length?`<b class=warn>its own seeds did not reproduce${atText}</b>`:'its own seeds not yet read at a size both campaigns reached'}`:'its seeds: read once the seeds campaign is decided and its own kind is read';
    const lines=Object.entries(c.boundaries||{}).map(([p,b])=>`<li>toward ${esc(short(p))}: between ${esc(b.between[0])} and ${esc(b.between[1])} of the line, ${esc(b.kinds[0])} to ${esc(b.kinds[1])}${b.why?` (${esc(b.why)})`:''}</li>`).join('');
    const depth=c.depth||{};
    const early=c.early_call;
    return `<div class=toolbar><b>${lawLink(c.law,c.of,c.label,c.origin)}</b><span class=muted>score ${scoreText(c)} · its kind at 16,384: ${esc(c.kind??'not read here yet')}${c.kind_from&&c.kind!=null?` (in ${esc(c.kind_from)})`:''}${c.identified_from?`, read so from N=${esc(num(c.identified_from))}`:''} · ${esc(stageText(c.stage))}${c.why?` (${esc(c.why)})`:''}</span><button type=button class=gsd-control data-admin-write data-map-do=skip data-map-law="${esc(c.law)}">skip this law</button></div>
      ${early?`<div class=muted title="each neighbour's kind at the size this law is identified from, against its kind at 16,384: how far a smaller read would have called it">the call at N=${esc(num(early.at_n))} agrees with 16,384 on ${esc(num(early.agreed))} of ${esc(num(early.of))} neighbours read</div>`:''}
      ${zoneStrip(d)}
      ${needsLine(c,z)}
      <table class=map-rings><thead><tr><th>ring</th><th>laws</th><th title="neighbours with a reading at 16,384">read</th><th>alike</th><th>other</th><th title="not read yet, or read while the law's own kind is not">waiting</th><th title="of those waiting: a seed of it running now">running</th><th title="of those waiting: its next seeds queued for a worker">queued</th><th title="of those waiting: a size done, its probes being read or the decider about to send it on">between sizes</th><th title="held by the decider or failed: these do not move by themselves">held</th><th title="no run made yet">not started</th><th title="those waiting that read a size with all their seeds: how many read the law's own kind at that size">alike so far</th><th></th></tr></thead><tbody>${rows||'<tr><td colspan=13 class=muted>no ring yet</td></tr>'}</tbody></table>
      ${z&&z.judged?`<div class="muted map-judged" title="how a neighbour is judged: one category, its kind, read at one size">${esc(z.judged)}</div>`:''}
      ${zoneLaws(z)}
      <div class=muted>${seedLine}</div>
      <div>${sens?`sensitive to <b>${esc(sens.on)}</b>: ${esc(sens.words)}`:'<span class=muted>sensitive to: not read yet (its seeds and the rings of 1e-3 or less)</span>'}</div>
      <div class=muted>its zone ${c.confirmed_at!=null&&(c.alike_to==null||+c.confirmed_at>+c.alike_to)?`stands at ring ${esc(radiusText(c.confirmed_at))}`:`reaches ${c.alike_to!=null?esc(c.alike_to):'no ring yet'}`} · its depth: deepest ${esc(size(depth.deepest))}, holds to ${esc(size(depth.holds_to))}${depth.invalidated_at!=null?`, <b class=warn>invalidated at ${esc(num(depth.invalidated_at))}</b>`:''}</div>
      ${lines?`<ul class=map-lines>${lines}</ul>`:''}${termsLine(c)}`}
  function needsLine(c,z){
    const n=c.needs||[], at=(z&&z.needs_at)||{};
    if(!n.length)return '';
    const open=n.filter(x=>!x.done).length;
    return `<div class="map-needs${open?'':' good'}" title="what the zone worker waits for before it maps this law: every line must hold">${open?`to map it, ${esc(num(open))} of ${esc(num(n.length))} still to come:`:'every condition holds: it is being mapped'} ${n.map(x=>`<span class="${x.done?'good':'muted'}">${x.done?'\u2713':'\u2717'} ${esc(x.what)}: ${esc(x.said)}${x.done&&at[x.what]?` (since ${esc(clockText(at[x.what]))})`:''}</span>`).join(' \u00b7 ')}</div>`}
  function termsLine(e){
    const t=Object.entries(e.terms||{});
    if(!t.length)return '';
    const each=t.map(([name,row])=>`${esc(name)}: ${row.load_bearing==null?'waiting':row.load_bearing?`<b>load-bearing</b> (off, it reads ${esc(row.kind)})`:'not load-bearing'}`).join(' · ');
    return `<div class=muted>each term switched off: ${each}${e.core?` · <b>its core: ${esc(e.core.join(', ')||'none of its terms alone')}</b>`:''}</div>`}
  function working(d){
    const z=d&&d.zone_now;
    if(!z)return '<div class=empty>the fleet\u2019s work arrives with the focus</div>';
    if(z.error)return `<div class=warn>the live reading failed: ${esc(z.error)}</div>`;
    const rows=z.running||[];
    if(!rows.length)return '<div class=empty>nothing is running now</div>';
    return `<table class=map-working><thead><tr><th>who</th><th>law</th><th>what it is</th><th>N</th><th>seed</th><th>running for</th><th title="the median time of one seed at this size over the last ${esc(num((z.typical||{}).hours||6))} hours: the zone's own runs where it has them, else the fleet's">typical</th><th></th></tr></thead><tbody>${rows.map(r=>`<tr class="map-role map-role-${esc(String(r.role).replace(/\s+/g,'-').toLowerCase())}"><td>${esc(r.role)}</td><td>${lawLink(r.law,r.campaign,r.label)}</td><td>${esc(r.part)}</td><td>${esc(num(r.n))}</td><td>${esc(r.seed)}</td><td>${since(r.started_utc,r.seconds)}</td><td>${r.typical!=null?esc(forText(r.typical)):'<span class=muted>not timed yet</span>'}</td><td>${runBar(r)}</td></tr>`).join('')}</tbody></table>`}
  function rangeText(lo,hi){return lo===hi?esc(Number(lo).toPrecision(4)):`${esc(Number(lo).toPrecision(4))} to ${esc(Number(hi).toPrecision(4))}`}
  function regions(d){
    const list=(d&&d.focus&&d.focus.regions)||[];
    if(!list.length)return '<div class=empty>no zone mapped yet: a zone is named once its law is mapped</div>';
    const touch=((d.focus.touching)||[]).map(t=>`<li>${esc(t.regions[0])} (${esc(t.kinds[0])}) and ${esc(t.regions[1])} (${esc(t.kinds[1])}) overlap in every coupling: a boundary lies between them</li>`).join('');
    return list.map(r=>`<div class=map-region><div><b>${esc(r.name)}</b> <span class=muted>${esc(r.kind)} · ${esc(r.members)} laws read its kind · from ${esc((r.labels||[]).join(', '))}${r.alike_to!=null?` · every ring to ${esc(r.alike_to)} alike`:''} · ${esc((r.boundaries||[]).length)} boundaries${Object.keys(r.cores||{}).length?` · core terms: ${Object.entries(r.cores).map(([l,c])=>`${esc(c.join(', ')||'none alone')} (${esc(l)})`).join('; ')}`:''}${r.seeded_from?` · seeded from ${esc(r.seeded_from.bundle)}`:''}</span></div>
      <table class=map-ranges><tbody>${Object.entries(r.ranges||{}).map(([axis,[lo,hi]])=>`<tr><td>${esc(axis)}</td><td>${rangeText(lo,hi)}</td></tr>`).join('')}</tbody></table></div>`).join('')+(touch?`<ul class=map-touching>${touch}</ul>`:'')}
  function depthTable(d){
    const all=Object.entries((d&&d.focus&&d.focus.contenders)||{});
    if(!all.length)return '<div class=empty>no law is being taken deeper yet</div>';
    const now=(d.focus.depth_now||{}).law,ended=d.focus.depth_done||{};
    const where=law=>law===now?'<b>now</b>':ended[law]?`<span class=muted>ended${ended[law].rule?` (${esc(ended[law].rule)}${ended[law].at_n?` at N=${esc(num(ended[law].at_n))}`:''})`:''}</span>`:'<span class=muted>waiting</span>';
    return `<table class=map-depth><thead><tr><th>law</th><th title="the depth worker takes one law at a time: the law in focus first, then the depth list in its order">depth worker</th><th>deepest</th><th>holds its kind to</th><th>invalidated at</th><th title="the next size priced from the law's own peak memory at the sizes below; past half the host's memory, the law is settled at its memory ceiling">memory ceiling</th><th>its kinds in the depth campaign</th></tr></thead><tbody>${all.map(([law,e])=>`<tr><td>${lawLink(law,e.of,e.label,e.origin)}</td><td>${where(law)}</td><td>${esc(size(e.deepest))}</td><td>${esc(size(e.holds_to))}</td><td>${e.invalidated_at!=null?`<b class=warn>${esc(num(e.invalidated_at))}</b>`:'no'}</td><td>${ceilingText(e.ceiling)}</td><td class=muted>${Object.entries(e.kinds||{}).map(([n,k])=>`${esc(num(n))} ${esc(k)}`).join(' · ')}</td></tr>`).join('')}</tbody></table>`}
  function ceilingText(c){if(!c)return '<span class=muted>not reached</span>';const g=b=>`${(+b/2**30).toFixed(1)} GiB`;return `<b class=warn title="priced from its own peaks at ${esc(c.from||'the sizes below')}, growth ${esc(c.growth)}; ${c.share!=null?`${esc(Math.round(100*c.share))}% of the host's ${esc(g(c.total_bytes||0))}`:`the host's reach ${esc(g(c.reach_bytes||0))} with ${esc(g(c.free_bytes||0))} kept free`}">settled at N=${esc(num(c.reached))}</b>: N=${esc(num(c.next_n))} needs ${esc(g(c.needs_bytes))}, ${esc(g(c.reach_bytes||0))} reachable`}
  function queue(d){
    const q=(d&&d.focus&&d.focus.queue)||[];
    if(!q.length)return '<div class=empty>the queue arrives with the focus’s first step</div>';
    return `<table class=map-queue><thead><tr><th></th><th>law</th><th>score</th><th>where it stands</th><th></th></tr></thead><tbody>${q.map((e,i)=>{
      const free=e.status==='waiting', back=e.status==='skipped'||!['waiting','in focus'].includes(e.status);
      return `<tr><td class=muted>${i+1}</td><td>${lawLink(e.law,e.campaign,e.label,e.origin)}</td><td>${scoreText(e)}</td><td>${esc(e.status==='unconfirmed'?'a lucky hit':e.status)}${e.region?` · ${esc(e.region)}`:''}${e.type?` <span class=muted>· ${esc(e.type)}</span>`:''}</td><td>${free?`<button type=button class=chip data-admin-write data-map-do=skip data-map-law="${esc(e.law)}">skip</button>`:''}${back?`<button type=button class=chip data-admin-write data-map-do=back data-map-law="${esc(e.law)}">put back</button>`:''}</td></tr>`}).join('')}</tbody></table>`}
  function done(d){
    const list=((d&&d.focus&&d.focus.done)||[]).slice().reverse();
    if(!list.length)return '<div class=empty>no law’s focus has ended yet</div>';
    return `<ul class=map-done>${list.map(e=>`<li><b>${lawLink(e.law,e.of,e.label,e.origin)}</b> ${esc(stageText(e.stage))}${e.region?` as ${esc(e.region)}`:''}${e.type?` (${esc(e.type)})`:''}${e.why?`: ${esc(e.why)}`:''}${e.sensitivity?` · sensitive to ${esc(e.sensitivity.on)}`:''}${e.core?` · core: ${esc(e.core.join(', ')||'none alone')}`:''}</li>`).join('')}</ul>`}
  function bytesText(n){n=+n||0;const u=['B','KiB','MiB','GiB','TiB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return `${n<10&&i?n.toFixed(1):Math.round(n)} ${u[i]}`}
  function seedState(b){
    const m=b.seeded;
    if(m&&m.selected)return `<span class=good>in the map since ${esc(String(m.at||'').replace('T',' ').slice(0,16))}</span>${m.laws_recorded===false?' <span class=muted title="read before its laws were recorded one by one: synchronize reads it again for each law\u2019s score and code">(synchronize to read its scores)</span>':` <span class=muted>${esc(num(m.laws_standing||0))} laws, zones ${esc((m.regions||[]).join(', ')||'none')}</span>`}`;
    if(m)return `<span class=muted>let go ${esc(String(m.let_go_utc||'').replace('T',' ').slice(0,16))}; its readings kept</span>`;
    if(b.identical_to)return `<b class=warn>identical to ${esc(b.identical_to)}: refused</b>`;
    return '<span class=muted>not in the map</span>'}
  function importRow(b){
    if(!b.readable)return `<tr class=map-import-unread><td></td><td><code>${esc(b.name)}</code></td><td colspan=6 class=muted>not readable yet${b.why?`: ${esc(b.why)}`:''} (still being copied?)</td></tr>`;
    const same=b.science_same?'<span class=good>same</span>':`<b class=warn title="${esc((b.science_differ||[]).join(', '))}: its laws come in alone, each run here from nothing, no score or zone carried">another science: laws only</b>`;
    const on=!!(b.seeded&&b.seeded.selected), can=!b.identical_to&&(b.in_folder!==false||b.seeded);
    const where=b.in_folder===false?' <span class=muted title="read from its path or no longer in the import folder">(not in the folder)</span>':'';
    return `<tr><td><input type=checkbox class=map-import-tick data-admin-write data-import-name="${esc(b.bundle||b.name)}" ${on?'checked ':''}${can?'':'disabled'}></td><td><code>${esc(b.name)}</code>${where}</td><td>study ${esc(b.study)}</td><td>${b.build!=null?`build ${esc(b.build)}`:'<span class=muted>-</span>'}</td><td>${esc(String(b.built_utc||'').replace('T',' ').replace('Z',' UTC'))}</td><td>${b.bytes!=null?esc(bytesText(b.bytes)):'<span class=muted>-</span>'}</td><td>${b.part==='dex'?'<b>dex</b>: ':''}${esc(num(b.scoring||0))} scoring laws${b.laws!=null?` of ${esc(num(b.laws))}`:''}${b.regions!=null?`, ${esc(num(b.regions))} zone${+b.regions===1?'':'s'}`:''}</td><td>${same} ${seedState(b)}</td></tr>`}
  function dexLine(d){
    const w=(d&&d.dex)||{},c=w.counts||{};
    const last=w.path?`the last dex: <code>${esc(String(w.path).split('/').pop())}</code>, ${esc(String(w.utc||'').replace('T',' ').replace('Z',' UTC'))}: ${esc(num(c.laws||0))} laws, ${esc(num(c.top||0))} in its top, ${esc(num(c.verified||0))} verified here${c.differs?`, <b class=warn>${esc(num(c.differs))} differ</b>`:''}`:'no dex written yet: the first within the hour';
    return `<div class="toolbar map-dex"><span class=muted>${last}${w.folder?` · in <code>${esc(w.folder)}</code>`:''}</span><button type=button class=gsd-control data-admin-write data-map-do=dex title="write this folder's dex now: its own scoring laws, every dex and bundle ticked here, the zones, and every run again checked against the chains recorded for it">write the dex now</button></div>`}
  function verdictText(v){return v==='confirmed'?'<span class=good>confirmed</span>':v==='denied'?'<b class=warn>denied</b>':'<span class=muted>unmatched</span>'}
  function dexCheck(d){
    const c=d&&d.focus&&d.focus.dex_check;if(!c)return '';
    const n=c.counts||{}, z=c.zone, rows=c.laws||[];
    const line=z?(z.chosen?`<b>the first zone: ${lawLink(z.centre,z.campaign,z.code)}</b>${z.taken_utc?' <span class=muted>taken into focus '+esc(String(z.taken_utc).replace('T',' ').slice(0,16))+'</span>':' <span class=muted>taken at the focus’s next step</span>'}<div class=muted>${esc(z.why||'')}</div>`:`<b>no zone chosen</b><div class=muted>${esc(z.why||'')}</div>`)
      :`<b>verifying the dex first</b>: ${esc(num(rows.length))} of ${esc(num(n.held||0))} laws read again; no law is taken into focus before every law has read`;
    const tally=`${esc(num(n.confirmed||0))} confirmed, ${n.denied?`<b class=warn>${esc(num(n.denied))} denied</b>`:'0 denied'}, ${esc(num(n.unmatched||0))} unmatched${n.controls?`, ${esc(num(n.controls))} standing control${+n.controls===1?'':'s'} never chosen`:''}`;
    const groups=z&&z.groups&&z.groups.length?`<table class=map-zone-groups><thead><tr><th title="the law of its term set with the most others within the radius, then the smallest mean distance">centre</th><th title="verified laws within the radius of the centre, the centre counted">near it</th><th>of its term set</th><th>its terms</th><th title="mean distance from the centre to every verified law of its term set">mean</th></tr></thead><tbody>${z.groups.map(g=>`<tr><td>${lawLink(g.centre,z.campaign,g.code)}</td><td>${esc(num(g.near))} within ${esc(z.radius)}</td><td>${esc(num(g.laws))}</td><td class=muted>${esc((g.terms||[]).join(', '))}, ${esc(g.dynamics||'')}</td><td>${esc(Number(g.mean).toFixed(3))}</td></tr>`).join('')}</tbody></table>`:'';
    const table=rows.length?`<details class=map-dex-laws><summary>the dex’s laws as they read again (${esc(num(rows.length))})</summary><table class=map-dex-check><thead><tr><th>law</th><th title="its score in the dex">score there</th><th title="every chain run here against the chain of the same law, size, seed, start and length in the dex">read again</th><th title="chains that agree to the bit, that differ, and run to another length">chains</th><th>sizes compared</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${lawLink(r.law,c.campaign,r.code)}</td><td>${r.score!=null?esc(r.score):'<span class=muted>-</span>'}</td><td>${verdictText(r.verdict)}</td><td>${esc(num(r.agree||0))} agree${r.differ?`, <b class=warn>${esc(num(r.differ))} differ</b>`:''}${r.other_length?`, <span class=muted>${esc(num(r.other_length))} of another length</span>`:''}</td><td class=muted>${esc((r.sizes||[]).map(num).join(', ')||'-')}</td></tr>`).join('')}</tbody></table></details>`:'';
    return `<div class=map-dex-check-line>${line}<div class=muted>${tally}${c.campaign?` · the dex campaign C${esc(c.campaign)}`:''}</div></div>${groups}${table}`}
  function seeds(d){
    const f=d&&d.focus, im=(d&&d.imports)||{};
    const where=im.folder?`<div class="toolbar map-import-where"><span>the import folder:</span> <code id=mapImportFolder>${esc(im.folder)}</code><button type=button class=gsd-control data-admin-write data-map-do=open_import title="open this folder in the file manager of the machine GSD runs on">open the folder</button><button type=button class=chip data-map-copy="${esc(im.folder)}" title="copy the folder's path">copy the path</button></div>
      <div class=muted>Put a dex or a study bundle into it, its <code>.tar.zst</code> as downloaded or its unpacked folder; it is listed below within a few seconds. A dex is read in by itself within a minute; a study bundle once ticked and synchronized. Nothing in the folder is changed.</div>${dexLine(d)}`
      :`<div class=empty>${esc(im.why||'no import folder')}</div>`;
    const list=(im.bundles||[]);
    const table=list.length?`<table class=map-imports><thead><tr><th title="ticked: its laws and zones are in this study's map">in the map</th><th>bundle</th><th>study</th><th>build</th><th>built</th><th>size</th><th>its laws</th><th>science and state</th></tr></thead><tbody>${list.map(importRow).join('')}</tbody></table>
      <div class=toolbar><button type=button class=gsd-control data-admin-write data-map-do=synchronize ${f?'':'disabled'} title="read in what is newly ticked and let go of what is unticked: its laws no longer focused on or taken deeper, its zones off the map; the readings already taken are kept">synchronize</button>${f?'':'<span class=muted>a seed joins a focus: start one first</span>'}</div>
      <div class="muted map-merge-line">Every dex and bundle ticked here is merged with this folder's own laws into the dex it writes every hour.</div>`
      :(im.folder?'<div class=empty>no dex or study bundle in the import folder yet</div>':'');
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
    const typing=['mapRings','mapConfirm','mapContenders','mapOutward','mapInside','mapPerType','mapStudy'].some(id=>{const el=document.getElementById(id);return el&&document.activeElement===el});
    const box=document.getElementById('mapSettings');if(box)settingsOpen=!!box.open;
    const fold=document.getElementById('mapZoneLaws');if(fold)lawsOpen=!!fold.open;
    const at=Date.parse(String((data&&data.zone_now&&data.zone_now.at)||''));if(isFinite(at))offsetMs=Date.now()-at;
    if(!typing)put('mapControls',controls(data));
    put('mapCurrent',current(data));put('mapWorking',working(data));put('mapRegions',regions(data));put('mapDepth',depthTable(data));put('mapQueue',queue(data));put('mapFocusList',listTable(data,'focus'));put('mapDepthList',listTable(data,'depth'));put('mapDone',done(data));put('mapRunOn',runOn(data));put('mapSeed',dexCheck(data)+seeds(data));
    document.querySelectorAll('.map-import-tick').forEach(t=>{const k=t.getAttribute('data-import-name');if(k in pendingTicks)t.checked=!!pendingTicks[k]});
    wire();
    if(!ticking&&typeof setInterval==='function'){ticking=true;setInterval(tick,1000)}}
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
    if(what==='dex')return {do:'dex'};
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
    root.addEventListener('change',e=>{if(e.target&&e.target.classList&&e.target.classList.contains('map-import-tick'))pendingTicks[e.target.getAttribute('data-import-name')]=!!e.target.checked;})}
  async function refresh(force){
    if(busy&&!force)return;busy=true;
    try{data=await SYS.getJson('/api/focus')}
    catch(e){note=String((e&&e.message)||e)}
    finally{busy=false;render(data)}}
  window.GSD_MAP={refresh,render,act,bodyFor,parseRings,ringsText,lawHref,doneNote,forText,longText,whereText,tick,get data(){return data},set data(v){data=v},get note(){return note},get pendingTicks(){return pendingTicks}};
})();
