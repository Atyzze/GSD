(() => {
'use strict';
const SYS=window.GSD_SYSTEM, cfg=window.GSD_UI_CONFIG||{}, BASE=String(cfg.basePath||''), ADMIN=new URLSearchParams(location.hash.slice(1)).get('admin')||'';
const {localTime,localTimeHtml,relativeTime,LOCAL_ZONE,registerLiveRegion,deferrableRedraw,setPinned,getPinned}=window.GSD_SYSTEM;
const esc=SYS.esc,fmt=SYS.fmt,TERMS=window.GSD_TERMS||{html:()=>'',summary:()=>'',version:'unavailable'};let campaign=null,last=null,landscape=null,landscapeRevision=null,landBusy=false,hitPoints=[];let landscapeFailure=null,landPending={campaign:null,polls:0};let explorerRows=[],explorerMeta={},explorerLoaded=false,explorerSelectedTerms=new Set(),explorerSort={key:'created',dir:-1},currentPage='home';
const pageMap={home:'gsdHome',campaigns:'gsdCampaigns',explorer:'gsdExplorer',reports:'gsdReports',calibration:'gsdCalibration',system:'gsdSystem'};
const pagePath={home:'/',campaigns:'/campaigns',explorer:'/explorer',reports:'/reports',calibration:'/calibration',system:'/system'};
let REPORT_CATALOG=[];
let REPORT_BY_CODE=Object.fromEntries(REPORT_CATALOG.map(r=>[r.code,r]));
let reportCatalogLoaded=false;
async function refreshReportCatalog(){if(reportCatalogLoaded)return;try{const payload=await get('/reports/catalog.json');if(Array.isArray(payload?.reports)&&payload.reports.length){REPORT_CATALOG=payload.reports.map(r=>({code:String(r.code),number:Number(r.number),slug:String(r.slug||''),title:String(r.title||''),question:String(r.question||'')})).filter(r=>r.code&&Number.isFinite(r.number));REPORT_BY_CODE=Object.fromEntries(REPORT_CATALOG.map(r=>[r.code,r]));reportCatalogLoaded=true}}catch(_){}}

function routePath(page){try{return new URL(SYS.route(pagePath[page]||'/'),location.href).pathname}catch(_){return pagePath[page]||'/'}}

function lawCode(row,c){
  const g=String((row&&row.ensemble_code)||''),m=/^G-?(\d+)$/.exec(g);
  if(!m)return g||null;
  const camp=c??(row&&row.campaign_id!=null?row.campaign_id:campaign);
  return camp!=null&&camp!==''&&String(camp)!=='study'?`C${camp}-G${m[1]}`:`G-${m[1]}`}
function lawCodeQuery(q){const m=/^(?:b\d+-)?(?:c(\d+))?(?:-?g-?(\d+))?$/.exec(String(q||'').trim().toLowerCase());return m&&(m[1]!=null||m[2]!=null)?{campaign:m[1]??null,ordinal:m[2]!=null?+m[2]:null}:null}
function candidateLabel(row){
  const code=lawCode(row);
  return code?esc(code):esc(String(row&&row.candidate_id||'').slice(0,14));
}
function candidateTitle(row){
  return esc(String(row&&row.candidate_id||''));
}
function lawHashesHtml(row){
  const law=String(row&&row.candidate_id||''),fn=String(row&&row.function_hash||''),also=(row&&row.also_in)||[];
  if(!law)return '';
  return `<small class="law-hashes" title="law hash ${esc(law)}: the fingerprint of the normalised law, the same in every campaign that holds it${fn?`\nfunction hash ${esc(fn)}: the energy with exact redundancies folded, with the dynamics that shape a run; the same for this function written another way`:''}">law ${esc(law.slice(0,10))}${fn?` \u00b7 fn ${esc(fn.slice(0,10))}`:''}${also.length?` \u00b7 also in ${also.map(c=>'C'+esc(c)).join(', ')}`:''}</small>`}
function identityHtml(row){
  const code=lawCode(row);
  if(code)return `<code>${esc(code)}</code>`;
  if(explorerPoint(row))
    return `<span class="identity-pending" title="This law has been measured -- the score beside it comes from the landscape -- but the candidate index in this tab was loaded before that happened, so its G-code is not in it. Press refresh data.">measured \u00b7 index is behind</span>`;
  return `<span class="identity-pending" title="not run yet: a G-code is the position of a law\u2019s first graph in this campaign\u2019s simulation sequence, and no graph has been built for this law. It is law ${esc(row&&row.candidate_number!=null?row.candidate_number:'?')} of the campaign by proposal order.">not run yet</span>`;
}

function graphOrdinal(row){
  const m=/^G-(\d+)/.exec(String((row&&row.ensemble_code)||''));
  return m?+m[1]:null;
}

function candidateHref(id,camp){let c=camp??campaign;if(String(c)==='study')c=null;let raw=SYS.route('/candidate'),parts=raw.split('#'),u=parts[0]+'?candidate='+encodeURIComponent(id);if(c)u+='&campaign='+encodeURIComponent(c);return u+(parts[1]?'#'+parts[1]:'')}
function normalizePage(){const p=location.pathname;for(const page of ['campaigns','explorer','reports','calibration','system'])if(p===routePath(page))return page;return'home'}
function landingPage(page){return pageMap[page]?page:'home'}
function navigate(page,href,push=true){page=landingPage(page);if(!push&&page!=='home'&&location.pathname!==routePath(page)){try{history.replaceState?.({page},'',SYS.route(pagePath[page]))}catch(_){}}currentPage=page;window.GSD_ACTIVE_PAGE=page;Object.entries(pageMap).forEach(([k,id])=>{const e=document.getElementById(id);if(e)e.hidden=k!==page});window.GSD_SET_ACTIVE_PAGE?.(page);document.title=`${page==='home'?'Research Runtime':page[0].toUpperCase()+page.slice(1)} · Build ${cfg.buildNumber}`;if(push&&location.pathname!==routePath(page))history.pushState({page},'',href||SYS.route(pagePath[page]));window.scrollTo({top:0,behavior:'instant'});if(page==='explorer'&&!explorerLoaded)loadExplorer();if(page==='reports')refreshReports(true);if(page==='calibration')refreshCalibration(true);if(page==='campaigns')refreshCampaigns(true);if(page==='system'&&last)renderSystem(last)}
let reportTick=0,reportStatus={},reportBusy=false,reportAdmin=false,reportTriggerError=null,bundleBusy=false,quietAskedAt=0;
const QUIET_ASK_WAIT_MS=120000;
let calibBusy=false,calibData=null,calibRefreshTimer=null;
let studyBundles=null,studyDeleteNote='';
const QUIET_STAGES=['pausing','draining','reporting','maintaining','resuming','bundling'];
const QUIET_HOLDING=['pausing','draining','reporting','maintaining'];
let gateData=null,gateBusy=false;
let campaignsData=null,campaignsBusy=false,campaignSelected=null,campaignPanelData=null;
let campaignsFailedSince=null,campaignsRetryTimer=null,campaignsRetryTicks=1;
let campaignsPausing=new Set(),campaignsSavedAt={};
let authorParent=null,authorTerms=new Set(),authorCheck=null,authorBusy=false,campaignActionError=null,authorRequestId=null;
const newRequestId=()=>(window.crypto&&crypto.randomUUID)?crypto.randomUUID():(Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,12));
let campaignFenceNext=false,authorTakesFleet=true,authorGrid={},fleetBusy=false;
let authorReasonText='';
let authorWindow=null;
let authorReadOnly=false;
window.GSD_NAVIGATE=(page,href)=>navigate(page,href,true);window.addEventListener('popstate',()=>navigate(normalizePage(),location.href,false));navigate(normalizePage(),location.href,false);
async function get(p){return SYS.getJson(p)}
function stableJitter(id,salt){let h=2166136261;for(const ch of String(id||'')+salt){h^=ch.charCodeAt(0);h=Math.imul(h,16777619)}return ((h>>>0)/4294967295-.5)*10}
const SCORE_WHO={empty:'the chain from empty',random:'the random start',lattice:'a lattice start, changed',kept:'a lattice start, kept',frozen:'a lattice start, frozen: no edge changed',still:'a lattice start, still: its own degree, few moves'};
const SCORE_FROM=16384;
function lawScoreOf(x){const s=x&&x.law_score;return (s&&typeof s.score==='number')?s:null}
function lawScoreBelow(x){const s=lawScoreOf(x);return !!(s&&s.top_n!=null&&+s.top_n<SCORE_FROM)}
function lawScoreText(x){const s=lawScoreOf(x);if(!s)return 'not scored yet';if(!(s.score>0))return lawScoreBelow(x)?'not yet at N=16,384':'no probe settles on any start';const lattice=latticeWho().has(s.by);return `${SCORE_WHO[s.by]||s.by}${lattice&&s.chain?' ('+s.chain+')':''}: ${s.points!=null?s.points:'?'} of ${s.points_of||15} at N=${Number(s.to_n).toLocaleString('en-US')}${s.einstein?', all four agreeing by Einstein':''}${s.d!=null?`; d ${s.d}${s.d<1.5?' (a ring)':''}`:''}`}
function scoreTitle(row){const s=lawScoreOf(row);const head=!s?'Not scored yet: the controller reads every decided law a page at a time.':s.score>0?`Score ${s.score} of 100: ${lawScoreText(row)}.`:lawScoreBelow(row)?'Score 0: not yet measured at N=16,384, the first size a probe can settle at (readings are relied on from 4,096).':'Score 0: no probe of any start settled from one size to the next from N=4,096.';return `${head}\nPoints times depth times who (784): only readings from N=4,096 on a piece of 4,096 nodes or more count. Each probe, and the Einstein relation d_s = 2 d_f / d_w as a fifth item, earns 1 when it reads at two sizes in a row, 2 when it settles between them (within the margin the calibration table\u2019s exact lattices set), 3 when it settles again at the next size: 15 at most. Each size from N=1,024 to 4,194,304 is a seventh of depth; the twin starts count 1, a lattice start that changed 0.6, one that kept its shape 0.3. Shown and ranked by; it orders the deep lane and decides nothing else.`}
function topClass(x){const s=lawScoreOf(x);if(s&&s.score>0)return'stable';const st=String(x.state||'');if(st.startsWith('REJECTED_'))return'unstable';return'provisional'}


function etaProgressHtml(job){
  const eta=job.eta, elapsed=job.since_s;
  const ran = elapsed!=null ? `, ${durationText(elapsed)} elapsed` : '';
  if(!eta) return ran;
  const p=eta.progress||{};
  if(p.overdue)
    return `${ran} · <span class="eta-overdue" title="${esc(eta.reason||'past the upper quartile of comparable attempts')}">`
      +`overdue by ${durationText(p.overdue_by_seconds)}</span>`;
  if(p.remaining_seconds!=null)
    return `${ran} · <span class="eta-live" title="median ${durationText(eta.median_seconds)} over `
      +`${eta.attempts} attempt(s) at this rung, ${eta.censored} of them stopped at the time ceiling">`
      +`~${durationText(p.remaining_seconds)} remaining</span>`;
  return `${ran} · <span class="eta-unknown" title="${esc(eta.reason||'insufficient history')}">no reliable estimate</span>`;
}
function deepestRunHtml(job, row){
  if(!job) return '';
  const stage=String(job.stage||'');
  const mult=(stage.match(/_x(\d+)/)||[])[1];
  const up=stage.toUpperCase();
  const kind=up.startsWith('EXT')?'extension rung'
            :up.startsWith('BASE')?'base rung'
            :'rung';
  const eta=job.eta||{}, p=eta.progress||{};
  const elapsed=job.since_s!=null?+job.since_s:null;
  const remaining=p.remaining_seconds!=null?+p.remaining_seconds:null;
  let frac=null;
  if(elapsed!=null&&remaining!=null&&elapsed+remaining>0) frac=Math.max(0,Math.min(1,elapsed/(elapsed+remaining)));
  else if(p.overdue) frac=1;
  const barClass=p.overdue?'overdue':(frac==null?'unknown':'live');
  const bar=`<span class="run-bar ${barClass}" title="${esc(p.overdue?(eta.reason||'past the upper quartile of comparable attempts'):(eta.reason||''))}">`
    +`<span class="run-bar-fill" style="width:${Math.round((frac==null?0:frac)*100)}%"></span></span>`;
  const facts=[
    `N=${esc(+job.n)}`,
    job.seed!=null?`seed ${esc(job.seed)}`:'sealed',
    (kind==='rung'
      ? `<span title="the job's stage (${esc(stage||'unset')}) does not say whether this is a base or an extension rung">rung</span>`
      : kind)+(mult?` \u00b7 ${esc(mult)}x sweeps`:''),
    elapsed!=null?`${durationText(elapsed)} elapsed`:'',
    remaining!=null?`~${durationText(remaining)} left`:(p.overdue?`overdue by ${durationText(p.overdue_by_seconds)}`:'no estimate'),
    eta.median_seconds!=null?`median ${durationText(eta.median_seconds)} over ${esc(eta.attempts)} attempt(s)${eta.censored?`, ${esc(eta.censored)} censored`:''}`:'',
  ].filter(Boolean);
  return `<span class="deepest-run"><span class="deepest-run-head">deepest live work \u00b7 <span class=candidate-link>${esc(candidateLabel(row))}</span></span>`
    +bar+`<span class="deepest-run-facts">${facts.map(f=>`<span>${f}</span>`).join('')}</span></span>`;
}
function rungLadderRow(){
  const root=document.getElementById('rungLadder');
  if(!root)return;
  registerLiveRegion(root);
  if(deferrableRedraw(root,()=>rungLadderRow()))return;
  const rows=(last&&last.rung_distribution)||[];
  if(!rows.length){root.innerHTML='<div class=empty>no rung has been declared or measured yet</div>';return}
  const depths=filteredDepths(),kept=depths?`<div class=muted id=ladderFiltered title="the fleet's live counts below are every law's: running, queued and analysing work is not tied to a law's kind until it is read">the laws the filters keep, by their deepest size: ${Object.keys(depths).length?Object.entries(depths).sort((a,b)=>a[0]-b[0]).map(([n,c])=>`N=${(+n).toLocaleString()} ${c}`).join(' \u00b7 '):'none'}</div>`:'';
  const live=rows.reduce((t,r)=>t+(+r.running||0),0);
  const queued=rows.reduce((t,r)=>t+(+r.queued||0),0);
  const sum=k=>rows.reduce((a,r)=>a+(+r[k]||0),0);
  const maxEvolve=Math.max(1,...rows.map(r=>+r.running||0));
  const maxProbe=Math.max(1,...rows.map(r=>+r.analysing||0));
  const bar=(v,max,cls)=>`<span class="run-bar ${v?cls:'unknown'}" style="width:${Math.round(100*(+v||0)/max)}%">`
    +`<span class="run-bar-fill" style="width:100%"></span></span>`;
  const count=v=>(+v||0)?`<b>${esc(+v)}</b>`:'<span class=muted>0</span>';
  const plain=v=>(+v||0)?esc(+v):'<span class=muted>0</span>';
  const em='<span class=muted>\u2014</span>';
  const secs=v=>v==null?em:esc(ladderDuration(+v));
  const bytesShort=v=>{
    const n=Number(v);
    if(!isFinite(n)||n<=0) return null;
    const u=['B','KiB','MiB','GiB','TiB']; let i=0,x=n;
    while(x>=1024&&i<u.length-1){x/=1024;i++}
    return {n:(x<10?x.toFixed(1):String(Math.round(x))),u:u[i]};
  };
  const memBand=r=>{
    const raw=[r.peak_bytes_min, r.peak_bytes_median, r.peak_bytes_p95, r.peak_bytes_max]
      .map(v=>{const n=Number(v); return (isFinite(n)&&n>0)?n:null;});
    if(raw[1]===null) return em;
    const each=raw.map(v=>v===null?null:bytesShort(v)), units=new Set(each.filter(Boolean).map(b=>b.u));
    if(units.size===1) return esc(each.map(b=>b===null?'\u2013':b.n).join('/')+' '+[...units][0].charAt(0));
    return esc(each.map(b=>b===null?'\u2013':b.n+b.u.charAt(0)).join('/'));
  };
  const bandSecs=v=>{
    if(v==null||v==='') return null;
    const n=Number(v);
    return (!isFinite(n)||n<0) ? null : ladderBandDuration(n);
  };
  const probeSecs=v=>{
    if(v==null||v==='') return null;
    const n=Number(v);
    if(!isFinite(n)||n<0) return null;
    return n<1?`${n>0?Math.max(1,Math.round(1000*n)):0}ms`:ladderBandDuration(n);
  };
  const probeTime=(r,p)=>{
    const own=r[`${p}_ran_median_seconds`];
    return (+r[`${p}_ran`]||0)>0&&own!=null?own:r[`${p}_median_seconds`];
  };
  const ranShare=(ran,timed)=>{
    const p=Math.round(100*ran/timed);
    return p<1?'<1%':(p>99?'>99%':`${p}%`);
  };
  const movesMedian=(r,p)=>{
    const all=Number(r[`${p}_median_seconds`]), own=Number(r[`${p}_ran_median_seconds`]);
    return !isFinite(all)||!isFinite(own)||Math.abs(own-all)>0.05*own;
  };
  const probeMedian=(r,p)=>{
    const ran=+r[`${p}_ran`]||0, timed=+r[`${p}_timed`]||0;
    if(timed>0&&ran===0) return `${em}<small class=ladder-share>0%</small>`;
    const v=probeSecs(probeTime(r,p));
    if(v===null) return em;
    return esc(v)+(ran>0&&timed>ran&&movesMedian(r,p)?`<small class=ladder-share>${esc(ranShare(ran,timed))}</small>`:'');
  };
  const FOUR_PROBES=['d_s','d_V','d_B','d_w'];
  const fourProbeSum=r=>{
    const parts=FOUR_PROBES.filter(p=>!((+r[`${p}_timed`]||0)>0&&!(+r[`${p}_ran`]||0)))
      .map(p=>probeTime(r,p)).filter(v=>v!=null&&v!==''&&isFinite(Number(v)));
    return parts.length?parts.reduce((a,v)=>a+Number(v),0):null;
  };
  const fourProbeCell=r=>{
    const s=fourProbeSum(r);
    return s===null?em:esc(probeSecs(s));
  };
  const windowText=v=>{
    const n=Number(v);
    if(v==null||v===''||!isFinite(n)||n<=0) return null;
    if(n<60) return `${Math.round(n)}s`;
    if(n<3600) return n%60?ladderBandDuration(n):`${Math.round(n/60)}m`;
    return n%3600?ladderBandDuration(n):`${Math.round(n/3600)}h`;
  };
  const budgetCell=r=>{
    const u=unitsText(r.work_budget);
    if(u===null) return em;
    return esc(u);
  };
  const lawsCell=(r,laws,strong)=>strong?count(r[laws]):plain(r[laws]);
  const timeBand=r=>{
    const cells=[r.min_seconds, r.median_seconds, r.p95_seconds, r.max_seconds].map(bandSecs);
    if(cells[1]===null&&cells[3]===null) return em;
    return esc(cells.map(v=>v===null?'\u2013':v).join('/')+(r.max_unfinished&&cells[3]!==null?'+':''));
  };
  const ratioShort=v=>{
    const n=Number(v);
    if(!isFinite(n)||n<=0) return em;
    return (n>=1.5?`<b>${esc(n.toFixed(2))}x</b>`:esc(n.toFixed(2)+'x'));
  };
  const pct=v=>{
    const n=Number(v);
    if(!isFinite(n)||n<0) return em;
    const q=100*n, text=q<1?'<1%':`${q.toFixed(q<10?1:0)}%`;
    return q>=20?`<b>${esc(text)}</b>`:esc(text);
  };
  const campaignTotal=sum('rung_seconds_total');
  const campaignWhole=campaignTotal+sum('running_seconds');
  const rungWhole=r=>(Number(r.rung_seconds_total)||0)+(Number(r.running_seconds)||0);
  const share1=(part,whole)=>{
    const p=Number(part), w=Number(whole);
    if(!isFinite(p)||!isFinite(w)||w<=0||p<0) return '';
    return `<small class=ladder-share>${esc((100*p/w).toFixed(1))}%</small>`;
  };
  const footSeconds=key=>{
    const s=sum(key);
    return `<b>${secs(s)}</b>`+share1(s,campaignWhole);
  };
  const probeCell=r=>{
    const p=Number(r.probe_seconds_total);
    if(!isFinite(p)||p<=0) return em;
    return esc(ladderDuration(p))+share1(p,rungWhole(r));
  };
  const evolveCell=r=>{
    const run=Number(r.running_seconds)||0, p=(Number(r.simulation_seconds_total)||0)+run;
    if(p<=0) return em;
    return esc(ladderDuration(p))+share1(p,rungWhole(r));
  };

  const COLS=[
    {g:'cand', head:'rung', title:'The graph size N, in nodes; every law starts at the smallest and climbs while the engine keeps it.',
     cell:r=>`<code>N=${esc(+r.n)}</code>`, foot:()=>'<b>all</b>'},
    {g:'cand', head:'laws', title:'Laws with a graph at this N. Read down the column: laws fall away as rules stop them.',
     cell:r=>{const n=+(r.laws!=null?r.laws:r.measured)||0;return n?esc(n):em;}, foot:()=>''},
    {g:'cand', head:'graphs', title:'Graphs grown at this N: every seed of every law here, each seed growing one graph from each start.',
     cell:r=>{const g=+r.graphs||0,k=+r.chains_per_seed||1,c=+r.chains||g*k;return g?esc(c):em;},
     foot:()=>`<b>${esc(sum('chains')||sum('graphs'))}</b>`},
    ...stopRuleColumns(rows, em),
    {g:'evolve', head:'running', w:56, title:'Laws with a seed being evolved at this N right now, one worker a seed; a law here is up to 3 seeds, 24 graphs.',
     cell:r=>lawsCell(r,'running_laws',true)+bar(r.running,maxEvolve,'live'), foot:()=>`<b>${esc(sum('running_laws'))}</b>`},
    {g:'evolve', head:'queue', title:'Laws with a seed waiting for a worker at this N.',
     cell:r=>lawsCell(r,'queued_laws',false), foot:()=>`<b>${esc(sum('queued_laws'))}</b>`},
    {g:'evolve', head:'time per seed', nowrap:true, title:'Wall time of one seed at this N (one law, one random seed, all its graphs): fastest, median, slowest 5% and slowest; + not finished, stopped runs counted.',
     cell:timeBand, foot:()=>em},
    {g:'evolve', head:'budget', nowrap:true, title:'A seed\u2019s budget in units of work, the engines\u2019 weighted count of their steps, the same on any machine; G 10^9, T 10^12.',
     cell:budgetCell, foot:()=>em},
    {g:'evolve', head:'cut', title:'Laws with a seed that ran out of its work budget before it settled. The cut gate records it and the law goes on, unless a design lets the gate stop it.',
     cell:r=>{const n=+r.budget_ended_laws||0;return n?lawsCell(r,'budget_ended_laws',false):((+r.graphs||0)?'<span class=muted>0</span>':em);},
     foot:()=>`<b>${esc(sum('budget_ended_laws'))}</b>`},
    {g:'evolve', head:'memory', nowrap:true, title:'Peak memory of one seed at this N, as seeds vary: the lightest, the median, the heaviest 5% and the heaviest.',
     cell:memBand, foot:()=>em},
    {g:'evolve', head:'ratio', nowrap:true, title:'Memory reserved for the median run over what it actually used: above 1x, admission held back more than the run needed.',
     cell:r=>ratioShort(r.reserved_over_observed), foot:()=>em},
    {g:'evolve', head:'etime', title:'All time spent evolving at this N, summed over every run, and its share of this rung\u2019s total time.',
     cell:evolveCell, foot:()=>{const run=sum('running_seconds'), s=sum('simulation_seconds_total')+run;
       return `<b>${secs(s)}</b>`+share1(s,campaignWhole);}},
    {g:'probe', head:'running', w:56, title:'Laws with a seed being probed at this N right now, on the same workers as evolving.',
     cell:r=>lawsCell(r,'analysing_laws',true)+bar(r.analysing,maxProbe,'probe'), foot:()=>`<b>${esc(sum('analysing_laws'))}</b>`},
    {g:'probe', head:'queue', title:'Laws with an evolved seed waiting for a probe at this N.',
     cell:r=>lawsCell(r,'queued_analyses_laws',false), foot:()=>`<b>${esc(sum('queued_analyses_laws'))}</b>`},
    {g:'probe', head:'d_s', title:'Median time of the spectral-dimension probe for one seed at this N, over the seeds it ran on; under it their share, where that moves the median.',
     cell:r=>probeMedian(r,'d_s'), foot:()=>footSeconds('d_s_seconds_total')},
    {g:'probe', head:'d_V', title:'Median time of the volume-growth probe for one seed at this N, over the seeds it ran on; under it their share, where that moves the median.',
     cell:r=>probeMedian(r,'d_V'), foot:()=>footSeconds('d_V_seconds_total')},
    {g:'probe', head:'d_B', title:'Median time of the box-covering probe for one seed at this N, over the seeds it ran on; under it their share, where that moves the median.',
     cell:r=>probeMedian(r,'d_B'), foot:()=>footSeconds('d_B_seconds_total')},
    {g:'probe', head:'d_w', title:'Median time of the random-walk probe for one seed at this N, over the seeds it ran on; under it their share, where that moves the median.',
     cell:r=>probeMedian(r,'d_w'), foot:()=>footSeconds('d_w_seconds_total')},
    {g:'probe', head:'curv', title:'Median time of the curvature probe for one seed at this N, from a sample of the seeds.',
     cell:r=>probeMedian(r,'kappa'), foot:()=>footSeconds('kappa_seconds_total')},
    {g:'probe', head:'sum', title:'The four dimension probes\u2019 medians added up, the curvature left out: roughly what probing one seed costs at this N when all four run.',
     cell:fourProbeCell, foot:()=>{const s=FOUR_PROBES.reduce((a,p)=>a+sum(`${p}_seconds_total`),0);return `<b>${secs(s)}</b>`+share1(s,campaignWhole);}},
    {g:'probe', head:'ptime', title:'All time spent probing at this N, the five probes summed over every seed, and its share of this rung\u2019s total time.',
     cell:probeCell, foot:()=>footSeconds('probe_seconds_total')},
    {g:'total', head:'total', title:'All time spent at this N, evolving plus probing, and this rung\u2019s share of the campaign\u2019s total.',
     cell:r=>{const t=rungWhole(r), p=pct(campaignWhole>0?t/campaignWhole:null);
       return t>0?secs(t)+(p===em?'':`<small class=ladder-share>${p}</small>`):em},
     foot:()=>`<b>${secs(sum('rung_seconds_total')+sum('running_seconds'))}</b>`+(sum('rung_seconds_total')>0?'<small class=ladder-share><b>100%</b></small>':'')},
  ];
  const attrs=c=>{
    const parts=[];
    if(!c.bar) parts.push('num');
    if(c.g) parts.push('g-'+c.g);
    if(c.nowrap) parts.push('nowrap');
    return parts.length?` class="${parts.join(' ')}"`:'';
  };
  const cells=rows.map(r=>COLS.map(c=>c.cell(r))), feet=COLS.map(c=>c.foot(rows));
  const fit=(c,i)=>Math.max(+c.w||0, Math.ceil(Math.max(String(c.head||'').length, textChars(feet[i]),
    ...cells.map(row=>textChars(row[i])))*LADDER_HEAD_CHAR_PX)+LADDER_HEAD_PAD_PX);
  const widths=COLS.map(fit);
  const colgroup='<colgroup>'+widths.map(w=>`<col style="width:${w}px">`).join('')+'</colgroup>';
  const perLaw=rows.find(r=>+r.chains_per_seed>0)||{}, seedsPer=+perLaw.seeds_per_law||0, graphsPer=+perLaw.chains_per_seed||0;
  const seedWords=seedsPer&&graphsPer?` \u00b7 a law at a size = ${seedsPer} seed${seedsPer===1?'':'s'} \u00d7 ${graphsPer} start${graphsPer===1?'':'s'} = ${seedsPer*graphsPer} graphs`:'';
  const GROUPS={cand:'candidates', stop:'laws stopped by rule', evolve:'evolving laws'+seedWords, probe:'probing laws'+seedWords, total:'totals'};
  let groupRow='<tr class=ladder-groups>', i=0;
  while(i<COLS.length){
    const g=COLS[i].g||null; let span=0;
    while(i+span<COLS.length&&(COLS[i+span].g||null)===g) span++;
    groupRow+=g?`<th class="g-${g}" colspan=${span}>${esc(GROUPS[g])}</th>`
               :`<th colspan=${span}></th>`;
    i+=span;
  }
  groupRow+='</tr>';
  const headRow='<tr>'+COLS.map(c=>
    `<th${attrs(c)}${c.title?` title="${esc(c.title)}"`:''}>${esc(c.head)}</th>`).join('')+'</tr>';
  const body=cells.map(row=>'<tr>'+COLS.map((c,i)=>`<td${attrs(c)}>${row[i]}</td>`).join('')+'</tr>').join('');
  const foot=`<tr class=ladder-total>`+COLS.map((c,i)=>`<td${attrs(c)}>${feet[i]}</td>`).join('')+'</tr>';

  const util=(last&&last.compute_utilization)||{};
  const analysis=Number(util.analysis_busy||0);
  const backlog=Number((last&&last.analysis_backlog)||0);
  const stalled=queued&&!live
    ? '<div class=muted><b>nothing is running</b>: every queued chain is waiting on an admission</div>'
    : (!queued&&!live&&(analysis||backlog)
       ? '<div class=muted><b>no chain is evolving</b>: the fleet is working the analysis backlog</div>'
       : '');
  root.innerHTML=kept+stalled
    +`<table class="explorer-table ladder-table">${colgroup}<thead>${groupRow}${headRow}</thead>`
    +`<tbody>${body}</tbody><tfoot>${foot}</tfoot></table>`;
}

const REGIME_LABEL={equilibrium:'equilibrium',zero_temperature:'zero temperature'};
function regimeChip(regime){
  if(!regime||regime==='equilibrium')return '';
  return ` <span class="regime-chip regime-${esc(regime)}" title="${regime==='zero_temperature'?'accepts only moves that do not raise the energy, so it can come to rest where its start led it':''}">${esc(REGIME_LABEL[regime]||regime)}</span>`;}
function shownLandscape(){return landscape&&String(landscape.campaign_id)===String(campaign)?landscape:null}
function leaderRow(){
  const rows=shownLandscape()?.top_candidates||[];
  const root=document.getElementById('leader');
  if(!root) return;
  if(!rows.length){root.innerHTML='<div class=empty>no scored candidate yet</div>';return}
  const best=rows[0];
  const found=lawScoreOf(best);
  const score=found?found.score:0;
  if(score<=0){
    root.innerHTML='<div class=empty>no law has scored above zero yet'
      +`<span class=muted> \u00b7 ${esc(rows.length)} law(s) measured; a law scores once one of its starts is a geometry `
      +`at N=1,024 or more${found?'':' (the first is not scored yet)'}</span></div>`;
    return}
  const tied=rows.filter(x=>lawScoreOf(x)?.score===score).length;
  const active=(last?.active||[]).filter(x=>String(x.state||'')!=='PROPOSED');
  const forBest=active.find(x=>String(x.candidate_id)===String(best.candidate_id));
  const deepest=active.reduce((acc,x)=>{
    const running=(x.running||[]).map(r=>+r.n);
    const top=running.length?Math.max(...running):null;
    return (top!=null&&(!acc||top>acc.n))?{n:top,row:x}:acc;
  },null);
  const deepestJob = job => (job.running||[]).slice().sort((a,b)=>(+b.n)-(+a.n))[0];
  const own = forBest&&(forBest.running||[]).length ? deepestJob(forBest) : null;
  const other = deepest ? deepestJob(deepest.row) : null;
  const job = own || other;
  const progress = job ? etaProgressHtml(job) : '';
  const engineNote = (own||!best.engine_decision) ? ''
    : `<span class="leader-work idle" title="the decision engine's latest decision for this law">engine: ${esc(engineDecisionText(best.engine_decision))}</span>`;
  const workLine = (own
    ?
      `<span class="leader-work live">${own.lane==='extension'?'running a rung above its base block at':own.lane==='base'?'running its base block at':'running at'} N=${esc(+own.n)}${progress}</span>`
    : other
      ?
        `<span class="leader-work idle" title="Nothing is queued or leased for this law right now. `
        +`The deepest rung running anywhere in the campaign is shown below for context; it is on `
        +`a different law.">nothing is running for this law${best.state?` \u00b7 ${esc(best.state)}`:''}</span>`
        +`<span class="leader-work">deepest live work in the campaign is N=${esc(+other.n)} on <span class=candidate-link>${esc(candidateLabel(deepest.row))}</span><span class=muted> (a different law)</span>${progress}</span>`
      : `<span class="leader-work idle">no rung is running right now${best.state?` \u00b7 this law is ${esc(best.state)}`:''}</span>`)+engineNote;
  const tieNote = tied>1 ? `<span class="leader-tie">${tied} laws tie at ${esc(score)}</span>` : '';
  root.innerHTML=`<a class="leader-card" href="${candidateHref(best.candidate_id,best.campaign_id)}" title="${esc(scoreTitle(best))}">`
    +`<span class=leader-score>${esc(score)}</span>`
    +`<span class=leader-body>`
      +`<span class=candidate-link>${esc(candidateLabel(best))}</span>`
      +`<span class=score-meta> \u00b7 ${esc(best.state||'measured')} \u00b7 ${esc(lawScoreText(best))}</span>`
      +(best.terms?.length?TERMS.html(best.terms,{compact:true}):'')
      +`<span class=leader-lines>${workLine}${tieNote}</span>`
      +deepestRunHtml(job, own?forBest:(deepest&&deepest.row))
    +`</span></a>`;
}
function engineDecisionText(d){
  if(!d) return 'no decision yet';
  if(d.action==='run_next') return `next N=${d.next_n}`+(d.priority?` \u00b7 priority ${d.priority}`:'')+` \u00b7 ${d.rule}`;
  if(d.action==='hold') return `held at N=${d.at_n} \u00b7 ${d.rule}`;
  if(d.action==='stop') return `stopped at N=${d.at_n} \u00b7 ${d.rule}`;
  return `done at N=${d.at_n}`;
}
function topDepthText(x){
  const id=String(x.candidate_id), top=Number(x.stability_top_rung)||null, parts=[];
  if(top) parts.push(`measured to N=${top}`);
  const act=((last&&last.active)||[]).find(a=>String(a.candidate_id)===id);
  const deeper=act?(act.running||[]).map(r=>+r.n).filter(n=>!top||n>top):[];
  if(deeper.length) parts.push(`N=${Math.max(...deeper)} running`);
  parts.push(engineDecisionText(x.engine_decision));
  return ' \u00b7 '+esc(parts.join(' \u00b7 '));
}
const ENGINE_CLASS_HEAD={priority_1:'bought first \u00b7 d_s settled',running:'running',held:'held',undecided:'no decision yet',finished:'stopped or done'};
function renderTop(){const root=document.getElementById('best');if(root){registerLiveRegion(root);if(deferrableRedraw(root,()=>renderTop()))return}const rows=filteredTop();if(!rows.length){root.innerHTML=homeFilterActive()?'<div class=empty>no law in the landscape passes these filters</div>':'<div class=empty>no law read yet</div>';return}root.innerHTML=rows.map((x,i)=>{const found=lawScoreOf(x);
  const scoreCell=found?esc(found.score):'<span class=muted title="not scored yet: the controller reads every decided law a page at a time">\u2026</span>';
  return `<a class="top-candidate ${topClass(x)}" href="${candidateHref(x.candidate_id,x.campaign_id)}" title="${esc(scoreTitle(x))}"><span class=top-rank>${i+1}</span><span><span class=candidate-link title="${candidateTitle(x)}">${candidateLabel(x)}</span>${regimeChip(x.regime)}<span class=score-meta> · ${esc(lawScoreText(x))}${topDepthText(x)}${x.mean_degree!=null?' · \u27e8d\u27e9 '+(+x.mean_degree).toFixed(2):''}${(x.limit_hits||[]).length?' · limit@'+x.limit_hits.join(','):''}</span>${x.terms?.length?TERMS.html(x.terms,{compact:true}):(x.law?`<span class=score-meta style="display:block">${esc(x.law)}</span>`:'')}</span><span class=score>${scoreCell}</span></a>`}).join('')}
function reportQuietHtml(s){
  const q=s.quiet_report||{},f=s.in_flight||{},active=QUIET_STAGES.includes(q.stage),n=(q.campaigns||[]).length;
  const parts=[];
  const sp=q.study_progress||null,lay=q.study_layout||{};
  if(active&&q.stage==='reporting'&&sp)parts.push(`study bundle: <b>reporting</b>${lay.at_once?` · ${esc(lay.at_once)} campaign${lay.at_once===1?'':'s'} at a time`:''} · each campaign's progress is the first row of the table below`);
  else if(active)parts.push(`study bundle: <b>${esc(q.stage)}</b>`+(q.stage==='reporting'&&n?` · campaign <b>${esc(q.campaign_id)}</b> (${(+q.index||0)+1} of ${n})`:(q.campaign_id&&!n?` · campaign <b>${esc(q.campaign_id)}</b>`:''))+(q.stage==='draining'&&q.in_flight?` · ${esc(q.in_flight.reading||'')}`:''));
  else if(q.stage==='done'){const b=q.study_bundle,k=b?(b.campaigns||[]).length:0;parts.push(`last study bundle: `+(b?`<b>${esc(b.filename)}</b>, ${k} campaign${k===1?'':'s'}`+((b.missing||[]).length?` · <span class=warn>${(b.missing||[]).length} missing</span>`:''):esc(q.outcome||'finished'))+(q.error?` · <span class=warn>${esc(q.error)}</span>`:'')+` · resumed ${esc((q.resumed||[]).join(', ')||'nothing')}`)}
  if(!active&&f.total)parts.push(`${esc(f.reading)}; the study bundle pauses them first and resumes them after`);
  if(active&&QUIET_HOLDING.includes(q.stage)&&reportAdmin)parts.push(`<button id=reportQuietCancel title="Stop the study bundle and resume exactly the campaigns it paused; no bundle is made">cancel the study bundle</button>`+(q.runner_error?` · <span class=warn>${esc(q.runner_error)}</span>`:''));
  return parts.map(x=>`<div>${x}</div>`).join('');
}
function unitsText(units){
  const u=Number(units);
  if(units==null||units===''||!isFinite(u)||u<=0) return null;
  for(const [scale,prefix] of [[1e15,'P'],[1e12,'T'],[1e9,'G'],[1e6,'M'],[1e3,'k']])
    if(u>=scale) return `${Number((u/scale).toPrecision(3))} ${prefix}`;
  return `${Math.round(u)}`;
}
function budgetText(seconds){const s=Math.max(0,Math.round(Number(seconds)||0)),h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=s%60;return [h?`${h}h`:'',m?`${m}m`:'',r||(!h&&!m)?`${r}s`:''].join('')}
const STOP_RULES=[['empty','empty','Laws stopped here because their mean degree stayed at the empty threshold.'],
  ['too_dense','dense','Laws stopped here because their mean degree reached the cap.'],
  ['disconnected','discon','Laws stopped here because their largest component fell under the connectivity floor.']];
const STRUCTURE_STOPS=['no_finite_dimension','no_giant_component'];
const BUDGET_STOPS=['over_budget','cut'];
function ladderDuration(seconds){
  const s=Math.max(0,Number(seconds)||0);
  if(s<60) return `${s.toFixed(1)}s`;
  if(s<3600){const m=Math.floor(s/60), r=Math.round(s-60*m); return r===60?`${m+1}m00s`:`${m}m${String(r).padStart(2,'0')}s`;}
  const h=Math.floor(s/3600), m=Math.round((s-3600*h)/60);
  return m===60?`${h+1}h00m`:`${h}h${String(m).padStart(2,'0')}m`;
}
function ladderBandDuration(seconds){
  const s=Math.max(0,Number(seconds)||0);
  if(s<10) return `${s.toFixed(1)}s`;
  if(s<60) return `${Math.round(s)}s`;
  if(s<600){const m=Math.floor(s/60), r=Math.round(s-60*m); return r===60?`${m+1}m00s`:`${m}m${String(r).padStart(2,'0')}s`;}
  if(s<3600) return `${Math.round(s/60)}m`;
  if(s<36000){const h=Math.floor(s/3600), m=Math.round((s-3600*h)/60); return m===60?`${h+1}h00m`:`${h}h${String(m).padStart(2,'0')}m`;}
  return `${Math.round(s/3600)}h`;
}
function textChars(html){
  return String(html==null?'':html).split(/<small|<span class="run-bar/)[0].replace(/<[^>]*>/g,'')
    .replace(/&[a-z0-9#]+;/gi,'x').length;
}
const LADDER_HEAD_CHAR_PX=7, LADDER_HEAD_PAD_PX=13;
function stopRuleColumns(rows,em){
  const rules=STOP_RULES.slice();
  const total=rule=>rows.reduce((a,r)=>a+(+((r.stopped_by_rule||{})[rule])||0),0);
  const columns=rules.map(([rule,head,title])=>({g:'stop', head, title,
    cell:r=>{const n=+((r.stopped_by_rule||{})[rule])||0;return n?esc(n):((+r.graphs||0)?'<span class=muted>0</span>':em);},
    foot:()=>`<b>${esc(total(rule))}</b>`}));
  if(!rows.some(r=>r.left!=null))return columns;
  const none=r=>(+r.graphs||0)?'<span class=muted>0</span>':em;
  const parkedOf=r=>Object.values(r.parked_by_rule||{}).reduce((a,v)=>a+(+v||0),0)
    +STRUCTURE_STOPS.reduce((a,rule)=>a+Math.max(0,(+((r.stopped_by_rule||{})[rule])||0)-(+((r.parked_by_rule||{})[rule])||0)),0);
  const stoppedOf=r=>r.stopped!=null?(+r.stopped||0):Math.max(0,(+r.left||0)-(+r.done||0));
  const byRule=(r,rule)=>+((r.parked_by_rule||{})[rule])||+((r.stopped_by_rule||{})[rule])||0;
  const cutOf=r=>byRule(r,'cut'), pricedOf=r=>byRule(r,'over_budget');
  const gatedOf=r=>Math.max(0,parkedOf(r)-BUDGET_STOPS.reduce((a,rule)=>a+(+((r.parked_by_rule||{})[rule])||0),0));
  const sumOf=key=>rows.reduce((a,r)=>a+(key==='gated'?gatedOf(r):key==='cut'?cutOf(r):key==='priced'?pricedOf(r):stoppedOf(r)),0);
  columns.push({g:'stop', head:'gated', title:'Laws parked here by a gate that reads the probes or the starts, or stopped by the structure gate; a park stops a law too.',
    cell:r=>{const n=gatedOf(r);return n?esc(n):none(r);}, foot:()=>`<b>${esc(sumOf('gated'))}</b>`});
  if(rows.some(r=>cutOf(r)>0)) columns.push({g:'stop', head:'stopped cut', title:'Laws stopped here by the cut gate, where a design lets it stop a law: a seed ran out of its work budget before it settled.',
    cell:r=>{const n=cutOf(r);return n?esc(n):none(r);}, foot:()=>`<b>${esc(sumOf('cut'))}</b>`});
  columns.push({g:'stop', head:'priced', title:'Laws stopped over_budget here, before a run: the next one, a larger size or a longer chain, is priced above its budget from the law\u2019s own seeds.',
    cell:r=>{const n=pricedOf(r);return n?esc(n):none(r);}, foot:()=>`<b>${esc(sumOf('priced'))}</b>`});
  columns.push({g:'stop', head:'total', title:'Every law stopped here, by any rule, including rules without a column of their own.',
    cell:r=>{const n=stoppedOf(r);return n?esc(n):none(r);}, foot:()=>`<b>${esc(sumOf('total'))}</b>`});
  return columns;
}
function snapshotStagesText(cycle){const by={};for(const st of (cycle&&cycle.snapshot_stages)||[]){const k=String(st.stage||'').replace(/^peer_/,'peers\u2019 ').replace(/_/g,' ');if(!k||k==='done')continue;by[k]=(by[k]||0)+(+st.seconds||0)}
  return Object.entries(by).sort((a,b)=>b[1]-a[1]).slice(0,3).filter(([,v])=>v>=0.5).map(([k,v])=>`${k} ${Math.round(v)}s`).join(' \u00b7 ')}
function durationText(seconds){const s=Math.max(0,Number(seconds)||0);if(s<60)return `${s.toFixed(1)}s`;const m=Math.floor(s/60),r=(s%60).toFixed(1).padStart(4,'0');if(m<60)return `${m}m${r}s`;const h=Math.floor(m/60),rm=m%60;return `${h}h${String(rm).padStart(2,'0')}m${String(Math.floor(s%60)).padStart(2,'0')}s`}
function liveClock(startUtc,baseSeconds=0){const ms=Date.parse(startUtc||'');if(Number.isFinite(ms))return `<span class="live-clock" data-live-start-ms="${ms}">${esc(durationText((Date.now()-ms)/1000))}</span>`;const base=Math.max(0,Number(baseSeconds)||0);return `<span class="live-clock" data-live-base-s="${base}" data-live-render-ms="${Date.now()}">${esc(durationText(base))}</span>`}
function updateLiveClocks(){const fresh=document.body&&document.body.dataset.gsdFreshness;if(fresh==='stale'||fresh==='offline')return; document.querySelectorAll('.live-clock').forEach(el=>{const start=Number(el.dataset.liveStartMs),base=Number(el.dataset.liveBaseS),rendered=Number(el.dataset.liveRenderMs);let seconds=0;if(Number.isFinite(start)&&start>0)seconds=(Date.now()-start)/1000;else if(Number.isFinite(base))seconds=base+(Number.isFinite(rendered)?(Date.now()-rendered)/1000:0);el.textContent=durationText(seconds)})}

function etaTitle(eta){
  if(!eta) return '';
  const lines=[];
  const cs=eta.candidate_scale||{};
  if(cs.reason) lines.push(cs.factor!=null?`this law: ${cs.reason}`:`no per-law factor: ${cs.reason}`);
  if(eta.progress&&eta.progress.median_seconds!=null)
    lines.push(`this law\u2019s own estimate ${durationText(eta.progress.median_seconds)}`
               +(eta.progress.scaled_by?` (the rung\u2019s typical \u00d7 ${eta.progress.scaled_by})`
                 :eta.extrapolated?' (scaled from its own lower rung)':' (the rung\u2019s typical: no factor of its own yet)')
               +(eta.progress.remaining_seconds!=null?`, about ${durationText(eta.progress.remaining_seconds)} left`:''));
  if(eta.identifiable){
    lines.push(`Typical attempt at N=${eta.n??'this rung'} (multiplier ${eta.sweeps_multiplier}): `
      +`median ${durationText(eta.median_seconds)}`
      +(eta.p25_seconds!=null&&eta.p75_seconds!=null
        ? ` (quartiles ${durationText(eta.p25_seconds)} to ${durationText(eta.p75_seconds)})`:''));
  } else {
    lines.push('No usable estimate: '+(eta.reason||'insufficient history'));
  }
  lines.push(`From ${eta.attempts} attempt(s): ${eta.completed} finished, ${eta.censored} stopped at the `
    +`${durationText(eta.ceiling_seconds)} time ceiling`
    +(eta.discarded_short_failures?`; ${eta.discarded_short_failures} short failure(s) excluded`:'')+'.');
  lines.push('Attempts stopped at the ceiling are counted as lasting at least that long rather than '
    +'dropped, because dropping them is what makes a completions-only median read low.');
  return ` title="${esc(lines.join('\n\n'))}"`;
}
const LIVE_LINGER_MS=4000, LIVE_ENTER_MS=4000, LIVE_ABSENT_POLLS=2;
const liveSeen=new Map();
let liveDom=null, livePayload=null, livePayloadAt=0, liveCampaignShown=null;
function liveReset(){
  liveSeen.clear();
  if(!liveDom) return;
  for(const law of liveDom.laws.values()) law.el.remove();
  liveDom.laws.clear();
  liveDom.painted=false;
}
const LIVE_KIND={
  graph:{icon:'\u25b8', verb:'evolving', title:'a chain is evolving this graph'},
  commit:{icon:'\u25aa', verb:'committing', title:'the chains have finished: the worker is writing the result before the graph is probed'},
  probe:{icon:'\u25c9', verb:'probing', title:'a probe is reading this graph'},
};
const LIVE_KIND_RANK={graph:0, probe:1};
function liveLeaseRows(d){
  const out=[];
  for(const row of (d.active||[])){
    for(const job of (row.running||[])) out.push({row, job, kind:'graph', n:+job.n,
      key:`${row.candidate_id}:graph:${job.n}:${job.seed==null?'s':job.seed}`});
    for(const probe of (row.probing||[])){
      if(probe.state==='waiting') continue;
      out.push({row, job:probe, kind:'probe', n:+probe.n,
                key:`${row.candidate_id}:probe:${probe.n}:${probe.seed==null?'s':probe.seed}`});
    }
  }
  return out;
}
function liveOutcome(row, n, kind){
  const step=((row&&row.ladder)||[]).find(s=>+s.n===+n);
  if(!step) return {cls:'gone', text:'no longer listed'};
  if(step.standing==='measured') return {cls:'done', text:'measured'};
  if(step.standing==='failed') return {cls:'failed', text:'failed'};
  if(step.standing==='analyzing') return {cls:'done', text:'handed to the probes'};
  return {cls:'stopped', text:String(step.standing||'stopped')};
}
function liveScores(){
  const map=new Map();
  const shown=shownLandscape();
  for(const p of [...((shown&&shown.dimension_points)||[]), ...((shown&&shown.top_candidates)||[])]){
    const s=lawScoreOf(p);
    if(s&&!lawScoreBelow(p)) map.set(String(p.candidate_id), s.score);
  }
  return map;
}
function liveScoreEmpty(){
  const why='a law is scored from N=1,024 nodes, once the controller has read its starts there';
  return `<span class="live-score muted" title="${esc(why)}">\u2014</span>`;
}
function liveWeight(row){
  const seconds=Number(row.compute_seconds);
  if(!isFinite(seconds)||seconds<=0) return '<span class=muted>no compute yet</span>';
  return `<span class=live-weight title="every second of graph and probe time spent on this law">${esc(durationText(seconds))}</span>`;
}
function liveMultiple(elapsed, typical){
  if(!(typical>0)||!(elapsed>typical)) return '';
  const m=elapsed/typical, text=m>=10?`\u00d7${Math.round(m)}`:`\u00d7${m.toFixed(1)}`;
  return ` <span class="lease-mult${m>=10?' high':''}" title="running ${esc(durationText(elapsed))} against a typical ${esc(durationText(typical))}">${text}</span>`;
}
function liveTypical(eta){
  if(!eta||eta.extrapolated) return null;
  return eta.median_seconds!=null?+eta.median_seconds:null;
}
function liveOwnEstimate(eta){
  const p=(eta||{}).progress||{};
  return p.median_seconds!=null?+p.median_seconds:null;
}
function liveGraphFacts(lease, elapsed){
  const eta=lease.job.eta||{}, ex=eta.extrapolation||{};
  const typical=liveTypical(eta);
  if(typical!=null) return `${durationText(typical)}${liveMultiple(elapsed, typical)}`;
  const own=liveOwnEstimate(eta);
  if(own!=null) return `<span class=est-rough title="no attempt at this rung has finished yet: scaled from this law\u2019s own lower rung, not measured at this rung">~${durationText(own)} rough</span>${liveMultiple(elapsed, own)}`;
  return `<span class=est-none title="${esc(ex.reason||'no comparable attempt at this rung and no lower rung of this law to scale from')}">no estimate: ${ex.basis==null&&ex.reason?'first rung':'no basis yet'}</span>`;
}
function liveGraphBar(lease, elapsed, ended){
  const eta=lease.job.eta||{};
  const budget=Number(lease.job.budget_seconds), typical=liveTypical(eta)??liveOwnEstimate(eta);
  const span=Math.max(typical||0, budget||0, elapsed||0)||1;
  let frac=Math.max(0,Math.min(1,(elapsed||0)/span));
  let cls=(typical!=null&&elapsed>typical)?'overdue':(typical==null?'unknown':'live');
  if(ended){ cls=ended.cls==='done'?'done':'stopped'; if(ended.cls==='done') frac=1; }
  const tick=(isFinite(budget)&&budget>0)?`<i style="left:${Math.round(100*Math.min(1,budget/span))}%" title="budget ${esc(budgetText(budget))}"></i>`:'';
  return `<span class="lease-bar ${cls}"><span style="width:${Math.round(frac*100)}%"></span>${tick}</span>`;
}
const PROBE_ORDER=['d_s','d_V','d_B','d_w'];
function probeTimings(d, n){
  const row=((d&&d.rung_distribution)||[]).find(x=>+x.n===+n)||{};
  const parts=PROBE_ORDER.map(probe=>({probe, seconds:Number(row[`${probe}_median_seconds`])}))
    .filter(x=>isFinite(x.seconds)&&x.seconds>0);
  return {parts, total:parts.reduce((a,b)=>a+b.seconds,0)};
}
function liveProbeFacts(lease, elapsed, timings){
  if(!timings.total) return `<span class=est-none title="no probe at this rung has a recorded duration in this campaign yet">none at N=${esc(lease.n)} yet</span>`;
  const split=timings.parts.map(x=>`${x.probe} ${durationText(x.seconds)}`).join(', ');
  return `<span title="${esc(`median per probe at this rung: ${split}. The bar is split in these proportions: how long the probes usually take, not which one is running.`)}">${durationText(timings.total)}</span>${liveMultiple(elapsed, timings.total)}`;
}
function liveProbeBar(timings, elapsed, ended){
  if(!timings.total) return '<span class="lease-bar probe-split unknown"><span class=fill style="width:0%"></span></span>';
  let frac=Math.max(0,Math.min(1,elapsed/timings.total)), cls=elapsed>timings.total?'overdue':'live';
  if(ended){ cls=ended.cls==='done'?'done':'stopped'; if(ended.cls==='done') frac=1; }
  const segs=timings.parts.map(x=>`<b style="width:${(100*x.seconds/timings.total).toFixed(1)}%"></b>`).join('');
  return `<span class="lease-bar probe-split ${cls}"><span class=fill style="width:${Math.round(frac*100)}%"></span><em class=segs>${segs}</em></span>`;
}
function livePhaseHtml(lease){
  const k=LIVE_KIND[lease.kind==='graph'&&lease.job.phase==='committing'?'commit':lease.kind];
  return `<span class="lease-icon ${lease.kind}" title="${esc(k.title)}">${k.icon}</span>`
    +`<span class="lease-verb ${lease.kind}">${esc(k.verb)}</span>`;
}
function liveSeedHtml(lease){
  if(lease.job.seed==null){
    return lease.kind==='graph'
      ? '<span class=muted title="a sealed run, which carries no seed">sealed</span>'
      : '<span class=muted title="this payload predates 483 and carries no seed for a probe">\u2014</span>';
  }
  return `<span title="which of the rung's three seeds this is">${esc(lease.job.seed)}</span>`;
}
function liveResumed(lease){
  const before=Number(lease.job.resumed_seconds);
  return lease.kind==='graph'&&isFinite(before)&&before>0?before:0;
}
function liveElapsedSeconds(lease, now, payloadAt){
  return (Number(lease.job.since_s)||0)+liveResumed(lease)+Math.max(0,(now-payloadAt)/1000);
}
function liveElapsedHtml(lease){
  const before=liveResumed(lease);
  if(!before) return `\u23f3${liveClock(lease.job.started_utc, lease.job.since_s)}`;
  const ms=Date.parse(lease.job.started_utc||'');
  const shifted=Number.isFinite(ms)?new Date(ms-before*1000).toISOString():'';
  const why=`resumed: ${durationText(before)} of this seed's run was spent before a pause, a stop or a bundle, `
    +'saved with its chains and resumed from there, so the elapsed time and the typical multiple count it';
  return `<span class=lease-resumed title="${esc(why)}">\u23f3${liveClock(shifted, (Number(lease.job.since_s)||0)+before)}`
    +' <span class=resumed-mark>\u21bb</span></span>';
}
function liveBarHtml(lease, elapsed, ended, d){
  return lease.kind==='graph' ? liveGraphBar(lease, elapsed, ended)
                              : liveProbeBar(probeTimings(d, lease.n), elapsed, ended);
}
function liveTypicalHtml(lease, elapsed, ended, d){
  if(ended) return `<span class=muted>${esc(ended.text)}</span>`;
  if(lease.kind==='probe') return liveProbeFacts(lease, elapsed, probeTimings(d, lease.n));
  return `<span${etaTitle(lease.job.eta)}>${liveGraphFacts(lease, elapsed)}</span>`;
}
function liveBudgetHtml(lease){
  const units=unitsText(lease.job.budget_units);
  if(units===null) return '<span class=muted>\u2014</span>';
  const budget=Number(lease.job.budget_seconds);
  const about=isFinite(budget)&&budget>0?`, about ${budgetText(budget)} where the unit was fitted`:'';
  return `<span title="${esc(`this seed's budget in units of work${about}; no clock ends it`)}">${esc(units)}</span>`;
}
function liveEnsureDom(root){
  if(liveDom&&liveDom.root===root&&liveDom.grid.parentNode===root) return liveDom;
  root.innerHTML='';
  const make=(cls)=>{ const el=document.createElement('div'); el.className=cls; return el; };
  const grid=make('live-grid'), head=make('live-head'), body=make('live-body'), empty=make('empty live-empty');
  head.innerHTML='<div>candidate</div><div>law</div><div class=num>score</div>'
    +'<div class=num>compute</div><div class=num>rung</div><div>phase</div>'
    +'<div class=num>seed</div><div class=num>elapsed</div><div>progress</div>'
    +'<div class=num>typical</div><div class=num>budget</div>';
  grid.appendChild(head); grid.appendChild(body); root.appendChild(grid); root.appendChild(empty);
  liveDom={root, grid, head, body, empty, laws:new Map(), painted:false};
  return liveDom;
}
function livePatch(node, field, value, write){
  if(!node.gsdLive) node.gsdLive={};
  if(node.gsdLive[field]!==value){ node.gsdLive[field]=value; write(value); }
}
function livePlace(parent, node, index){
  const kids=parent.children;
  if(kids[index]!==node) parent.insertBefore(node, kids[index]||null);
}
function liveMakeLaw(id){
  const make=(cls)=>{ const el=document.createElement('div'); el.className=cls; return el; };
  const law={el:make('live-law'), idCell:make('live-cell law-id'), termsCell:make('live-cell law-terms'),
             scoreCell:make('live-cell law-score num'), computeCell:make('live-cell law-compute num'),
             leasesEl:make('live-leases'), leases:new Map()};
  law.el.dataset.law=id;
  for(const cell of [law.idCell, law.termsCell, law.scoreCell, law.computeCell, law.leasesEl]) law.el.appendChild(cell);
  return law;
}
function liveMakeLease(lease, animate){
  const make=(cls)=>{ const el=document.createElement('div'); el.className=cls; return el; };
  const el=make('lease');
  const cells={rungEl:make('lease-rung num'), phaseEl:make('lease-phase'), seedEl:make('lease-seed num'),
               elapsedEl:make('lease-elapsed num'), barEl:make('lease-bar-cell'),
               typicalEl:make('lease-typical num'), budgetEl:make('lease-budget num')};
  el.dataset.lease=lease.key;
  for(const cell of [cells.rungEl, cells.phaseEl, cells.seedEl, cells.elapsedEl, cells.barEl,
                     cells.typicalEl, cells.budgetEl]) el.appendChild(cell);
  return Object.assign({el, bornAt:Date.now(), animate}, cells);
}
function renderLive(d){
  const root=document.getElementById('live');
  registerLiveRegion(root);
  if(deferrableRedraw(root, ()=>renderLive(last||d), {force:!!d.paused})){ updateLiveClocks(); return; }
  if(liveCampaignShown!==String(campaign)){
    if(homeLoading&&!homeLoading.overview){ updateLiveClocks(); return; }
    liveReset(); liveCampaignShown=String(campaign);
  }
  if(d.paused) liveSeen.clear();
  const now=Date.now(), scores=liveScores(), leases=liveLeaseRows(d);
  const freshPayload=d!==livePayload;
  if(freshPayload){ livePayload=d; livePayloadAt=now; }
  const present=new Set(leases.map(l=>l.key));
  const scoresKnown=!!(landscape&&Array.isArray(landscape.dimension_points));
  for(const lease of leases){
    const prior=liveSeen.get(lease.key);
    const score=scores.has(String(lease.row.candidate_id))?scores.get(String(lease.row.candidate_id)):null;
    const start=prior&&prior.scoreAtStart!==undefined?prior.scoreAtStart:(scoresKnown?score:undefined);
    liveSeen.set(lease.key, {lease, since:prior?prior.since:now, scoreAtStart:start, missing:0, ended:null});
  }
  for(const [key, seen] of liveSeen){
    if(present.has(key)) continue;
    if(seen.ended==null){
      if(freshPayload) seen.missing+=1;
      if(seen.missing>=LIVE_ABSENT_POLLS) seen.ended=now;
    } else if(now-seen.ended>LIVE_LINGER_MS) liveSeen.delete(key);
  }
  const dom=liveEnsureDom(root);
  const rows=[...liveSeen.values()].sort((a,b)=>a.since-b.since);
  if(!rows.length){
    const u=d.compute_utilization||{}, ana=Number(u.analysis_busy||0), backlog=Number(d.analysis_backlog||0);
    for(const law of dom.laws.values()) law.el.remove();
    dom.laws.clear();
    dom.grid.hidden=true; dom.empty.hidden=false;
    livePatch(dom.empty, 'html', ana||backlog
      ?`no chain and no probe holds a lease for a listed candidate &mdash; ${esc(ana)} analysis job(s) in flight`+(backlog?`, ${esc(backlog)} queued`:'')
      :'nothing is running &mdash; no chain is evolving and no probe is running. On a finished campaign this is the expected reading; otherwise read System &rarr; capacity verdict.',
      v=>{ dom.empty.innerHTML=v; });
    dom.painted=true;
    return;
  }
  dom.grid.hidden=false; dom.empty.hidden=true;
  const groups=new Map();
  for(const seen of rows){
    const id=String(seen.lease.row.candidate_id);
    if(!groups.has(id)) groups.set(id, []);
    groups.get(id).push(seen);
  }
  const current=new Map((d.active||[]).map(a=>[String(a.candidate_id), a]));
  const keepLaws=new Set();
  let lawIndex=0;
  for(const [id, seens] of groups){
    keepLaws.add(id);
    const row=current.get(id)||seens[seens.length-1].lease.row;
    let law=dom.laws.get(id);
    if(!law){
      law=liveMakeLaw(id); dom.laws.set(id, law);
      if(dom.painted){ law.enteringAt=now; law.el.style.maxHeight='0px'; livePatch(law.el, 'cls', 'live-law entering', v=>{ law.el.className=v; }); }
    }
    livePlace(dom.body, law.el, lawIndex++);
    const allEnded=seens.every(x=>x.ended!=null);
    if(allEnded&&!law.leaving){
      law.leaving=true; law.enteringAt=0;
      law.el.style.maxHeight=`${law.el.offsetHeight||law.el.scrollHeight||0}px`;
      livePatch(law.el, 'cls', 'live-law leaving', v=>{ law.el.className=v; });
      requestAnimationFrame(()=>{ if(law.leaving) law.el.style.maxHeight='0px'; });
    } else if(!allEnded&&law.leaving){
      law.leaving=false; law.el.style.maxHeight='';
      livePatch(law.el, 'cls', 'live-law', v=>{ law.el.className=v; });
    } else if(law.enteringAt&&now-law.enteringAt>LIVE_ENTER_MS){
      law.enteringAt=0; law.el.style.maxHeight='';
      livePatch(law.el, 'cls', 'live-law', v=>{ law.el.className=v; });
    }
    const score=scores.has(id)?scores.get(id):null, started=seens[0].scoreAtStart;
    const moved=started===undefined?'':(score!=null&&started!=null&&score!==started)
      ?`<span class="score-move ${score>started?'up':'down'}">${score>started?'\u25b2':'\u25bc'}${esc(Math.abs(score-started))}</span>`
      :(score!=null&&started==null?'<span class="score-move up">first</span>':'');
    livePatch(law.idCell, 'html', `<a class=candidate-link href="${candidateHref(id)}" title="${candidateTitle(row)}">${candidateLabel(row)}</a>`, v=>{ law.idCell.innerHTML=v; });
    livePatch(law.termsCell, 'html', row.terms?.length?TERMS.html(row.terms,{compact:true}):`<span class=muted>${esc(row.law||'')}</span>`, v=>{ law.termsCell.innerHTML=v; });
    livePatch(law.scoreCell, 'html', (score==null?liveScoreEmpty():`<span class=live-score>${esc(score)}</span>`)
      +(moved?'<wbr>'+moved:''), v=>{ law.scoreCell.innerHTML=v; });
    livePatch(law.computeCell, 'html', liveWeight(row), v=>{ law.computeCell.innerHTML=v; });
    const ordered=seens.slice().sort((a,b)=>(b.lease.n-a.lease.n)
      ||(LIVE_KIND_RANK[a.lease.kind]-LIVE_KIND_RANK[b.lease.kind])||(a.lease.key<b.lease.key?-1:1));
    const keep=new Set();
    let previousN=null, index=0;
    for(const seen of ordered){
      const {lease}=seen;
      keep.add(lease.key);
      let node=law.leases.get(lease.key);
      if(!node){ node=liveMakeLease(lease, dom.painted); law.leases.set(lease.key, node); }
      livePlace(law.leasesEl, node.el, index++);
      const ended=seen.ended!=null?liveOutcome(row, lease.n, lease.kind):null;
      const elapsed=liveElapsedSeconds(lease, now, livePayloadAt);
      const sameRung=previousN===lease.n;
      previousN=lease.n;
      const entering=node.animate&&!ended&&now-node.bornAt<LIVE_ENTER_MS;
      livePatch(node.el, 'cls', `lease ${lease.kind}${sameRung?' same-rung':''}${entering?' entering':''}${ended?` leaving ${ended.cls}`:''}`,
                v=>{ node.el.className=v; });
      livePatch(node.rungEl, 'html', sameRung?'':`<code>N=${esc(lease.n)}</code>`,
                v=>{ node.rungEl.innerHTML=v; });
      livePatch(node.phaseEl, 'html', livePhaseHtml(lease), v=>{ node.phaseEl.innerHTML=v; });
      livePatch(node.seedEl, 'html', liveSeedHtml(lease), v=>{ node.seedEl.innerHTML=v; });
      livePatch(node.elapsedEl, 'html', liveElapsedHtml(lease), v=>{ node.elapsedEl.innerHTML=v; });
      livePatch(node.barEl, 'html', liveBarHtml(lease, elapsed, ended, d), v=>{ node.barEl.innerHTML=v; });
      livePatch(node.typicalEl, 'html', liveTypicalHtml(lease, elapsed, ended, d), v=>{ node.typicalEl.innerHTML=v; });
      livePatch(node.budgetEl, 'html', liveBudgetHtml(lease), v=>{ node.budgetEl.innerHTML=v; });
    }
    for(const [key, node] of law.leases) if(!keep.has(key)){ node.el.remove(); law.leases.delete(key); }
  }
  for(const [id, law] of dom.laws) if(!keepLaws.has(id)){ law.el.remove(); dom.laws.delete(id); }
  for(const law of dom.laws.values()) if(law.enteringAt&&law.el.style.maxHeight==='0px')
    requestAnimationFrame(()=>{ if(law.enteringAt) law.el.style.maxHeight=`${law.el.scrollHeight||0}px`; });
  dom.painted=true;
  updateLiveClocks();
}

const CHANNEL_HELP={
  d_s:{title:'d_s · spectral dimension',
       body:'How readily the graph conducts diffusion. From a random walk\u2019s return probability, p(t) ~ t^(-d_s/2).'},
  d_V:{title:'d_V · distance-volume exponent',
       body:'How mass grows with distance, B(r) ~ r^d_V, averaged over sampled sources. It measures volume growth, not a Hausdorff dimension.'},
  d_B:{title:'d_B · box-covering exponent',
       body:'How many radius-r balls are needed to cover the whole component, N(r) ~ r^-d_B. A global cover, so it notices sparse regions that source-averaged channels smooth over. Withheld entirely when box counts are not power-law in radius.'},
  d_w:{title:'d_w · walk dimension',
       body:'How far a random walker gets, \u27e8r\u00b2\u27e9 ~ t^(2/d_w). Exactly 2 is ordinary diffusion; above 2 means the walker is trapped by dead ends, which is the signature of a fractal.'}
};
const BAND_HELP={
  einstein:{title:'5th band: all four agree by the Einstein relation',
    body:'All four probes settled, and they agree with one another as a geometry\u2019s must: d_s = 2 d_f / d_w, with d_f read by d_V and by d_B alike, within the tolerance the calibration table\u2019s exact lattices and fractals set (resources/calibration/score_margins.json). A space without holes reads d_w = 2 and d_s = d_V = d_B; a fractal reads d_w above 2 and d_s below d_f. The strongest the chart can say of a chain.'},
  tier4:{title:'4 probes: all four settled',
    body:'Every channel settled on this law: d_s, d_V, d_B and d_w, but they do not agree by the Einstein relation d_s = 2 d_f / d_w within its tolerance, so they are not yet one geometry: the band above holds the chains where they do. Hover a point for how far the relation misses.'},
  tier3:{title:'3 probes settled',
    body:'Three of the four independent channels settled on this law. A single settled probe is weak evidence: build 274 measured 78 of 104 CONVERGED blocks as probes drifting monotonically, too coarsely measured to notice they were still climbing. Agreement across channels that fail differently is the cheapest check on that. A law settling on all four has its own band above this one.'},
  tier2:{title:'2 probes settled',
    body:'Two of the four channels settled. Read which two before believing it: d_w is tied to the other channels by the Einstein relation rather than independent of them, so d_s + d_w is closer to one channel voting twice; and the atlas shows d_V and d_B both plateau on at least one known geometry, so that pair can agree on a shared artefact. The pair is on the specimen tooltip.'},
  contracting:{title:'1 probe settled',
    body:'At least one of the four probes has settled: its successive factor-of-four steps in N shrank toward the instrument\u2019s own noise floor, so that block scored a full 25. One probe is enough: the score is four independent blocks and this band asks whether any geometry is settling, not whether all of them are.'},
  flowing:{title:'Flowing',
    body:'No probe has settled yet. Drift persists or grows as N increases, or too few valid rungs exist to have an opinion, so no finite value should be read off these estimates. Faint marks are small worlds: the radius grows like ln N on the rungs the readings come from, so there is no dimension to read, and their box and volume readings creep up toward ln N / ln(diameter) however settled their steps look (581). Faint dashed marks are readings one seed of three gave, the other two refusing it at that size; in study 174 (06:26Z) the d_w readings near 4, 6.6 and 8.6 are such, on graphs in pieces or trees whose next sizes every seed refused (861).'}
};
function bandCountText(count){
  const n=+count||0;
  return n?`${n.toLocaleString()} law${n===1?'':'s'}`:'none yet';
}
function bandOf(p){
  if(p&&p.landscape_band)return p.landscape_band;
  const tier=(p&&(p.stability_contracting_tier??(p.stability_contracting_probes||[]).length))|0;
  if(tier>=4&&p&&p.einstein&&p.einstein.agree)return 'einstein';
  if(tier>=4)return 'tier4';
  if(tier>=3)return 'tier3';
  if(tier===2)return 'tier2';
  if(p&&p.contracting_band)return 'contracting';
  return 'flowing';
}
let labelHits=[],channelCounts={},bandLayout=[];

function settledOf(p){return Array.isArray(p&&p.settled_probes)?p.settled_probes:((p&&p.stability_contracting_probes)||[])}
function estimateOf(point,key){
  const v=point?.[key];
  return (typeof v==='number'&&Number.isFinite(v))?v:null;
}
function drawLandscape(points){
  const c=document.getElementById('land'),tip=document.getElementById('landTip');
  if(!c)return;
  registerLiveRegion(c);
  if(deferrableRedraw(c,()=>drawLandscape(points))) return;
  renderLandscape(c,tip,points);
  restoreTooltip();
}

function renderLandscape(c,tip,points){
  const dpr=devicePixelRatio||1,box=c.getBoundingClientRect();
  if(!box.width)return;
  const H=Math.max(120,Math.round(box.height));
  c.width=Math.max(1,box.width*dpr); c.height=Math.max(1,H*dpr);
  const x=c.getContext('2d'); x.scale(dpr,dpr);
  const W=box.width,css=getComputedStyle(document.documentElement),
    bg=css.getPropertyValue('--panel2').trim()||'#080c0f',
    line=css.getPropertyValue('--line').trim()||'#1c2822',
    muted=css.getPropertyValue('--muted').trim()||'#77838f',
    blue=css.getPropertyValue('--blue').trim()||'#6fa8ff',
    amber=css.getPropertyValue('--amber').trim()||'#d0a13b',
    green=css.getPropertyValue('--green').trim()||'#63d58a',
    teal=css.getPropertyValue('--teal').trim()||'#4fd1c5',
    orange=css.getPropertyValue('--orange').trim()||'#e08a4b';

  const CHANNELS=[
    {id:'d_s',key:'d_s_estimate',src:'d_s_source',mark:'circle',  color:'#0072B2'},
    {id:'d_V',key:'d_v_estimate',src:'d_v_source',mark:'diamond', color:'#E69F00'},
    {id:'d_B',key:'d_b_estimate',src:'d_b_source',mark:'square',  color:'#009E73'},
    {id:'d_w',key:'d_w_estimate',src:'d_w_source',mark:'triangle',color:'#CC79A7'}
  ];

  x.clearRect(0,0,W,H); x.fillStyle=bg; x.fillRect(0,0,W,H);

  const vals=[];
  for(const p of points||[]) for(const ch of CHANNELS){
    const v=estimateOf(p,ch.key); if(v!==null) vals.push(v);
  }

  const GUTTER=94,left=GUTTER,right=16,top=52,bottom=46;
  const plotW=Math.max(10,W-left-right);
  const max=Math.max(4,Math.ceil(vals.reduce((m,v)=>v>m?v:m,4)));
  const X=v=>left+Math.max(0,Math.min(max,+v))/max*plotW;

  if(!vals.length){
    x.fillStyle=muted; x.font='12px monospace';
    x.fillText('no valid dimension estimates yet',left,H/2);
    if(tip)tip.style.display='none';
    hitPoints=[]; return;
  }

  x.strokeStyle=line; x.fillStyle=muted; x.font='10px monospace';
  for(let i=0;i<=max;i++){
    const xx=X(i);
    x.beginPath(); x.moveTo(xx,top); x.lineTo(xx,H-bottom); x.stroke();
    x.fillText(String(i),xx-3,H-30);
  }
  x.fillText('dimension estimate',left,H-12);

  let lx=left; labelHits=[];
  const settledPerChannel=Object.create(null);
  for(const p of points||[]) for(const id of settledOf(p))
    settledPerChannel[id]=(settledPerChannel[id]||0)+1;
  for(const ch of CHANNELS){
    drawMark(x,ch.mark,lx+4,14,ch.color,4);
    const count=channelCounts[ch.id],settled=settledPerChannel[ch.id]||0;
    const label=count==null?ch.id:`${ch.id} ${count} (${settled} settled)`;
    x.fillStyle=muted; x.fillText(label,lx+12,18);
    const width=22+x.measureText(label).width;
    labelHits.push({x:lx,y:4,w:width,h:18,help:CHANNEL_HELP[ch.id],channel:ch.id,label});
    lx+=width+14;
  }
  drawMark(x,'circle',lx+12,14,muted,4,true);
  drawMark(x,'circle',lx+30,14,muted,4,false);
  x.fillStyle=muted;
  x.fillText('settled / not settled \u00b7 shape and colour = channel',lx+40,18);
  const kx=lx+48+x.measureText('settled / not settled \u00b7 shape and colour = channel').width;
  if(kx+8+x.measureText('withheld, not a reading').width<W&&(points||[]).some(p=>p.withheld&&Object.keys(p.withheld).length)){
    x.globalAlpha=.55; drawMark(x,'circle',kx,14,muted,3.5,false,true); x.globalAlpha=1;
    x.fillStyle=muted; x.fillText('withheld, not a reading',kx+8,18);
  }

  const plotTop=top+42, plotBottom=H-bottom-14, span=Math.max(60,plotBottom-plotTop);
  const COLLAPSED=26;
  const occupancy=Object.create(null);
  for(const p of points||[]) occupancy[bandOf(p)]=(occupancy[bandOf(p)]||0)+1;
  const specs=[
    {id:'einstein',label:'EINSTEIN'},
    {id:'tier4',label:'4 PROBES'},
    {id:'tier3',label:'3 PROBES'},
    {id:'tier2',label:'2 PROBES'},
    {id:'contracting',label:'1 PROBE'},
    {id:'flowing',label:'FLOWING'}
  ];
  const open=specs.filter(s=>occupancy[s.id]);
  const expanded=new Set((open.length?open:specs.filter(s=>s.id==='contracting'||s.id==='flowing')).map(s=>s.id));
  const share=(span-(specs.length-expanded.size)*COLLAPSED)/Math.max(1,expanded.size);
  const bands=[]; let cursor=plotTop;
  for(const s of specs){
    const h=expanded.has(s.id)?Math.max(COLLAPSED,share):COLLAPSED;
    const wanted=Math.min(44,Math.round(h*0.42));
    const rowGap=Math.max(6,Math.min(46,(h-wanted-8)/Math.max(1,CHANNELS.length-1)));
    const head=Math.max(0,Math.min(wanted,Math.floor(h-(CHANNELS.length-1)*rowGap-1)));
    bands.push({...s,top:cursor,h,y:cursor+Math.min(26,head),head,rowGap});
    cursor+=h;
  }
  const bandById=Object.create(null);
  for(const b of bands) bandById[b.id]=b;
  bandLayout=bands.map(b=>({id:b.id,top:b.top,height:b.h,head:b.head,rowGap:b.rowGap,
    count:occupancy[b.id]||0}));
  x.font='11px monospace';
  for(const b of bands){
    x.strokeStyle=line; x.beginPath();
    x.moveTo(left,b.top); x.lineTo(W-right,b.top); x.stroke();
    x.fillStyle=muted;
    x.fillText(b.label,8,b.y);
    x.font='9px monospace'; x.fillStyle=line;
    x.fillText(bandCountText(occupancy[b.id]),8,b.y+13);
    x.font='11px monospace';
    labelHits.push({x:4,y:b.y-12,w:GUTTER-8,h:30,help:BAND_HELP[b.id]});
  }

  const bins=Array.from({length:max*2+1},()=>Object.create(null));
  for(const p of points||[]) for(const ch of CHANNELS){
    const v=estimateOf(p,ch.key); if(v===null)continue;
    const i=Math.min(bins.length-1,Math.max(0,Math.floor(v*2)));
    bins[i][ch.id]=(bins[i][ch.id]||0)+1;
  }
  let bmax=1;
  for(const b of bins) for(const ch of CHANNELS) bmax=Math.max(bmax,b[ch.id]||0);
  const bw=plotW/bins.length, sub=bw/CHANNELS.length;
  x.globalAlpha=.55;
  for(let i=0;i<bins.length;i++){
    CHANNELS.forEach((ch,k)=>{
      const n=bins[i][ch.id]||0; if(!n)return;
      const h=n/bmax*Math.max(18,Math.min(46,(plotTop-top)*0.7));
      x.fillStyle=ch.color;
      x.fillRect(left+i*bw+k*sub,plotTop-4-h,Math.max(1,sub*.8),h);
    });
  }
  x.globalAlpha=1;

  hitPoints=[];
  for(const p of points||[]){
    const band=bandById[bandOf(p)]||bands[bands.length-1];
    const settled=new Set(p.small_world?[]:settledOf(p));
    const faint=!!p.small_world;
    if(faint)x.globalAlpha=.3;
    CHANNELS.forEach((ch,k)=>{
      const v=estimateOf(p,ch.key);
      const py=band.top+band.head+k*band.rowGap+stableJitter(p.candidate_id,ch.id);
      if(v===null){
        const w=(p.withheld||{})[ch.id]; if(!w||!isFinite(+w.value))return;
        const px=X(+w.value);
        x.globalAlpha=.55; drawMark(x,ch.mark,px,py,ch.color,3.5,false,true); x.globalAlpha=faint?.3:1;
        hitPoints.push({x:px,y:py,p,metric:ch.id,value:+w.value,band:band.id,settled:false,smallWorld:faint,withheld:w});
        return;
      }
      const px=X(v),from=(p.readings_from||{})[ch.id],lone=oneSeedReading(from);
      if(lone)x.globalAlpha=.35;
      drawMark(x,ch.mark,px,py,ch.color,4.5,settled.has(ch.id)&&!lone,lone);
      if(lone)x.globalAlpha=faint?.3:1;
      hitPoints.push({x:px,y:py,p,metric:ch.id,value:v,band:band.id,settled:settled.has(ch.id),smallWorld:faint,from});
    });
    if(faint)x.globalAlpha=1;
  }
  if(tip)tip.style.display='none';
}

function drawMark(x,shape,px,py,color,r,filled=true,dashed=false){
  x.beginPath();
  x.setLineDash(dashed?[2,2]:[]);
  if(shape==='circle'){x.arc(px,py,r,0,Math.PI*2);}
  else if(shape==='diamond'){x.moveTo(px,py-r);x.lineTo(px+r,py);x.lineTo(px,py+r);x.lineTo(px-r,py);x.closePath();}
  else if(shape==='square'){x.rect(px-r*.85,py-r*.85,r*1.7,r*1.7);}
  else {x.moveTo(px,py-r);x.lineTo(px+r,py+r);x.lineTo(px-r,py+r);x.closePath();}
  if(filled){x.fillStyle=color; x.fill();}
  else {x.strokeStyle=color; x.lineWidth=1.4; x.stroke();}
  if(dashed)x.setLineDash([]);
}
function nearest(ev){const c=document.getElementById('land'),r=c.getBoundingClientRect(),px=ev.clientX-r.left,py=ev.clientY-r.top;let best=null,dist=9;for(const h of hitPoints){const d=Math.hypot(h.x-px,h.y-py);if(d<dist){best=h;dist=d}}return{best,px,py}}

function plateauBreakLine(b){const n=v=>Number(v).toLocaleString('en-US');return `<b>plateau, then break</b>: d_s held near ${esc(Number(b.plateau_value).toFixed(2))} from N=${esc(n(b.plateau_from))} to ${esc(n(b.plateau_to))}, then ${esc(Number(b.from).toFixed(2))} \u2192 ${esc(Number(b.to).toFixed(2))} at N=${esc(n(b.break_at))} (${esc(Number(b.sigmas).toFixed(1))} standard errors)`}
function oneSeedReading(from){return !!from&&from.seeds!=null&&from.of>1&&from.seeds<2}
function readingFromLine(from){if(!from||from.seeds==null)return '';const n=v=>Number(v).toLocaleString('en-US');
  const above=(from.refused_above||[]).map(([m,why])=>`${n(m)}${why?` (${esc(String(why).toLowerCase().replace(/_/g,' '))})`:''}`).join(', ');
  return `read on ${esc(from.seeds)} of ${esc(from.of)} seeds at N=${esc(n(from.n))}${oneSeedReading(from)?' (drawn faint: the other seeds refused it there)':''}`
    +(above?`; every seed refused it at ${above}`:'')+'<br>'}
function withheldLine(h){const w=h.withheld||{},why=Object.entries(w.reasons||{}).map(([k,v])=>`${esc(k)} on ${esc(v)}`).join(', ');
  return `${esc(h.metric)} <b>withheld</b>: computed ${esc(Number(w.value).toFixed(3))}${w.seeds?` on ${esc(w.seeds)} seed(s)`:''}`
    +`${w.n?` at N=${esc(Number(w.n).toLocaleString('en-US'))}`:''} and refused${why?` (${why})`:''}; not a reading, `
    +`and no rung of this law read ${esc(h.metric)}<br>`}
function tooltipHtml(h,{pinned=false}={}){
  const p=h.p,src=p[{d_s:'d_s_source',d_V:'d_v_source',d_B:'d_b_source',d_w:'d_w_source'}[h.metric]]||'current';
  const code=p.ensemble_code?`<b>${candidateLabel(p)}</b><br><span class=muted>${esc(p.candidate_id.slice(0,16))}</span>`
                            :`<b>${esc(p.candidate_id.slice(0,16))}</b>`;
  return (pinned?`<button class="tip-close" data-tip-close="1" title="unpin">×</button>`:'')
    +code+`<br>`
    +(h.withheld?withheldLine(h):`${esc(h.metric)} ${esc(h.value)} · ${esc(src)} · score ${esc(lawScoreOf(p)?lawScoreOf(p).score:'not yet')}<br>`+readingFromLine(h.from))
    +(p.stability_control_family?`control: reproduces ${esc(p.stability_control_family)} \u00b7 points withheld<br>`:'')
    +(p.small_world?`<b>small world</b>: the radius grows like ln N from N=${esc(Number((p.small_world.sizes||[])[0]).toLocaleString('en-US'))}, so no dimension to read<br>`:'')
    +(p.stability_plateau_break?plateauBreakLine(p.stability_plateau_break)+'<br>':'')
    +`${esc(p.state||'measured')}`
    +(p.terms?.length?'<br>'+TERMS.html(p.terms,{compact:true}):'')
    +(pinned?'<br><span class=muted>click to open · × to unpin</span>':'');
}

function showTooltip(h,px,py){
  const canvas=document.getElementById('land'),tip=document.getElementById('landTip');
  if(!canvas||!tip)return;
  const pinned=getPinned()===`${h.p.candidate_id}:${h.metric}`;
  tip.innerHTML=tooltipHtml(h,{pinned});
  tip.style.pointerEvents=pinned?'auto':'none';
  tip.dataset.candidate=pinned?h.p.candidate_id:'';tip.dataset.campaign=pinned&&h.p.campaign_id!=null?h.p.campaign_id:'';
  tip.style.display='block';
  tip.style.left=Math.min(px+12,canvas.clientWidth-240)+'px';
  tip.style.top=Math.max(6,py-18)+'px';
}

function restoreTooltip(){
  const key=getPinned(); if(!key)return;
  const match=hitPoints.find(h=>`${h.p.candidate_id}:${h.metric}`===key);
  if(!match){setPinned(null);const tip=document.getElementById('landTip');if(tip)tip.style.display='none';return}
  showTooltip(match,match.x,match.y);
}

const canvas=document.getElementById('land');
function labelAt(px,py){
  for(const hit of labelHits){
    if(hit.help && px>=hit.x && px<=hit.x+hit.w && py>=hit.y && py<=hit.y+hit.h) return hit;
  }
  return null;
}

canvas?.addEventListener('mousemove',ev=>{
  if(getPinned())return;
  const{best,px,py}=nearest(ev),tip=document.getElementById('landTip');
  const label=labelAt(px,py);
  if(label){
    tip.innerHTML=`<b>${esc(label.help.title)}</b><br>${esc(label.help.body)}`;
    tip.style.pointerEvents='none'; tip.dataset.candidate='';
    tip.style.display='block';
    tip.style.left=Math.min(px+12,canvas.clientWidth-300)+'px';
    tip.style.top=Math.max(6,py+14)+'px';
    canvas.style.cursor='help'; return;
  }
  if(!best){tip.style.display='none';canvas.style.cursor='default';return}
  showTooltip(best,px,py); canvas.style.cursor='pointer';
});
canvas?.addEventListener('mouseleave',()=>{
  if(getPinned())return;
  const tip=document.getElementById('landTip'); if(tip)tip.style.display='none';
});
canvas?.addEventListener('click',ev=>{
  const{best,px,py}=nearest(ev);
  if(!best){setPinned(null);const tip=document.getElementById('landTip');if(tip)tip.style.display='none';return}
  const key=`${best.p.candidate_id}:${best.metric}`;
  setPinned(key); showTooltip(best,px,py);
});

document.getElementById('landTip')?.addEventListener('click',ev=>{
  const tip=ev.currentTarget;
  if(ev.target?.dataset?.tipClose){
    setPinned(null); tip.style.display='none'; tip.style.pointerEvents='none';
    ev.stopPropagation(); return;
  }
  if(tip.dataset.candidate) location.href=candidateHref(tip.dataset.candidate,tip.dataset.campaign);
});
let landMetaKey=null, gatesKey=null;
const GATE_STATE={'records only':'records only','testing':'testing','confirmed':'confirmed','A/B':'A/B'};
function gatesBoxHtml(g){
  if(!g) return '<div class=empty>no gate counters: this campaign is not on the let-through rule, or its landscape is still loading</div>';
  const about=g.about||{}, rows=[];
  for(const [gate,bySize] of Object.entries(g.gates||{})) for(const [n,e] of Object.entries(bySize||{})) rows.push({gate,n:+n,...e});
  for(const [gate,a] of Object.entries(about)) if(a&&a.let_through&&!(g.gates||{})[gate]) rows.push({gate,n:0,unfired:true});
  const order=gate=>{const a=about[gate]||{};return [a.order==null?99:+a.order, gate]};
  rows.sort((a,b)=>{const x=order(a.gate),y=order(b.gate);return (x[0]-y[0])||(x[1]<y[1]?-1:x[1]>y[1]?1:0)||a.n-b.n});
  const pct=v=>v>=1?'all':`${Math.round(v*100)}%`;
  const scoring=Array.isArray(g.scored_from), atLeast=g.scored_at_least?'\u2265':'';
  const scoredCell=r=>!scoring?'':`<td class=num>${r.scored?`<b>${esc(atLeast+fmt(r.scored))}</b> <small class=muted>best ${esc(fmt(r.best_score))}</small>`:esc(fmt(r.scored||0))}</td>`;
  let shown=null;
  const body=rows.length?rows.map(r=>{const a=about[r.gate]||{},first=r.gate!==shown;shown=r.gate;
    return `<tr class="gate-${r.unfired?'unfired':esc(String(r.label).replace('/','').replace(' ','-'))}${first?' gate-first':''}"><td>${first?`<b>${esc(r.gate)}</b>${a.reads?`<small class=gate-reads>${esc(a.reads)}</small>`:''}`:''}</td>`
      +`<td>${first?esc(a.kind||''):''}</td>`+(r.unfired?`<td class=num>\u2013</td><td colspan=${scoring?7:6} class=muted>not fired yet in this study</td></tr>`:`<td class=num><code>N=${esc(fmt(r.n))}</code></td><td>${esc(GATE_STATE[r.label]||r.label)} ${esc(pct(+r.share))}</td>`
      +`<td class=num>${esc(fmt(r.held||0))}</td><td class=num>${esc(fmt(r.let_through))}</td><td class=num>${esc(fmt(r.clean))}</td>`
      +`<td class=num>${esc(fmt(r.missed))}</td><td class=num>${esc(fmt(r.open))}</td>${scoredCell(r)}</tr>`)}).join('')
    :`<tr><td colspan=${scoring?10:9} class=muted>no gate has fired yet in this study</td></tr>`;
  const rule=+g.ab_share>0
    ?`Every gate lets ${esc(pct(+g.ab_share))} of the laws it would hold back through, each law\u2019s arm drawn once for the gate, so a law in its B arm is never held back by it and what it would have held back is measured; no gate confirms.`
    :`From N=${esc(fmt(g.from_n))} a gate lets ${esc(pct(g.testing_share))} through until ${esc(fmt(g.confirm_after))} of its let-through laws in a row were held back again one size up, then ${esc(pct(g.confirmed_share))}; a miss puts it back.`;
  const seen=(g.signatures||[]).filter(x=>x.known??x.seen_enough).length;
  return `<table class="gates-box"><thead><tr><th>gate</th><th>kind</th><th class=num>at</th><th>share</th>`
    +`<th class=num title="laws it held back at this size">held back</th><th class=num title="laws it would have held back that went one size on">let through</th>`
    +`<th class=num title="of those, held back one size up by any gate">held again</th><th class=num title="of those, passed every gate one size up">passed</th>`
    +`<th class=num title="of those, not judged yet or at the ladder\u2019s top">open</th>`
    +(scoring?`<th class=num title="of the laws it let through, how many score above zero now, and the best score: what it would have held back that scored${g.scored_from.length===1?'; scores read in this batch only':''}">scored${g.scored_from.length===1?` <small class=muted>batch ${esc(g.scored_from[0])}</small>`:''}</th>`:'')
    +`</tr></thead><tbody>${body}</tbody></table>`
    +`<p class=gates-foot>Every gate at every size has its own counter, read from this study\u2019s decisions alone. Below N=${esc(fmt(g.from_n))} every verdict is recorded and every law goes on. ${rule} repeats_a_known_result reads from N=${esc(fmt(g.known_result_from||g.seen_enough_from||g.from_n))}: ${esc(fmt(seen))} signature(s) of ${esc(fmt(g.signatures_total||0))} kept by ${esc(fmt(g.known_result_after??g.seen_enough_after))} laws one size up.</p>`;
}
function renderGatesBox(){
  const root=document.getElementById('gatesBox');if(!root)return;
  const shown=shownLandscape(), g=shown&&shown.gates_ledger;
  const key=g?`${shown.revision||''}|${shown.generated_utc||''}|${g.decisions_read||0}`:'none';
  if(key===gatesKey)return;gatesKey=key;root.innerHTML=gatesBoxHtml(g||null);
}
const CAMPAIGN_SCOPE_IDS=['landScope','topScope','ladderScope','liveScope','reportScope','gateScope','workScope'];
function liveCampaignRows(){return (SYS.campaignRows||[]).filter(r=>r.status!=='archived')}
function oneCampaign(){if(String(campaign)!=='study')return campaign;const rows=((studyNow||{}).campaigns||[]).filter(r=>r.study_batch).map(r=>String(r.campaign_id)).sort(NATSORT.compare);return rows[0]||(SYS.campaignRows||[])[0]?.campaign_id||campaign}
function paintCampaignScope(){const id=campaign==null?'':String(campaign),all=id==='study';for(const key of CAMPAIGN_SCOPE_IDS){const el=document.getElementById(key);if(!el)continue;el.textContent=all?'all batches':(id?`C${id}`:'');el.title=all?'this panel reads every batch of the study together (652); a batch alone is a card in The study now, on Home':(id?`this panel reads campaign ${id} alone; pick another in The study now, on Home`:'')}const one=document.getElementById('explorerScopeOne');if(one)one.textContent=all?'all batches':(id?`campaign ${id}`:'this campaign');
  const others=document.getElementById('explorerScopeOthers');if(others){const ids=liveCampaignRows().map(r=>String(r.campaign_id)).filter(x=>x!==id).sort((a,b)=>NATSORT.compare(a,b));others.innerHTML=ids.map(x=>`<option value="c:${esc(x)}">campaign ${esc(x)}</option>`).join('');others.hidden=!ids.length}}
let studyNow=null,studyNowAt=0;
async function refreshStudyNow(force=false){if(!force&&Date.now()-studyNowAt<15000){renderStudyNow(studyNow);return}studyNowAt=Date.now();try{studyNow=await get('/api/campaigns/overview')}catch(e){return}renderStudyNow(studyNow)}
function notPriced(rungs){const ns=[...new Set((rungs||[]).map(Number).filter(n=>n>0))].sort((a,b)=>a-b);return ` · time left not known yet${ns.length?` (no seed at N=${ns.map(n=>fmt(n)).join(', ')} has ended here)`:''}`}
function workLeftText(queuedHours,queuedPace,expectedHours,expectedPace){
  const pace=h=>h>0?`, ${fmt(Math.round(h*10)/10)} h at the last hour's pace`:'';
  if(!(expectedHours>queuedHours)) return ` · at least ${fmt(queuedHours)} core-h left${pace(queuedPace)}`;
  const said=`at least ${fmt(queuedHours)} core-hours are queued now, each seed at its size's median; this figure takes each at the mean, which the slow seeds raise, and adds the sizes the laws still climbing are expected to buy, from the share of laws that went on at each size`;
  return ` · <span title="${esc(said)}">about ${fmt(Math.round(expectedHours*10)/10)} core-h left${pace(expectedPace)}</span>`;
}
function studyCard(r){const id=String(r.campaign_id),b=r.law_budget||{},held=b.laws_held??r.laws_total,budget=b.law_budget,work=r.work_left||{},running=+r.slots_held||0,analysing=+r.analyses_running||0,queued=+r.work_queued||0,live=running+analysing>0;
  const laws=`<span title="${esc(LAWS_WAITING_TIP)}">${cardLawsText(held,budget,lawsWaitingOf(r))}</span>`,deep=r.deepest_n?` · deepest N=${fmt(r.deepest_n)}`:'';
  const left=work.core_hours_left==null?'':(+work.core_hours_left>0?workLeftText(+work.core_hours_left,+work.hours_at_last_hours_pace,+work.core_hours_expected,+work.hours_expected_at_last_hours_pace):(queued>0||(work.unpriced_rungs||[]).length?notPriced(work.unpriced_rungs):' · nothing left to run'));
  const verdict=r.control_verdict&&r.control_verdict.overall?` · controls ${esc(r.control_verdict.overall)}`:'';
  const k=+r.chains_per_seed||1,done=(+(r.graphs_finished??r.graphs_total)||0)*k,created=(r.graphs_bought??r.graphs_created)==null?null:+(r.graphs_bought??r.graphs_created)*k,current=id===String(campaign);
  const graphs=created!=null&&created>done?`${fmt(created)} graphs, ${fmt(done)} done`:`${fmt(created??done)} graphs`;
  const tip=current?`campaign ${esc(id)}: the landscape, Top 100, the fleet ladder and Now researching below read this one`
    :`show campaign ${esc(id)} in the panels below and on every page that reads one campaign`;
  return `<button type=button class="study-card${current?' current':''}" data-campaign="${esc(id)}" title="${tip}"><span class=study-card-head><b>C${esc(id)}</b><span class="study-card-state${live?' live':''}">${esc(String(r.state||r.status||''))}</span></span><small>${esc(r.quadrant||r.name||'')}</small><span title="graphs grown, every seed of every law bought into a rung times the chains a seed grows (the fleet ladder's graphs), and how many of them are done">${laws} · ${graphs}${deep}</span><small>running ${fmt(running)} · analysing ${fmt(analysing)} · queued ${fmt(queued)}${left}${verdict}</small></button>`}
function drawCard(rows){const id0=String(rows[0].campaign_id),label=(rows[0].draw||{}).label||rows[0].name||'';let held=0,budget=0,created=0,done=0,running=0,analysing=0,queued=0,left=0,pace=0,deep=0,live=false,waiting=0,expected=0;
  for(const r of rows){const b=r.law_budget||{},k=+r.chains_per_seed||1;waiting+=lawsWaitingOf(r);held+=+(b.laws_held??r.laws_total)||0;budget+=+b.law_budget||0;done+=(+(r.graphs_finished??r.graphs_total)||0)*k;created+=(+(r.graphs_bought??r.graphs_created??r.graphs_total)||0)*k;running+=+r.slots_held||0;analysing+=+r.analyses_running||0;queued+=+r.work_queued||0;const w=r.work_left||{};if(+w.core_hours_left>0){left+=+w.core_hours_left;expected+=Math.max(+w.core_hours_left,+w.core_hours_expected||0);if(+w.hours_at_last_hours_pace>0)pace+=+w.core_hours_left/+w.hours_at_last_hours_pace}deep=Math.max(deep,+r.deepest_n||0);live=live||(+r.slots_held||0)+(+r.analyses_running||0)>0}
  const states=[...new Set(rows.map(r=>String(r.state||r.status||'')))],state=states.length===1?states[0]:(states.includes('active')?'active':states.join(' / '));
  const laws=`<span title="${esc(LAWS_WAITING_TIP)}">${cardLawsText(held,budget,waiting)}</span>`,graphs=created>done?`${fmt(created)} graphs, ${fmt(done)} done`:`${fmt(created)} graphs`;
  const unpriced=rows.flatMap(r=>(r.work_left||{}).unpriced_rungs||[]);
  const rest=left>0?workLeftText(Math.round(left*10)/10,pace>0?left/pace:0,expected,pace>0?expected/pace:0):(queued>0||unpriced.length?notPriced(unpriced):' · nothing left to run');
  const chips=rows.map(r=>{const id=String(r.campaign_id),cur=id===String(campaign);return `<button type=button class="draw-batch${cur?' current':''}" data-campaign="${esc(id)}" title="batch ${esc(String((r.draw||{}).batch||''))} of ${rows.length}: campaign ${esc(id)}; show it in the panels below">${esc(String((r.draw||{}).batch||id))}</button>`}).join('');
  const current=rows.some(r=>String(r.campaign_id)===String(campaign));
  return `<div class="study-card study-draw${current?' current':''}" data-draw="${esc((rows[0].draw||{}).key||id0)}" title="one draw from one design, run in ${rows.length} batches so each batch's report fits in memory; the panels below read one batch, picked here"><span class=study-card-head><b>${esc(label)}</b><span class="study-card-state${live?' live':''}">${esc(state)}</span></span><small>${esc(rows[0].quadrant||'')} · one draw in ${rows.length} batches</small><span>${laws} · ${graphs}${deep?` · deepest N=${fmt(deep)}`:''}</span><small>running ${fmt(running)} · analysing ${fmt(analysing)} · queued ${fmt(queued)}${rest}</small><span class=draw-batches>batch ${chips}</span></div>`}
function renderStudyNow(d){const root=document.getElementById('studyNow');if(!root||!d)return;registerLiveRegion(root);if(deferrableRedraw(root,()=>renderStudyNow(d)))return;const rows=(d.campaigns||[]).filter(r=>!r.archived).sort((a,b)=>NATSORT.compare(String(a.campaign_id),String(b.campaign_id)));
  const groups=new Map();for(const r of rows){const key=(r.draw&&r.draw.key)||null;if(key){if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r)}}
  const drawn=new Set();const cards=[];for(const r of rows){const key=(r.draw&&r.draw.key)||null;if(key&&groups.get(key).length>1){if(drawn.has(key))continue;drawn.add(key);cards.push(drawCard(groups.get(key)))}else cards.push(studyCard(r))}
  const batches=rows.filter(r=>r.study_batch);if(batches.length>1)cards.unshift(allCard(batches));
  root.innerHTML=cards.length?cards.join(''):'<div class=empty>no campaign in this study yet</div>'}
function lawsWaitingOf(r){return +((r.laws_by_state||{}).PROPOSED)||0}
function cardLawsText(held,budget,waiting){return `${fmt(held)}${budget?` of ${fmt(budget)}`:''} laws drawn`+(waiting?`, ${fmt(waiting)} waiting to start`:'')}
const LAWS_WAITING_TIP='laws drawn counts every law drawn into the batches, those still waiting in the proposer\u2019s pool among them (32 a batch at most); the fleet ladder counts a law from the size where its seeds run, so its first rung shows the drawn laws less the waiting ones. The graph count here is read by a slower scan than the ladder\u2019s, so while the fleet runs it trails the ladder a little';
function allCard(rows){const cur=String(campaign)==='study';let held=0,budget=0,created=0,done=0,running=0,analysing=0,deep=0,waiting=0;
  for(const r of rows){const b=r.law_budget||{},k=+r.chains_per_seed||1;waiting+=lawsWaitingOf(r);held+=+(b.laws_held??r.laws_total)||0;budget+=+b.law_budget||0;done+=(+(r.graphs_finished??r.graphs_total)||0)*k;created+=(+(r.graphs_bought??r.graphs_created??r.graphs_total)||0)*k;running+=+r.slots_held||0;analysing+=+r.analyses_running||0;deep=Math.max(deep,+r.deepest_n||0)}
  const ids=rows.map(r=>`C${esc(String(r.campaign_id))}`).join(', '),graphs=created>done?`${fmt(created)} graphs, ${fmt(done)} done`:`${fmt(created)} graphs`;
  return `<button type=button class="study-card study-all${cur?' current':''}" data-campaign="study" title="${cur?'the panels below read every batch together':'show every batch together in the panels below'}"><span class=study-card-head><b>All batches</b><span class="study-card-state${running+analysing>0?' live':''}">${rows.length} batches</span></span><small>${ids}</small><span title="${esc(LAWS_WAITING_TIP)}">${cardLawsText(held,budget,waiting)} · ${graphs}${deep?` · deepest N=${fmt(deep)}`:''}</span><small>running ${fmt(running)} · analysing ${fmt(analysing)}</small></button>`}
const KIND_NAMES={grown:'settled from empty or random',small_world:'small world',made:'made',ring:'ring or chain made',empty:'empty',full:'full',frozen:'frozen lattice',still:'still lattice',rewired:'rewired lattice',moved:'melted lattice',broken:'broken',apart:'apart',unread:'nothing read'};
const KIND_ORDER=Object.keys(KIND_NAMES),NOT_READ='not read yet';
let homeFilter={off:new Set(),kind:'',group:'',batch:'',region:'',settled:''};
function kindOf(p){return (p&&p.kind)||NOT_READ}
function regionOf(p){return p&&p.region?p.region.state:'new'}
function batchOf(p){return String(p&&(p.batch??p.campaign_id)!=null?(p.batch??p.campaign_id):'')}
function homeFilterActive(){const f=homeFilter;return !!(f.off.size||f.kind||f.group||f.batch||f.region||f.settled)}
function homeFilterPasses(p){const f=homeFilter,k=kindOf(p);
  if(f.kind){if(k!==f.kind)return false}else if(f.off.has(k))return false;
  if(f.group&&String(p&&p.group||'')!==f.group)return false;
  if(f.batch&&batchOf(p)!==f.batch)return false;
  if(f.region&&regionOf(p)!==f.region)return false;
  const settled=settledOf(p).length>0;if(f.settled==='settled'&&!settled)return false;if(f.settled==='unsettled'&&settled)return false;
  return true}
function lawNumber(text){const m=/(\d+)\s*$/.exec(String(text??''));return m?+m[1]:Infinity}
function lawOrder(a,b){const scoreOf=p=>+((p.law_score||{}).score||0),c=p=>/^\d+$/.test(String(p.campaign_id??''))?+p.campaign_id:Infinity;
  return scoreOf(b)-scoreOf(a)||c(a)-c(b)||lawNumber(a.ensemble_code)-lawNumber(b.ensemble_code)||String(a.candidate_id).localeCompare(String(b.candidate_id))}
function filteredTop(){const base=shownLandscape()?.top_candidates||[];if(!homeFilterActive()){const scored=base.filter(p=>+((p.law_score||{}).score||0)>0).sort(lawOrder);return [...scored,...base.filter(p=>!(+((p.law_score||{}).score||0)>0))].slice(0,100)}
  const seen=new Map();for(const p of [...base,...landChainPoints()])if(p&&p.candidate_id&&!seen.has(String(p.campaign_id??'')+'|'+p.candidate_id))seen.set(String(p.campaign_id??'')+'|'+p.candidate_id,p);
  return [...seen.values()].filter(homeFilterPasses).sort(lawOrder).slice(0,100)}
function filterOptions(points){const kinds=new Map(),groups=new Set(),batches=new Set();
  for(const p of points||[]){kinds.set(kindOf(p),(kinds.get(kindOf(p))||0)+1);if(p.group)groups.add(String(p.group));const b=batchOf(p);if(b)batches.add(b)}
  const order=[...KIND_ORDER,NOT_READ].filter(k=>kinds.has(k)).concat([...kinds.keys()].filter(k=>!KIND_ORDER.includes(k)&&k!==NOT_READ));
  return {kinds:order.map(k=>[k,kinds.get(k)]),groups:[...groups].sort(),batches:[...batches].sort((a,b)=>(+a||0)-(+b||0)||a.localeCompare(b))}}
function renderFilters(points){const host=document.getElementById('homeFilters');if(!host)return;
  const focused=document.activeElement;if(focused&&focused.tagName==='SELECT'&&String(focused.id||'').startsWith('filter'))return;
  if(!points||!points.length){host.innerHTML='<div class="empty">the filters arrive with the landscape</div>';return}
  const o=filterOptions(points),f=homeFilter,kept=points.filter(homeFilterPasses).length;
  const name=k=>KIND_NAMES[k]||k,opt=(v,label,cur)=>`<option value="${esc(v)}"${String(cur)===String(v)?' selected':''}>${esc(label)}</option>`;
  const pills=o.kinds.map(([k,n])=>`<label class="kind-pill${f.off.has(k)?' off':''}" title="${f.off.has(k)?'hidden: click to show':'shown: click to hide'} the laws whose kind is ${esc(name(k))}"><input type=checkbox data-filter-kind="${esc(k)}"${f.off.has(k)?'':' checked'}>${esc(name(k))} ${esc(n)}</label>`).join('');
  host.innerHTML=`<div class=filter-row>${pills}</div>
  <div class=filter-row><label>one kind <select id=filterKind><option value="">every kind ticked above</option>${o.kinds.map(([k])=>opt(k,name(k),f.kind)).join('')}</select></label>
  <label title="known: a region the map has marked known; mapping: a region the map is still reading; new: in no region yet">map <select id=filterRegion>${opt('','every law',f.region)}${opt('new','not in a region yet',f.region)}${opt('mapping','in a region being mapped',f.region)}${opt('known','in a known region',f.region)}</select></label>
  <label title="A: the blind draw; B: the map of the best">group <select id=filterGroup>${opt('','every group',f.group)}${o.groups.map(g=>opt(g,g==='A'?'A, blind':g==='B'?'B, map':g,f.group)).join('')}</select></label>
  <label>batch <select id=filterBatch>${opt('','every batch',f.batch)}${o.batches.map(b=>opt(b,'C'+b,f.batch)).join('')}</select></label>
  <label title="settled: at least one probe settled under the score">settled <select id=filterSettled>${opt('','settled or not',f.settled)}${opt('settled','settled',f.settled)}${opt('unsettled','not settled',f.settled)}</select></label>
  <button type=button class=gsd-control id=filterClear${homeFilterActive()?'':' disabled'}>clear</button><span class=muted id=filterCount>${esc(kept.toLocaleString())} of ${esc(points.length.toLocaleString())} laws shown</span></div>`}
function chooseFilter(ev){const t=ev.target;if(!t)return;const f=homeFilter;
  if(t.dataset&&t.dataset.filterKind!=null){const k=t.dataset.filterKind;if(t.checked)f.off.delete(k);else f.off.add(k)}
  else if(t.id==='filterKind')f.kind=t.value;else if(t.id==='filterRegion')f.region=t.value;else if(t.id==='filterGroup')f.group=t.value;
  else if(t.id==='filterBatch')f.batch=t.value;else if(t.id==='filterSettled')f.settled=t.value;else return;
  if(t.blur)t.blur();landMetaKey=null;if(last)renderHome(last)}
function clearFilters(){homeFilter={off:new Set(),kind:'',group:'',batch:'',region:'',settled:''};landMetaKey=null;if(last)renderHome(last)}
function filteredDepths(){if(!homeFilterActive())return null;const by={};for(const p of landChainPoints().filter(homeFilterPasses)){const n=+((p.law_score||{}).top_n||0);if(n)by[n]=(by[n]||0)+1}return by}
function renderHome(d){last=d;markHomeLoading();renderLive(d);renderTop();rungLadderRow();renderGatesBox();refreshStudyNow();const use=landscape&&String(landscape.campaign_id)===String(campaign),pts=use?landChainPoints():[];if(use){const c=landChainCounts(),e=landscape.exposure||{},model=landscape.score_model||{},parts=model.components||{};channelCounts={d_s:c.d_s_estimates,d_V:c.d_V_estimates,d_B:c.d_B_estimates,d_w:c.d_w_estimates};
const metaHtml=`<span>${fmt(c.measured_candidates)} measured candidates</span><span title="laws with no dimension estimate on any probe. Open the Explorer and filter Estimates to \u2018refused\u2019 to list them.">${fmt(c.refused_candidates)} refused</span><span title="laws whose measurement landed outside a declared limit: at or above the mean-degree cap, or out of seed budget. A standing property of the measurements, true of history the moment it can be read \u2014 not a count of filter actions.">${fmt(c.limit_hit_candidates)} at a limit</span><span class="${(c.band_candidates?.contracting||0)+(c.band_candidates?.tier2||0)+(c.band_candidates?.tier3||0)+(c.band_candidates?.tier4||0)+(c.band_candidates?.einstein||0)?'good':''}" title="Laws in each band, by how many of the four probes settled under the score (784: between two sizes from N=4,096, on a piece of 4,096 nodes or more): 1 probe, 2, 3 and 4, as the chart's bands are labelled, and the 5th band, all four settled and the Einstein relation d_s = 2 d_f / d_w held at two sizes. More than one settled is a stronger claim than one: two channels that fail differently agreeing is the cheapest available check on a single probe's false positives; build 274 measured 78 of 104 CONVERGED blocks as probes still drifting. Zero is the expected reading on a young campaign and is a finding, not a fault.">${fmt(c.band_candidates?.contracting||0)} at 1 probe \u00b7 ${fmt(c.band_candidates?.tier2||0)} at 2 \u00b7 ${fmt(c.band_candidates?.tier3||0)} at 3 \u00b7 ${fmt(c.band_candidates?.tier4||0)} at 4 \u00b7 ${fmt(c.band_candidates?.einstein||0)} by Einstein</span>${landChainPicker()}<span title="cartography revision ${esc(landscape.revision||'current')} \u00b7 changes when the landscape is recomputed">${fmt(e.opportunities)} proposal opportunities</span>`;const metaKey=`${campaign}|${landscape.revision||''}|${landscape.generated_utc||''}|${landLattices}`;if(metaKey!==landMetaKey){document.getElementById('landMeta').innerHTML=metaHtml;landMetaKey=metaKey}renderFilters(pts);if(currentPage==='home'){drawLandscape(pts.filter(homeFilterPasses))}}else{document.getElementById('landMeta').innerHTML='<span>complete landscape warming independently; operational UI remains live</span>';landMetaKey=null}}
let homeLoading=null;
let landLattices=false;
function landPointKey(p){return `${p.campaign_id||''}|${p.candidate_id}`}
function latticeWho(){return new Set(((typeof landscape!=='undefined'&&landscape)||{}).lattice_who||[])}
function landChainPoints(){const base=(landscape&&landscape.dimension_points)||[];if(!landLattices)return base;const every=(landscape||{}).every_chain||{},by=new Map(base.map(p=>[landPointKey(p),p])),who=latticeWho();for(const [name,pts] of Object.entries(every.points||{}))for(const p of pts||[]){const s=p.law_score||{};if(who.has(s.by)&&s.chain===name)by.set(landPointKey(p),p)}return [...by.values()].map(p=>Object.assign({},p,p.landscape_band_with_lattices?{landscape_band:p.landscape_band_with_lattices}:{},Array.isArray(p.settled_probes_with_lattices)?{settled_probes:p.settled_probes_with_lattices}:{}))}
function landChainCounts(){const c=(landscape&&landscape.counts)||{};if(!landLattices)return c;const pts=landChainPoints(),bands={};for(const p of pts)bands[bandOf(p)]=(bands[bandOf(p)]||0)+1;return {...c,measured_candidates:pts.length,band_candidates:bands}}
function landChainPicker(){return `<label class=land-lattices title="Off: each law is banded by its twin starts alone, the chain from empty and the random start (the score counts them 1). On: by its best start, a lattice start that changed (0.6) or kept its shape (0.3) among them, drawn at that start’s own readings. A band is the score’s: how many of the four probes settled between two sizes from N=4,096 on a piece of 4,096 nodes or more, and the 5th when the Einstein relation held at two sizes too."><input type=checkbox id=landLattices${landLattices?' checked':''}> include lattice starts</label>`}
function chooseLandLattices(on){landLattices=!!on;landMetaKey=null;if(last)renderHome(last)}
function markHomeLoading(){const home=document.getElementById('gsdHome');if(!home)return;
  const pending=!!homeLoading&&(!homeLoading.overview||!(landscape&&String(landscape.campaign_id)===String(campaign)));
  if(!pending)homeLoading=null;home.classList.toggle('is-loading',pending);let note=document.getElementById('homeLoadingNote');
  if(pending){if(!note){note=document.createElement('div');note.id='homeLoadingNote';note.className='loading-note';home.prepend(note)}
    const failed=landscapeFailure&&landscapeFailure.campaign===String(campaign)?landscapeFailure.error:null;
    note.innerHTML=`<span class=spinner></span> loading campaign ${esc(homeLoading.campaign)}: ${failed?`its landscape could not be built (${esc(failed)}); asking again, less often`:homeLoading.overview?`its overview is here, its landscape is on its way${landWaiting&&landWaiting.campaign===String(campaign)&&landWaiting.of>1?` (${fmt(landWaiting.read)} of ${fmt(landWaiting.of)} batches read)`:''}`:'asking for its overview and landscape'}; what is dimmed below is still the campaign before`}
  else if(note)note.remove()}
let landWaiting=null;let landTimer=null;function scheduleLandscape(delay){clearTimeout(landTimer);landTimer=setTimeout(pollLandscape,delay)}
async function pollLandscape(){landTimer=null;if(!campaign||landBusy){scheduleLandscape(4000);return}landBusy=true;const asked=campaign;let delay=4000 ;try{const meta=await get('/api/landscape/'+encodeURIComponent(campaign)+'?meta=1');if(!meta.pending){landPending={campaign:null,polls:0};landscapeFailure=null}if(meta.pending){ if(landPending.campaign!==String(asked))landPending={campaign:String(asked),polls:0};landPending.polls++;landscapeFailure=meta.last_refresh_error?{campaign:String(asked),error:String(meta.last_refresh_error)}:null;landWaiting=Array.isArray(meta.batches)&&Array.isArray(meta.waiting_for)?{campaign:String(asked),read:meta.batches.length-meta.waiting_for.length,of:meta.batches.length}:null;const base=Math.max(250,Number(meta.retry_after_ms||500));delay=landscapeFailure?Math.min(30000,1000*2**Math.min(5,landPending.polls)):Math.min(4000,base*2**Math.min(4,landPending.polls-1));markHomeLoading()}else if(meta.revision&&meta.revision!==landscapeRevision){const body=await get('/api/landscape/'+encodeURIComponent(campaign));if(String(asked)!==String(campaign)){delay=250}else if(!body.pending&&Array.isArray(body.dimension_points)){landscape=body;landscapeRevision=body.revision||meta.revision;if(last)renderHome(last);if(currentPage==='explorer'&&explorerLoaded)drawExplorer()}else delay=4000}}catch(e){console.warn('landscape refresh',e);delay=4000}finally{landBusy=false;scheduleLandscape(delay)}}
function humanize(value){return String(value||'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase())}
function setSelectOptions(id,values,allLabel){const el=document.getElementById(id);if(!el)return;const keep=el.value;el.innerHTML=`<option value="">${esc(allLabel)}</option>`+(values||[]).map(v=>`<option value="${esc(v)}">${esc(humanize(v))}</option>`).join('');if([...el.options].some(o=>o.value===keep))el.value=keep}
function renderExplorerFilters(){const f=explorerMeta.filter_options||{},ops=f.operators||[...new Set(explorerRows.flatMap(x=>(x.terms||[]).map(t=>t.op).filter(Boolean)))].sort();setSelectOptions('explorerState',f.states||[...new Set(explorerRows.map(x=>x.state).filter(Boolean))].sort(),'all states');setSelectOptions('explorerCoupling',f.coupling_strata||['weak','moderate','strong','extreme'],'all coupling strengths');setSelectOptions('explorerScaling',f.scaling_profiles||['unscaled','mixed','scaled'],'all scaling profiles');setSelectOptions('explorerCoeffScale',f.coefficient_scales||['one','log_N','inv_log_N','inv_N','inv_sqrt_N','power'],'all coefficient scales');setSelectOptions('explorerMinN',(f.rungs||[]).map(String),'any measured / scheduled N');const root=document.getElementById('explorerTerms');if(root)root.innerHTML=ops.map(op=>`<button type="button" class="filter-pill${explorerSelectedTerms.has(op)?' active':''}" data-op="${esc(op)}" title="Filter for Hamiltonians containing ${esc(op)}">${esc(TERMS.label?TERMS.label(op):humanize(op))}</button>`).join('')||'<span class=muted>no term vocabulary available</span>'}
function explorerFilteredRows(){const q=(document.getElementById('explorerQ')?.value||'').trim().toLowerCase(),group=document.getElementById('explorerGroup')?.value||'',state=document.getElementById('explorerState')?.value||'',coupling=document.getElementById('explorerCoupling')?.value||'',scaling=document.getElementById('explorerScaling')?.value||'',coeffScale=document.getElementById('explorerCoeffScale')?.value||'',minN=Number(document.getElementById('explorerMinN')?.value||0),estimate=document.getElementById('explorerEstimate')?.value||'',sample=document.getElementById('explorerSample')?.value||'',termMode=document.getElementById('explorerTermMode')?.value||'all',selected=[...explorerSelectedTerms];const code=lawCodeQuery(q);return explorerRows.filter(x=>{if(code){if((code.campaign!=null&&String(code.campaign)!==String(x.campaign_id??campaign))||(code.ordinal!=null&&graphOrdinal(x)!==code.ordinal))return false}else if(q&&!JSON.stringify(x).toLowerCase().includes(q))return false;if(group&&String(x.status_group||'')!==group)return false;if(state&&String(x.state||'')!==state)return false;if(coupling&&String(x.coupling_stratum||'')!==coupling)return false;if(scaling&&String(x.scaling_profile||'')!==scaling)return false;if(coeffScale&&!(x.coefficient_scales||[]).includes(coeffScale))return false;if(minN&&Number(x.largest_n||0)<minN)return false;if(estimate==='refused'&&!((x.rungs||[]).length&&!(x.probes_valid||0)))return false;if(estimate==='limit'&&!(x.limit_hits||[]).length)return false;if(estimate==='measured'&&!(x.probes_valid||0))return false;if(sample==='unfiltered'&&!x.unfiltered)return false;if(sample==='filtered'&&x.unfiltered)return false;if(selected.length){const ops=new Set(x.term_operators||(x.terms||[]).map(t=>t.op));const ok=termMode==='any'?selected.some(op=>ops.has(op)):selected.every(op=>ops.has(op));if(!ok)return false}return true})}
const explorerPointIndex=(()=>{let rev=null,map=new Map();return()=>{const live=landscape&&String(landscape.campaign_id)===String(campaign),r=live?(landscape.revision||'current'):null;if(r!==rev){rev=r;map=new Map();if(live)for(const pt of (landscape.dimension_points||[]))map.set(String(pt.candidate_id),pt)}return map}})();
function explorerPoint(x){if(x.campaign_id!=null&&String(campaign)!=='study'&&String(x.campaign_id)!==String(campaign))return null;return explorerPointIndex().get(String(x.candidate_id))||null}
function explorerScore(x){const pt=explorerPoint(x);const s=pt&&lawScoreOf(pt);return (!s||lawScoreBelow(pt))?null:Number(s.score)}
function explorerScoreCell(x){if(x.campaign_id!=null&&String(campaign)!=='study'&&String(x.campaign_id)!==String(campaign))return `<span class=muted title="a score is read from the landscape of the campaign the page shows; choose campaign ${esc(String(x.campaign_id))} in the header, or open the law, for this one's">\u2014</span>`;const pt=explorerPoint(x);if(!pt)return '<span class=muted title="no landscape row for this law yet: it has no measured rung, or the landscape has not caught up">\u2014</span>';const v=explorerScore(x);if(v===null)return `<span class=muted title="${lawScoreBelow(pt)?'scored from N=16,384 nodes, the first size a probe can settle at, which this law has not reached':'the controller has not read this law yet'}">${lawScoreBelow(pt)?'below 16,384':'not yet'}</span>`;return `<b class="${v>0?'good':'muted'}" title="${esc(scoreTitle(pt))}">${v}</b>${v>0?`<small>${esc(lawScoreText(pt))}</small>`:''}`}
const EXPLORER_COLS=[
 {key:'candidate',label:'candidate',width:'26%',num:true,dir:1,get:x=>graphOrdinal(x),
  title:'sort by G-code. Laws that have not run have no G-code and sort last in both directions.',
  cell:x=>`<a class=candidate-link href="${candidateHref(x.candidate_id,x.campaign_id)}" title="${candidateTitle(x)}">${identityHtml(x)}</a>${lawHashesHtml(x)}${x.lineage_parent?`<small>parent <a class=candidate-link href="${candidateHref(x.lineage_parent,x.campaign_id)}">${esc(String(x.lineage_parent).slice(0,10))}</a></small>`:''}`},
 {key:'law',label:'law',width:'22%',get:x=>String(x.law||''),
  cell:x=>`${x.terms?.length?TERMS.html(x.terms,{compact:true}):`<span>${esc(x.law||'\u2014')}</span>`}<small class=explorer-law-text>${esc(x.law||'')}</small>`},
 {key:'score',label:'score',width:'8%',num:true,dir:-1,cls:'num',
  title:'the score from the landscape, 0 to 100: who built a space times how far it held (608). Blank when the landscape has no row for the law.',
  get:x=>explorerScore(x),cell:explorerScoreCell},
 {key:'state',label:'state',width:'14%',get:x=>String(x.state||''),
  cell:x=>`<b>${esc(x.state||'\u2014')}</b><small>${esc(x.status_group||'')}</small>${x.state_reason?`<small title="${esc(x.state_reason)}">${esc(x.state_reason)}</small>`:''}`},
 {key:'coupling',label:'coupling',width:'8%',get:x=>String(x.coupling_stratum||''),
  cell:x=>esc(humanize(x.coupling_stratum||'\u2014'))},
 {key:'scaling',label:'scaling',width:'9%',get:x=>String(x.scaling_profile||''),
  cell:x=>`${esc(humanize(x.scaling_profile||'\u2014'))}<small>${esc((x.coefficient_scales||[]).map(humanize).join(', '))}</small>`},
 {key:'largest_n',label:'largest N',width:'6%',num:true,dir:-1,cls:'num',
  get:x=>(x.largest_n===null||x.largest_n===undefined||x.largest_n===''?null:Number(x.largest_n)),
  cell:x=>esc(x.largest_n||'\u2014')},
 {key:'created',label:'created',width:'7%',dir:-1,get:x=>String(x.created_utc||''),
  cell:x=>localTimeHtml(x.created_utc)}];
const EXPLORER_COL=Object.fromEntries(EXPLORER_COLS.map(c=>[c.key,c]));
const NATSORT=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});
const TIE=(a,b)=>NATSORT.compare(candidateLabel(a),candidateLabel(b));
function explorerSorted(rows){const col=EXPLORER_COL[explorerSort.key]||EXPLORER_COL.created,dir=explorerSort.dir;
 return rows.map((x,i)=>[col.get(x),i,x]).sort((a,b)=>{const [p,i,,]=a,[q,j]=b;const pn=p===null||p===undefined||p==='',qn=q===null||q===undefined||q==='';if(pn!==qn)return pn?1:-1;if(pn)return i-j;const c=col.num?(Number(p)-Number(q)):NATSORT.compare(String(p),String(q));return c?c*dir:TIE(a[2],b[2])||(i-j)}).map(r=>r[2])}
const EXPLORER_ROW_CAP=1000;
const EXPLORER_TYPING_DELAY_MS=500;
let explorerTypingTimer=null;
function drawExplorerSoon(){
  if(explorerTypingTimer)clearTimeout(explorerTypingTimer);
  explorerTypingTimer=setTimeout(()=>{explorerTypingTimer=null;drawExplorer()},EXPLORER_TYPING_DELAY_MS);
}
function drawExplorer(){const root=document.getElementById('explorerBody');if(!root)return;const filtered=explorerFilteredRows(),shown=explorerSorted(filtered).slice(0,EXPLORER_ROW_CAP),status=document.getElementById('explorerFilterSummary');const code=lawCodeQuery((document.getElementById('explorerQ')?.value||''));const study=explorerStudy(),camps=study?new Set(explorerRows.map(x=>String(x.campaign_id??campaign))).size:1;if(status)status.textContent=`showing ${shown.length.toLocaleString()} of ${explorerRows.length.toLocaleString()} candidates${study?` of ${camps} campaign${camps===1?'':'s'}`:''}${filtered.length>shown.length?` \u00b7 first ${EXPLORER_ROW_CAP.toLocaleString()} by this sort`:''}${code&&code.campaign!=null&&!study&&String(code.campaign)!==String(campaign)?` \u00b7 C${code.campaign}${code.ordinal!=null?`-G${code.ordinal} is a law`:' holds the laws'} of campaign ${code.campaign}: choose every campaign in the scope above, or campaign ${code.campaign}'s card in The study now on Home, to find ${code.ordinal!=null?'it':'them'}`:''}`;if(!shown.length){root.innerHTML='<div class=empty>no candidates match these filters</div>';return}
 const head=EXPLORER_COLS.map(c=>{const on=explorerSort.key===c.key,arrow=on?(explorerSort.dir>0?'\u25b2':'\u25bc'):'';return `<th style="width:${c.width}" class="sortable${on?' sorted':''}${c.cls?' '+c.cls:''}" data-sort="${c.key}" title="${esc(c.title||('sort by '+c.label))}" aria-sort="${on?(explorerSort.dir>0?'ascending':'descending'):'none'}"><button type=button class=sort-head>${esc(c.label)}<span class=sort-arrow>${arrow}</span></button></th>`}).join('');
 root.innerHTML=`<table class="explorer-table"><thead><tr>${head}</tr></thead><tbody>${shown.map(x=>`<tr>${EXPLORER_COLS.map(c=>`<td${c.cls?` class="${c.cls}"`:''}>${c.cell(x)}</td>`).join('')}</tr>`).join('')}</tbody></table>`}
function explorerSortBy(key){if(!EXPLORER_COL[key])return;if(explorerSort.key===key)explorerSort.dir=-explorerSort.dir;else explorerSort={key,dir:EXPLORER_COL[key].dir||1}; drawExplorer()}
function explorerStudy(){return (document.getElementById('explorerScope')?.value||'')==='study'||String(campaign)==='study'}
function mergeFilterOptions(metas){const out={};for(const m of metas)for(const [k,v] of Object.entries((m&&m.filter_options)||{}))if(Array.isArray(v))out[k]=[...new Set([...(out[k]||[]),...v])];if(out.rungs)out.rungs.sort((a,b)=>+a-+b);return out}
let explorerLoadSeq=0;
class ExplorerLoadSuperseded extends Error{}
async function loadExplorerIndex(id,status,label,seq){let d;for(;;){if(seq!==explorerLoadSeq)throw new ExplorerLoadSuperseded('superseded');d=await get('/api/overview/'+encodeURIComponent(id)+'?exploration=1');const r=d.dashboard_response||{};if(!r.heavy_pending)break;if(r.last_refresh_error&&!r.refreshing)throw new Error(`the ${label}candidate index could not be built: ${r.last_refresh_error}`);if(status&&seq===explorerLoadSeq)status.textContent=`building ${label}candidate index…`;await new Promise(res=>setTimeout(res,400))}if(seq!==explorerLoadSeq)throw new ExplorerLoadSuperseded('superseded');return d.exploration_map||{}}
async function loadExplorer(force=false){const status=document.getElementById('explorerStatus');if(!campaign){if(status)status.textContent='waiting for campaign…';return}if(explorerLoaded&&!force)return;const study=explorerStudy(),asked=campaign,seq=++explorerLoadSeq;if(status)status.textContent='loading complete candidate index…';try{let meta,rows;if(!study){meta=await loadExplorerIndex(campaign,status,'',seq);rows=meta.nodes||[]}else{const ids=[...(String(campaign)==='study'?[]:[String(campaign)]),...liveCampaignRows().map(r=>String(r.campaign_id)).filter(id=>id!==String(campaign))],metas=[];rows=[];for(const [i,id] of ids.entries()){if(status)status.textContent=`loading campaign ${id}, ${i+1} of ${ids.length}…`;const one=await loadExplorerIndex(id,status,`campaign ${id}'s `,seq);metas.push(one);for(const node of one.nodes||[])rows.push(node.campaign_id==null?Object.assign(node,{campaign_id:id}):node)}meta={...(metas[0]||{}),filter_options:mergeFilterOptions(metas)}}if(seq!==explorerLoadSeq||asked!==campaign||study!==explorerStudy())return;explorerMeta=meta;explorerRows=rows;explorerLoaded=true;renderExplorerFilters();if(status)status.textContent=`${explorerRows.length.toLocaleString()} candidates loaded${study?' from every campaign of the study':''}`;drawExplorer()}catch(e){if(e instanceof ExplorerLoadSuperseded||seq!==explorerLoadSeq)return;explorerLoaded=false;if(status)status.textContent=String(e)}}
function clearExplorerFilters(){explorerSelectedTerms.clear();for(const id of ['explorerQ','explorerGroup','explorerState','explorerEstimate','explorerSample','explorerCoupling','explorerScaling','explorerCoeffScale','explorerMinN','explorerTermMode']){const el=document.getElementById(id);if(!el)continue;el.value=id==='explorerTermMode'?'all':''}renderExplorerFilters();drawExplorer()}
function bytes(n){if(n===null||n===undefined||n===''||!Number.isFinite(+n))return'—';const u=['B','KiB','MiB','GiB'];let v=+n,i=0;while(v>=1024&&i<u.length-1){v/=1024;i++}return`${v.toFixed(i?1:0)} ${u[i]}`}
function renderReports(s){
  if(!s)return;
  const reportsRoot=document.getElementById('gsdReports');
  if(reportsRoot){registerLiveRegion(reportsRoot);if(deferrableRedraw(reportsRoot,()=>renderReports(s)))return;}
  const m=s.manifest||{},p=m.analysis_phase||{},diag=p.diagnostics||{},dag=diag.dag||m.report_dag||{};
  reportStatus=s;reportAdmin=!!((s.access||{}).local_admin);
  const cstate=(m.cycle_state||{complete:'COMPLETE',complete_with_errors:'PARTIAL',error:'FAILED'}[m.generation_status]||'').toUpperCase();
  const inFlight=['requested','running','generating'].includes(String(p.state||'').toLowerCase());
  const cycle=inFlight?(diag.cycle||m.cycle||{}):(m.cycle||{}),pre=inFlight?(diag.preprocessing||{}):{};
  const badge=document.getElementById('reportsBadge');if(badge){const shown=inFlight?'RUNNING':cstate;const cls=inFlight?'idle':(cstate==='COMPLETE'?'ok':(cstate==='PARTIAL'?'warn':(cstate==='FAILED'?'bad':'idle')));const secs=(m.cycle_seconds??cycle.total_seconds);badge.className='report-badge '+cls;badge.textContent=inFlight?`… RUNNING${m.bundle_revision?' · last good revision '+m.bundle_revision:''}`:(shown?`${shown==='COMPLETE'?'✓':(shown==='PARTIAL'?'!':'✗')} ${shown}${m.bundle_revision?' · revision '+m.bundle_revision:''}${secs==null?'':' · '+Number(secs).toFixed(1)+'s'}`:(p.state||'idle'));}
  const failure=document.getElementById('reportFailure');if(failure){const cycleErr=cstate==='COMPLETE'?'':(p.error||m.service_error||''),err=reportTriggerError||cycleErr;const retrying=inFlight&&!!cycleErr&&!reportTriggerError;const failed=(m.failed_reports||[]).map(code=>REPORT_BY_CODE[code]?.number||code);const title=reportTriggerError?'manual report trigger failed':(retrying?'previous cycle failed · a new cycle is running':`current report-cycle error · ${cstate||'FAILED'}`);failure.innerHTML=err?`<div class="report-error-box${retrying?' retrying':''}"><b>${esc(title)}</b>${failed.length&&!reportTriggerError?`<div>failed reports: <b>${esc(failed.join(', '))}</b></div>`:''}<pre>${esc(err)}</pre>${reportTriggerError?'<div class=muted>The control remains disabled unless the API confirms the current admin capability. Refresh or reopen the current runtime admin URL if this token is stale.</div>':(retrying?`<div class=muted>This error is from the previous cycle (${esc(m.failed_cycle_id||m.cycle_id||'—')}). A new cycle is in progress; it will clear if that cycle succeeds. Last-good report bodies remain available.</div>`:`<div class=muted>Failure stage: ${esc(p.stage||diag.stage||'unknown')} · request ${esc(p.request_id||diag.request_id||'—')}. Last-good report bodies remain available.</div>`)}</div>`:'';}
  const resolved=document.getElementById('reportResolved');if(resolved){const hist=m.resolved_errors||[];resolved.innerHTML=hist.length?`<details class=resolved-errors><summary>Resolved failures (${hist.length})</summary>${hist.slice().reverse().map(h=>`<div class=resolved-row><pre>${esc(h.error||'')}</pre><div class=muted>resolved by cycle ${esc(h.resolved_by_cycle_id||'—')} at ${localTimeHtml(h.resolved_utc)}</div></div>`).join('')}</details>`:'';}
  const bundle=document.getElementById('reportBundle');if(bundle){bundle.innerHTML='';bundle.hidden=true}
  renderStudyBundles();
  const storage=(pre.snapshot||{}).storage||{};
  const total=cycle.total_seconds,cycleEl=document.getElementById('reportCycle');if(cycleEl){
    const pool=cycle.report_pool||{},parts=(cycle.snapshot_parts||[]).slice().sort((a,b)=>(+b.json_bytes||0)-(+a.json_bytes||0)).slice(0,3);
    const transported=Number(cycle.snapshot_compressed_bytes)>0,finished=m.generation_finished_utc||cycle.finished_utc;
    cycleEl.innerHTML=`<div>trigger <b>${esc(m.cycle?.trigger_source||p.trigger_source||'—')}</b>${total==null?'':` · total <b>${esc(durationText(total))}</b>`}</div>`
      +`<div>snapshot ${cycle.snapshot_seconds==null?'—':`<b>${esc(durationText(cycle.snapshot_seconds))}</b>`}${snapshotStagesText(cycle)?` <span class=muted>(${esc(snapshotStagesText(cycle))})</span>`:''}</div>`
      +(cycle.snapshot_resident_bytes!=null?`<div>held after it <b>${bytes(cycle.snapshot_resident_bytes)}</b>${cycle.snapshot_peak_bytes!=null?` · worker peak <b>${bytes(cycle.snapshot_peak_bytes)}</b>`:''}</div>`:'')
      +(pool.workers!=null?`<div>report processes <b>${esc(pool.workers)}</b>${pool.why?` <span class=muted>(${esc(pool.why)})</span>`:''}</div>`:'')
      +(parts.length?`<div>largest parts <span class=muted>${parts.map(x=>`${esc(String(x.part||''))} ${bytes(x.json_bytes)}`).join(' · ')}</span></div>`:'')
      +(transported?`<div>transport · ${bytes(cycle.snapshot_compressed_bytes)} compressed · streamed <b>${bytes(cycle.api_bytes_transferred)}</b> · staging ${storage.tmpfs?'RAM-backed tmpfs':esc(storage.source||cycle.snapshot_storage_target||'—')}</div>`:'')
      +`<div>last finish <b>${localTimeHtml(finished)}</b> <span class=muted>${esc(relativeTime(finished))}</span></div>`;}
  const quietActive=QUIET_STAGES.includes((s.quiet_report||{}).stage),busyFleet=!!((s.in_flight||{}).total);
  if(quietActive)quietAskedAt=0;const asked=!!quietAskedAt&&Date.now()-quietAskedAt<QUIET_ASK_WAIT_MS;
  const btn=document.getElementById('reportsManual');if(btn){const active=['requested','running'].includes(p.state);btn.disabled=active||!reportAdmin||quietActive||asked;btn.textContent=asked?'asked: pausing the fleet, please wait…':(active||quietActive)?'working, please wait…':(busyFleet?'pause everything and make the study bundle':'make the study bundle');btn.title=!reportAdmin?'A valid current-runtime admin capability is required.':'One report cycle for every campaign of the folder in turn, then one bundle of all of them with study.json and the gate trees. Running campaigns are paused first with their rungs saved and resumed after.';}
  const quietEl=document.getElementById('reportQuiet');if(quietEl){quietEl.innerHTML=reportQuietHtml(s);const stop=document.getElementById('reportQuietCancel');if(stop)stop.onclick=()=>triggerReports('cancel')}
  updateLiveClocks();
}
async function refreshCalibration(force=false){
  if((!force&&currentPage!=='calibration')||calibBusy)return;
  calibBusy=true;
  try{calibData=await get('/api/calibration');renderCalibration(calibData)}
  catch(e){const host=document.getElementById('calibStatus');if(host)host.innerHTML=`<div class=report-error-box><b>calibration endpoint unavailable</b><pre>${esc(String(e))}</pre></div>`}
  finally{calibBusy=false}
}
function calibNum(v,digits=4){return (v==null||!isFinite(+v))?'—':(+v).toFixed(digits)}
const CALIB_HELP={
  'anchor':'A graph whose dimensions are known exactly by construction. The probes are judged against it.',
  'probe':'The estimator being tested. d_s: spectral (random-walk return) dimension. d_B: box-counting dimension. d_w: walk dimension (how mean-square displacement grows). d_V: volume-growth exponent (how fast the balls grow), which is not a Hausdorff dimension.',
  'measured':'What the probe reported on this graph, averaged over seeds.',
  'theory':'The exact value for this graph. Not fitted: known from construction.',
  'drift':'|measured minus theory|. How far the instrument is from the truth here.',
  'tolerance':'Deliberately loose band for the startup gate; precision belongs to the ladders below.',
  'status':'PASS: drift within tolerance. REFUSED: the probe declined a graph whose answer is known, which is itself a defect.',
  'd_f source':'Which fractal dimension feeds the Einstein relation d_s = 2·d_f/d_w: the exact theory value, or the measured d_B (which inherits box-counting bias).',
  'd_f':'Fractal (mass-scaling) dimension used on this row.',
  '2·d_f/d_w':'The Einstein prediction for d_s from d_f and d_w. Three probes tied into one identity that a broken pipeline does not satisfy by accident.',
  'residual':'|d_s measured minus 2·d_f/d_w|. With theory d_f it tests whether the spectral and walk probes agree with each other; with measured d_B it adds box-counting bias, so the gap between the two rows is d_B\'s bias.',
  'N':'Number of nodes at this rung of the ladder. Campaign rungs are 64, 256, 1024, 4096, 16384 and beyond.',
  'd_s':'Spectral dimension from random-walk return probability. Reads high on high-degree graphs at small N.',
  'd_B':'Box-counting dimension. Under-reads on every family at small N; on fractals it can plateau below theory (a precise wrong answer).',
  'd_w':'Walk dimension: exponent of mean-square displacement versus time. 2 for ordinary diffusion.',
  'd_V':'Volume-growth exponent, B(r) ~ r^d_V, from how the balls grow; not a Hausdorff dimension, which a finite graph does not have. Deterministic per graph, so its seed spread is zero.',
  'required':'The smallest sweep budget whose median ESS clears the certification floor at this N. This is the measured S0 for this Hamiltonian, not a guess.',
  'band':'[first budget where any seed cleared the floor, first budget where every seed cleared it]. The two agree when seeds agree.',
  'sw':'Sweep budget (MCMC sweeps per node) at which this column was measured. Cell: median ESS over seeds [min to max]. A ? marks an unresolved autocorrelation time: chain too short to measure its own correlation, so the ESS flatters it and never satisfies the floor.',
  'refused':'The probe declined to report a number. Correct on the refusal anchor (an expander has no dimension); a defect on a graph whose answer is known.',
  'ungated':'Below the size where this probe is judged. Charted for context, never alarmed.',
  '±':'Spread across seeds (standard deviation). The noise floor of the instrument at this N.',
  'σ':'Spread across seeds (standard deviation). For a family whose graph varies per seed this is ensemble spread plus estimator noise; otherwise estimator noise alone.',
  'band':'The tolerance band drawn: theory at the centre, the declared tolerance as the bar, the measured value as the marker (with its seed spread). A marker outside the bar is out of tolerance.',
  'Δ':'|measured minus theory| for this cell.',
  'gap':'The spectral gap of the largest component\'s normalised Laplacian (524, the structure census). A graph of spectral dimension d_s closes it as N^(-2/d_s); an expander keeps it open. \u00b1 is the spread across graph draws. Read up to a fixed size (a factorisation of a three- or four-dimensional lattice above it costs more memory than a cell should); a larger rung says "not measured", with the size on hover.',
  'd_s from gap':'-2 divided by the slope of log(gap) against log(N) from the rung below: the spectral dimension the gap alone implies. "open" when the gap does not close as a power of N.',
  'diameter':'The largest component\'s diameter (a lower bound from breadth-first sweeps; exact on a tree). Grows as N^(1/d_f) on a graph of fractal dimension d_f, as log N on a tree, an expander or a random graph.',
  'd_f from diameter':'1 divided by the slope of log(diameter) against log(N) from the rung below. Large (or "> 50") when the diameter grows as a logarithm.',
  'giant':'The share of nodes in the largest component. The gap and diameter are read on it, and their slopes against its size.',
  'clique':'The largest clique (a + marks a lower bound, where the search hit its work limit). Degeneracy and triangles per node on hover. Counted up to the fleet census\u2019s size limit; a larger rung says "not measured", with the size on hover.'

};
function calibTh(label,extra){const key=String(label).replace(/\s*\(.*$/,'').trim();const h=CALIB_HELP[key]||(/ sw$/.test(key)?CALIB_HELP['sw']:'');return `<th${h?` title="${esc(h)}"`:''}>${esc(label)}${extra||''}</th>`}
function calibBand(v){
  if(v==null||v.theory==null||v.tolerance==null||v.measured==null)return '';
  const tol=+v.tolerance,theory=+v.theory,m=+v.measured,sd=+(v.seed_std||0);
  const half=Math.max(tol,Math.abs(m-theory)+sd,1e-9)*1.15;
  const x=(val)=>50+50*(val-theory)/half;
  const lo=x(theory-tol),hi=x(theory+tol),mx=x(m),sl=x(m-sd),sh=x(m+sd);
  const cls=Math.abs(m-theory)<=tol?'in':'out';
  return `<span class="calib-band" title="theory ${theory.toFixed(4)} \u00b1 tolerance ${tol.toFixed(3)}; measured ${m.toFixed(4)}${sd?` \u00b1 ${sd.toFixed(3)} across seeds`:''}"><span class="calib-band-tol" style="left:${lo.toFixed(1)}%;width:${(hi-lo).toFixed(1)}%"></span><span class="calib-band-theory" style="left:50%"></span>${sd?`<span class="calib-band-sd" style="left:${sl.toFixed(1)}%;width:${Math.max(0.5,sh-sl).toFixed(1)}%"></span>`:''}<span class="calib-band-mark ${cls}" style="left:${mx.toFixed(1)}%"></span></span>`;
}
const CALIB_STRUCT_COLS=['gap','d_s from gap','diameter','d_f from diameter','giant','clique'];
function calibSci(v){return (v==null||!isFinite(+v))?'\u2014':(Math.abs(+v)>=0.01?(+v).toFixed(4):(+v).toExponential(3))}
function calibNotMeasured(what,limit){return `<td class=muted title="${esc(`${what} is not measured above N=${Number(limit).toLocaleString()}: the census stops there by design, so the cell is empty rather than lost`)}"><small>not measured</small></td>`}
function calibNotYet(what){return `<td class=muted title="${esc(`${what} is not measured on this cell yet: tools/probe_calibration.py --structure measures it, as many cells at once as memory holds`)}"><small>not measured yet</small></td>`}
function calibStructCells(s,n,limits,first){
  if(!s||!s.seeds)return `<td class=muted colspan=${CALIB_STRUCT_COLS.length} title="${esc(s&&s.error?s.error:'no census on this rung yet: tools/probe_calibration.py --structure')}">${s&&s.error?'census failed':'no census yet'}</td>`;
  const L=limits||{},gapLimit=+L.gap_max_n||0,cliqueLimit=+L.clique_max_n||0,above=(lim)=>lim&&n!=null&&+n>lim;
  const B=L.before_531||{},gapBefore=+B.gap_max_n||0,cliqueBefore=+B.clique_max_n||0;
  const spread=(v,sd)=>sd!=null&&v?` <small class=muted>\u00b1${(100*sd/Math.abs(v)).toFixed(0)}%</small>`:'';
  const gap=s.gap!=null?`<td title="${esc('method: '+(s.gap_method||'?')+' \u00b7 '+s.seeds+' seed(s)')}">${calibSci(s.gap)}${spread(s.gap,s.gap_spread)}</td>`:(above(gapLimit)?calibNotMeasured('the spectral gap',gapLimit):(above(gapBefore)?calibNotYet('The spectral gap'):`<td class=muted title="${esc(s.gap_reason||'')}">\u2014</td>`));
  const ds=s.implied_d_s!=null?`<td title="${esc('local gap slope '+(+s.gap_slope).toFixed(3)+' from the rung below; d_s = -2 / slope')}">${(+s.implied_d_s).toFixed(2)}</td>`
    :(s.gap_slope!=null&&s.gap_slope>=-1e-9?`<td class=muted title="${esc('gap slope '+(+s.gap_slope).toFixed(3)+': the gap does not close as a power of N')}">open</td>`
    :(above(gapLimit)?calibNotMeasured('the spectral gap, and so the d_s it implies,',gapLimit)
    :above(gapBefore)&&s.gap==null?calibNotYet('The spectral gap, and so the d_s it implies,')
    :(first?`<td class=muted title="a slope needs this rung and the one below it"><small>first rung</small></td>`:`<td class=muted title="needs the gap on this rung and the one below">\u2014</td>`)));
  const diam=s.diameter_lower!=null?`<td title="${esc('lower bound '+s.diameter_lower+(s.diameter_upper!=null?', upper bound '+s.diameter_upper:''))}">${esc(Math.round(+s.diameter_lower).toLocaleString())}${spread(s.diameter_lower,s.diameter_lower_spread)}</td>`:'<td class=muted>\u2014</td>';
  const df=s.implied_d_f!=null?`<td title="${esc('local diameter slope '+(+s.diameter_slope).toFixed(3)+' from the rung below; d_f = 1 / slope')}">${(+s.implied_d_f>=50?'> 50':(+s.implied_d_f).toFixed(2))}</td>`:(first?`<td class=muted title="a slope needs this rung and the one below it"><small>first rung</small></td>`:'<td class=muted>\u2014</td>');
  const giant=`<td>${s.giant_fraction!=null?(100*s.giant_fraction).toFixed(s.giant_fraction>0.999?0:1)+'%':'\u2014'}</td>`;
  const clique=s.largest_clique!=null?`<td title="${esc('degeneracy '+(s.degeneracy!=null?Math.round(s.degeneracy):'\u2014')+(s.triangles_per_node!=null?' \u00b7 triangles per node '+(+s.triangles_per_node).toFixed(3):''))}">${Math.round(s.largest_clique)+(s.largest_clique_exact===false?'+':'')}</td>`
    :(above(cliqueLimit)?calibNotMeasured('the clique census',cliqueLimit):(above(cliqueBefore)?calibNotYet('The clique census'):'<td class=muted>\u2014</td>'));
  return gap+ds+diam+df+giant+clique;
}
function calibVerdictClass(v){return v==='PASS'?'ok':(v==='FAIL'?'bad':'warn')}
function atlasFamilyName(f){return String(f).replace('periodic_','').replace(/_/g,' ')}
function calibConvergenceWords(atlas,family,probe){const A=((((atlas||{}).probes||{})[probe]||{}).families||{})[family]||{};const words=[A.trend,A.at_the_top].filter(Boolean);return words.length?words.join(', '):'too few sizes to say'}
function atlasLastDeviation(v){const rows=(v.rungs||[]).filter(r=>r.mean!=null);const top=rows[rows.length-1];return top?{n:top.n,dev:top.deviation}:null}
function atlasProbeLine(p,a,tol){
  const fams=Object.entries(a.families||{}),key=String(tol);
  const reached=fams.filter(([,v])=>(v.first_n_with_error_below||{})[key]!=null),never=fams.filter(([,v])=>(v.first_n_with_error_below||{})[key]==null);
  const latest=reached.slice().sort((x,y)=>(+y[1].first_n_with_error_below[key])-(+x[1].first_n_with_error_below[key]))[0];
  const dev=v=>{const t=atlasLastDeviation(v);return t?`${t.dev>=0?'+':''}${(+t.dev).toFixed(3)} at N=${Number(t.n).toLocaleString()}`:'no reading'};
  const head=`<b>${esc(p)}</b>: within ±${tol} (its error with the seeds’ spread) on ${reached.length} of ${fams.length} families`
    +(latest?`, the last from N=${Number(latest[1].first_n_with_error_below[key]).toLocaleString()} (${esc(atlasFamilyName(latest[0]))})`:'');
  return `<li>${head}${never.length?`; never on ${never.map(([f,v])=>`${esc(atlasFamilyName(f))} (${esc(dev(v))})`).join(', ')}`:''}.</li>`;
}
function atlasByAccuracy(families){
  const off=v=>{const t=atlasLastDeviation(v);return t&&t.dev!=null&&isFinite(+t.dev)?Math.abs(+t.dev):Infinity};
  return Object.entries(families||{}).sort((x,y)=>{const a=off(x[1]),b=off(y[1]);return a!==b?(a<b?-1:1):String(x[0]).localeCompare(String(y[0]))});
}
function renderProbeAtlas(root,atlas){
  if(!atlas||atlas.error){root.innerHTML=`<div class=empty>${esc(atlas&&atlas.error?'atlas unavailable: '+atlas.error:'no calibration table yet')}</div>`;return}
  const tols=atlas.tolerances||[],probesOrder=['d_s','d_V','d_w','d_B'].filter(p=>atlas.probes&&atlas.probes[p]);
  const lines=`<ul class=atlas-lines>${probesOrder.map(p=>atlasProbeLine(p,atlas.probes[p],0.1)).join('')}</ul>`;
  const fmtFirst=n=>n==null?'<span class=muted>never</span>':esc(Number(n).toLocaleString());
  const topWords=v=>v==null?'—':(/^off by/.test(v)?`<b class=warn>${esc(v)}</b>`:esc(v));
  const perFamily=probesOrder.map(p=>{const a=atlas.probes[p];return `<details class=atlas-family open><summary><b>${esc(p)}</b> on each known geometry: its trend with N, how close it is at the largest sizes, and the first N from which it stays within each tolerance</summary><table class="calib-table"><thead><tr>${calibTh('family')}${calibTh('trend')}${calibTh('at the largest sizes')}${calibTh('approach')}${calibTh('theory')}${calibTh('observed range')}${calibTh('d* (gap)')}${tols.map(t=>calibTh('±'+t)).join('')}</tr></thead><tbody>${atlasByAccuracy(a.families).map(([f,v])=>`<tr><td>${esc(atlasFamilyName(f))}</td><td>${esc(v.trend||'—')}</td><td>${topWords(v.at_the_top)}</td><td>${esc((v.approach||'').replace('_',' '))}</td><td>${v.theory!=null&&isFinite(+v.theory)?esc((+v.theory).toFixed(3)):'—'}</td><td>${v.observed_range?esc(v.observed_range[0].toFixed(3))+' … '+esc(v.observed_range[1].toFixed(3)):'—'}</td><td>${v.asymptote!=null?esc(Number(v.asymptote).toFixed(3))+(v.asymptote_gap!=null?' ('+(v.asymptote_gap>=0?'+':'')+esc(Number(v.asymptote_gap).toFixed(3))+')':''):'—'}</td>${tols.map(t=>`<td>${fmtFirst((v.first_n_with_error_below||{})[String(t)])}</td>`).join('')}</tr>`).join('')}</tbody></table></details>`}).join('');
  root.innerHTML=`<div class=muted>Each probe against graphs whose dimension is known exactly, from the calibration table below. Each probe’s rows run from the family it reads most accurately to the one it reads least, by its distance from the known value at the largest size it reads; a family it never reads comes last. A probe’s error at a size is its distance from the known value plus the spread of its ten seeds. Trend compares that error over the larger half of the sizes with the smaller half (improves: under 0.6 of it; worsens: over 1.25); at the largest sizes says whether the remaining error is within the seeds’ own spread.</div>`
    +lines+perFamily+calibMarginBands(atlas.d_s_margins);
}
function calibMarginBands(m){
  if(!m||m.error)return m&&m.error?`<div class=muted>d_s's guard: ${esc(m.error)}</div>`:'';
  const own=m.cells_with_margins>0,committed=m.committed_with_the_build,bands=own?m.from_this_table:(committed&&committed.bands)||{};
  const rungs=Object.keys(bands).sort((a,b)=>a-b);if(!rungs.length)return '';
  const range=(r,none)=>r?`${(+r[0]).toFixed(1)} to ${(+r[1]).toFixed(1)}`:`<span class=muted>${none}</span>`;
  const sep=v=>v===true?'<b class=good>yes</b>':v===false?'<b class=warn>no</b>':'<span class=muted>\u2014</span>';
  const rows=rungs.map(n=>{const b=bands[n],p=b.plateau||{},w=b.whole_range||{},read=Object.entries(b.null_families_reported||{}).map(([f,r])=>`${atlasFamilyName(f)} (${(+r[1]).toFixed(1)})`).join(', ');
    return `<tr><td>${esc(Number(n).toLocaleString())}</td><td>${range(p.geometry,'none')}</td><td>${range(p.no_finite_dimension,'none reached')}</td><td>${sep(p.separated)}</td><td>${range(w.geometry,'none')}</td><td>${range(w.no_finite_dimension,'none reached')}</td><td>${sep(w.separated)}</td><td>${read?`<b class=warn>${esc(read)}</b>`:'<span class=muted>none</span>'}</td></tr>`}).join('');
  const source=own?`${m.cells_with_margins} of ${m.cells} cells of the table carry their margins`
    :`the reading committed with the build${committed&&committed.computed_utc?' ('+esc(committed.computed_utc)+')':''}`;
  return `<details class=atlas-family><summary><b>d_s’s guard against reading a mixing rate</b>: by how much a power law beats exponential decay in its return probability, on graphs with a dimension and on graphs without one</summary>`
    +`<div class=muted>A walk on a graph with no finite dimension (a random graph, a hyperbolic one) loses the way back exponentially fast, and a power law fitted to that reads a large number that is a mixing rate, not a dimension. So d_s is reported only where a power law beats exponential decay by more than ${esc(m.threshold)} in AICc. Each row is one size of the table: the range of that margin over the families with a dimension (they should clear it by far) and over those without one (they should not reach it), over d_s’s window and over the whole walk; “with d” is the families with a dimension, “without” those without one, and apart says whether the two ranges do not overlap (a dash: nothing to compare). “none reached” means no graph without a dimension reached this test at that size: every probe had refused it already. The last column names any graph without a dimension that d_s read anyway, with its margin; a reading under 4,096 nodes is kept and not relied on.</div>`
    +`<table class="calib-table calib-margins"><thead><tr><th rowspan=2>N</th><th colspan=3>d_s’s window</th><th colspan=3>the whole walk</th><th rowspan=2>read anyway</th></tr><tr><th>with d</th><th>without</th><th>apart</th><th>with d</th><th>without</th><th>apart</th></tr></thead><tbody>${rows}</tbody></table><div class=muted>${source}. The margin is AICc(exponential decay) − AICc(power law).</div></details>`;
}
function atlasEinstein(atlas){
  const P=(atlas&&atlas.probes)||{},s=P.d_s,v=P.d_V,w=P.d_w;
  if(!s||!v||!w)return '<div class="empty">the table has no d_s, d_V and d_w to tie together</div>';
  const at=(probe,f)=>new Map(((probe.families||{})[f]?.rungs||[]).filter(r=>r.mean!=null).map(r=>[+r.n,+r.mean]));
  const rows=Object.keys(s.families||{}).filter(f=>(v.families||{})[f]&&(w.families||{})[f]).map(f=>{
    const ds=at(s,f),dv=at(v,f),dw=at(w,f),theory=+v.families[f].theory;
    const sizes=[...ds.keys()].filter(n=>dv.has(n)&&dw.has(n)&&dw.get(n)>0).sort((a,b)=>a-b);
    if(!sizes.length)return `<tr><td>${esc(atlasFamilyName(f))}</td><td colspan=5 class=muted>no size where d_s, d_V and d_w all read</td></tr>`;
    const res=n=>({theory:ds.get(n)-2*theory/dw.get(n),measured:ds.get(n)-2*dv.get(n)/dw.get(n)});
    const top=sizes[sizes.length-1],r=res(top),big=sizes.filter(n=>n>=4096),worst=big.length?Math.max(...big.map(n=>Math.abs(res(n).measured))):null;
    const num=x=>(x>=0?'+':'')+x.toFixed(3);
    return `<tr><td>${esc(atlasFamilyName(f))}</td><td>${esc(sizes.length)} sizes, ${esc(Number(sizes[0]).toLocaleString())} to ${esc(Number(top).toLocaleString())}</td><td>${esc(Number(top).toLocaleString())}</td><td>${num(r.measured)}</td><td>${num(r.theory)}</td><td>${worst==null?'—':worst.toFixed(3)}</td></tr>`}).join('');
  return `<table class="calib-table"><thead><tr>${['family','sizes where all three read','largest','d_s − 2·d_V/d_w, measured','with the known d_V','worst from 4,096, measured'].map(h=>calibTh(h)).join('')}</tr></thead><tbody>${rows}</tbody></table>`
    +'<div class=muted>Each family of the table at every size where d_s, d_V and d_w all read: how far d_s lies from what the other two say through the Einstein relation, with d_V as measured and with its known value. Near 0 means the three probes tell one consistent story about the graph.</div>';
}
function renderCalibration(d){
  const status=document.getElementById('calibStatus'),probes=document.getElementById('calibProbes'),
        einstein=document.getElementById('calibEinstein'),sweeps=document.getElementById('calibSweeps'),
        prov=document.getElementById('calibProvenance'),ladders=document.getElementById('calibLadders'),
        refusals=document.getElementById('calibRefusals'),
        atlasEl=document.getElementById('calibAtlas');
  if(!status||!probes||!einstein||!sweeps||!prov)return;
  if(atlasEl)renderProbeAtlas(atlasEl,d&&d.available!==false?d.atlas:null);
  if(!d||d.available===false){
    status.innerHTML=`<div class="report-error-box"><b>no calibration table in force</b><pre>${esc(String((d&&d.hint)||'main.py run or main.py serve computes it in the foreground before starting; by hand: python3 tools/probe_calibration.py --probe-ladders'))}</pre>${d&&d.expected_path?`<div class=muted>expected at ${esc(d.expected_path)}</div>`:''}</div>`;
    probes.innerHTML='<div class="empty">run <code>tools/probe_calibration.py --probes</code> to populate</div>';
    einstein.innerHTML='<div class="empty">populated with the pipeline trial</div>';
    if(ladders)ladders.innerHTML='<div class="empty">run <code>tools/probe_calibration.py --probe-ladders</code> to populate</div>';
    if(refusals)refusals.innerHTML='';
    sweeps.innerHTML='<div class="empty">run <code>tools/probe_calibration.py --sweep-scan</code> to populate</div>';
    prov.textContent='\u2014';
    return;
  }
  if(calibRefreshTimer){clearInterval(calibRefreshTimer);calibRefreshTimer=null}
  const P=d.pipeline_trial||null,S=d.sweep_scan||null,D=d.deviation||{},plan=d.plan||{},profile=d.profile||{},origin=d.origin||{};
  const authoritative=d.authoritative===true;
  const verdict=D.verdict||'\u2014';
  status.innerHTML=(authoritative?'':`<div class="report-badge bad">NOT AUTHORITATIVE: reduced profile (${esc(profile.seeds||'?')} seed(s)${profile.max_nodes?`, ladders truncated at ${esc(profile.max_nodes)} nodes`:''}). Nothing collected under this table is certifiable; the full suite has not been run on this install.</div> `)
    +`<span class="report-badge ${calibVerdictClass(verdict)}">${verdict==='PASS'?'\u2713':verdict==='FAIL'?'\u2717':'!'} calibration ${esc(verdict)}</span> <span class="report-badge ${P&&P.pipeline_passed?'ok':'warn'}">${P?(P.pipeline_passed?'\u2713 pipeline trial PASS':'! pipeline trial reported failures'):'pipeline trial not yet run'}</span>`
    +`<div class=muted>${esc(D.summary_line||'')}</div>`
    +(plan.total_cells?`<div class=muted>${esc(plan.current||0)} of ${esc(plan.total_cells)} cells current${plan.stale?`, ${esc(plan.stale)} stale`:''}${plan.missing?`, ${esc(plan.missing)} missing`:''}${plan.failed?`, ${esc(plan.failed)} failed`:''} \u00b7 ${esc(D.seeds||profile.seeds||'?')} seeds per cell \u00b7 ${origin.adopted?`adopted from ${esc(origin.adopted_from||'elsewhere')} after verification`:`computed on ${esc(origin.computed_on||'this host')}`}</div>`:'')
    +(P&&P.stage_failures&&P.stage_failures.length?`<pre>${esc(P.stage_failures.join('\n'))}</pre>`:'');
  if(P&&Array.isArray(P.rows)&&P.rows.length){
    const passed=P.rows.filter(r=>r.status==='PASS').length;
    probes.innerHTML=`<div>${esc(passed)} of ${esc(P.rows.length)} readings carried right${passed===P.rows.length?'':' <b class=warn>(see below)</b>'}: two graphs whose answer is known, sent through the fleet\u2019s own recording path, so that a value landing in the wrong column or lost on the way is caught. It checks the plumbing, not the probes; their accuracy is the table above.</div><details${passed===P.rows.length?'':' open'}><summary>the readings</summary><table class="calib-table"><thead><tr>${['anchor','probe','measured','theory','drift','tolerance','band','status'].map(h=>calibTh(h)).join('')}</tr></thead><tbody>${P.rows.map(r=>`<tr class="calib-${esc(String(r.status||'').toLowerCase())}"><td>${esc(r.anchor)}</td><td><b>${esc(r.channel)}</b></td><td>${calibNum(r.measured)}</td><td>${calibNum(r.theory)}</td><td>${calibNum(r.drift)}</td><td>${calibNum(r.tolerance,2)}</td><td>${calibBand(r)}</td><td><span class="report-badge ${r.status==='PASS'?'ok':(r.status==='DRIFT'?'bad':'warn')}">${esc(r.status)}</span></td></tr>`).join('')}</tbody></table><div class=muted>${esc(P.seeds||'?')} seed(s) \u00b7 ${esc(P.seconds!=null?P.seconds+'s':'')} \u00b7 a REFUSED row means the estimator declined a graph whose answer is known, which is itself a defect.</div></details>`;
  }else probes.innerHTML='<div class="empty">pipeline trial not recorded in the table</div>';
  einstein.innerHTML=atlasEinstein(d.atlas);
  if(ladders){
    const CALIB_SECTIONS=[
      ['Graphs whose dimension is known exactly. The probes should read it.',['periodic_ring','periodic_square_lattice','periodic_honeycomb_lattice','periodic_triangular_lattice','periodic_cubic_lattice','periodic_hypercubic_lattice_4d']],
      ['Exact non-integer dimensions.',['sierpinski_gasket','sierpinski_carpet','uniform_random_tree']],
      ['Graphs with no dimension. The probes should refuse; a confident number here is a defect, so "refused" below is the correct reading.',['random_3_regular','random_4_regular','erdos_renyi_degree_2','erdos_renyi_sparse','erdos_renyi_mid','erdos_renyi_dense','erdos_renyi_degree_6','balanced_binary_tree']]];
    const all=D.families?Object.entries(D.families):[];
    const placed=new Set();
    const fams=[];
    for(const [title,names] of CALIB_SECTIONS){let first=true;for(const nme of names){const e=all.find(([f])=>f===nme);if(!e)continue;placed.add(nme);fams.push([e[0],e[1],first?title:null]);first=false}}
    for(const e of all){if(!placed.has(e[0]))fams.push([e[0],e[1],fams.length===0?'':null])}
    if(fams.length){
      const waived=(D.waivers_applied||[]);const expired=(D.waivers_expired||[]);
      const waiverBanner=(waived.length||expired.length)?`<div class="report-badge warn">${waived.length?`${waived.length} waived cell(s): ${waived.map(w=>`${esc(w.family)}:${esc(w.channel)}@${esc(w.n)} until ${esc(w.expires_utc)}`).join(' \u00b7 ')}`:''}${expired.length?` \u00b7 ${expired.length} EXPIRED waiver(s) no longer apply`:''}</div>`:'';
      const incompleteBanner=plan.complete===false?`<div class="report-badge warn">table incomplete: ${esc(plan.current||0)}/${esc(plan.total_cells||'?')} cells current; the suite resumes from the completed cells at the next start</div>`:'';
      ladders.innerHTML=waiverBanner+incompleteBanner+fams.map(([name,F,sectionTitle])=>{
        const channels=Array.from(new Set([...Object.keys(F.trends||{}),...(F.rows||[]).flatMap(r=>Object.keys(r.channels||{}))])).sort();
        const head=`<tr>${calibTh('N')}${channels.map(c=>calibTh(c,F.theory&&F.theory[c]!=null?` <small class=muted>(theory ${(+F.theory[c]).toFixed(3)})</small>`:'')).join('')}${CALIB_STRUCT_COLS.map(h=>calibTh(h)).join('')}</tr>`;
        const limits=(d.atlas&&d.atlas.structure_limits)||{};
        const rows=[...(F.rows||[]),...(F.extension_rows||[])].map((r,index)=>`<tr class="${r.complete===false?'calib-incomplete':''}"><td><b>${esc(r.n)}</b>${r.seeds_present!=null&&r.seeds_planned!=null&&r.seeds_present<r.seeds_planned?`<small class=muted> ${esc(r.seeds_present)}/${esc(r.seeds_planned)} seeds</small>`:''}</td>${channels.map(c=>{
          const v=(r.channels||{})[c]||{};
          const gates=v.refusal_gates&&Object.keys(v.refusal_gates).length?` <small class=muted title="${esc(Object.entries(v.refusal_gates).map(([g,k])=>`${k}\u00d7 ${g}`).join(', '))}">(${esc(Object.values(v.refusal_gates).reduce((a,b)=>a+(+b||0),0))}\u00d7)</small>`:'';
          if(v.status==='MISSING')return (sectionTitle?`<h2 class="calib-section">${esc(sectionTitle)}</h2>`:'')+`<td class="calib-refused-cell" title="no seed measured yet">\u2014</td>`;
          if(v.status==='WAIVED')return `<td class="calib-refused-cell" title="${esc((v.waiver&&v.waiver.reason)||'')} \u00b7 expires ${esc((v.waiver&&v.waiver.expires_utc)||'')}">${v.measured==null?'refused':(+v.measured).toFixed(3)} <small>waived (${esc(v.unwaived_status||'')})</small></td>`;
          if(v.status==='FALSE_CONFIDENCE')return `<td class="calib-false-confidence" title="a confident reading on a graph with no dimension">${(+v.measured).toFixed(3)} \u26a0</td>`;
          if(v.status==='OUT_OF_TOLERANCE')return `<td class="calib-false-confidence" title="drift ${(+v.drift).toFixed(3)} exceeds tolerance ${(+v.tolerance).toFixed(3)}">${(+v.measured).toFixed(3)} \u2717${calibBand(v)}</td>`;
          if(v.status==='REFUSED')return `<td class="calib-false-confidence" title="refused inside a gated band: the probe declined a graph whose answer is known">refused \u2717${gates}</td>`;
          if(v.status==='REFUSED_MAJORITY')return `<td class="calib-false-confidence" title="only ${Math.round((+v.valid_fraction)*100)}% of seeds returned a value (floor ${Math.round((+v.availability_floor)*100)}%); the survivors' mean ${(+v.measured).toFixed(3)} is not the instrument's reading of this rung">${(+v.measured).toFixed(3)} \u2717 <small>${Math.round((+v.valid_fraction)*100)}% seeds</small>${gates}</td>`;
          if(v.status==='UNGATED'||v.status==='UNGATED_MEASURED')return `<td class="calib-refused-cell" title="below the size where this probe is gated; charted, never alarmed">${v.measured==null?'refused':(+v.measured).toFixed(3)} <small>ungated</small>${gates}</td>`;
          if(v.measured==null)return `<td class="calib-refused-cell" title="${F.expectation==='REFUSE'?esc('correct: this family has no finite dimension; a probe that reports one here is broken'):esc(CALIB_HELP['refused'])}">${F.expectation==='REFUSE'?'refused \u2713':'refused'}${gates}</td>`;
          const hover=[v.seed_std!=null?`\u03c3 ${(+v.seed_std).toFixed(3)}: ${CALIB_HELP['\u03c3']}`:'',v.seed_refusals?`${v.seed_refusals} seed(s) refused`:''].filter(Boolean).join('\n');
          return `<td${hover?` title="${esc(hover)}"`:''}>${(+v.measured).toFixed(3)}${v.drift!=null?` <small class=muted>\u0394${(+v.drift).toFixed(3)}</small>`:''}${v.seed_refusals?'<small class=muted>*</small>':''}${calibBand(v)}</td>`;
        }).join('')}${calibStructCells(r.structure,r.n,limits,index===0)}</tr>`).join('');
        const SR=((d.atlas&&d.atlas.structure_readings)||{})[name]||null;
        const structLine=SR?`<div class=muted>structure, by the committed rule (523): <b>${SR.finite_dimension===true?'finite dimension':SR.finite_dimension===false?'no finite dimension':'not decidable'}</b>${SR.implied_spectral_dimension!=null?` \u00b7 the gap implies d_s \u2248 ${(+SR.implied_spectral_dimension).toFixed(2)}`:''}${SR.implied_fractal_dimension!=null?` \u00b7 the diameter implies d_f \u2248 ${(+SR.implied_fractal_dimension).toFixed(2)}`:''} \u00b7 ${esc(SR.why||'')}</div>`:'';
        const conv=F.convergence||{};
        const convLine=Object.keys(conv).length?`<div class=muted>does more N buy accuracy? ${channels.map(c=>{const k=conv[c];return k?`<b>${esc(c)}</b>: ${esc(calibConvergenceWords(d.atlas,name,c))}${k.late_median_drift!=null?` (drift at the smaller sizes ${esc(k.early_median_drift)}, at the larger ${esc(k.late_median_drift)}${k.late_median_spread!=null?`, seeds\u2019 spread ${esc(k.late_median_spread)}`:''})`:''}`:''}).filter(Boolean).join(' \u00b7 ')}</div>`:'';
        const flow=F.finite_size_flow||{};
        const flowLine=Object.keys(flow).length?`<div class=muted>finite-size flow d(N) = d* + a\u00b7N<sup>\u2212\u03c9</sup>: ${channels.map(c=>{const f=flow[c];if(!f)return `${esc(c)}: not fittable (<4 measured rungs)`;const gap=f.asymptote_gap==null?'':` \u00b7 d*\u2212theory ${(+f.asymptote_gap>=0?'+':'')}${(+f.asymptote_gap).toFixed(3)}`;const om=f.omega_unresolved?'flat after first rung':`\u03c9=${esc(f.omega)}`;return `<b>${esc(c)}</b>: d*=${(+f.d_star).toFixed(3)}${gap} \u00b7 ${om} \u00b7 rms ${esc(f.residual_rms)} over ${esc(f.points)} rungs`}).join(' \u00b7 ')}</div>`:'';
        const fc=F.expectation==='REFUSE'?` \u00b7 <b class="${F.false_confidence_readings?'warn':''}">${esc(F.false_confidence_readings)} false-confidence reading(s)</b>`:'';
        const disp=`<div class=muted>seed spread means: ${esc(F.dispersion_meaning||(F.graph_varies_per_seed?'ensemble dispersion (a different graph per seed)':'estimator dispersion (one graph, different walks)'))}</div>`;
        return `<div class="calib-scan-block"><b>${esc(name)}</b> <span class="report-badge ${calibVerdictClass(F.verdict)}">${esc(F.verdict||'\u2014')}</span> <span class=muted>(${esc(F.expectation)}${F.graph_varies_per_seed?', graph varies per seed':''})</span> \u2014 <span class=muted>${esc(F.why||'')}</span><table class="calib-table"><thead>${head}</thead><tbody>${rows}</tbody></table>${fc?`<div class=muted>${fc.replace(/^ \u00b7 /,'')}</div>`:''}${convLine}${flowLine}${structLine}${disp}</div>`;
      }).join('')+`<div class=muted>${esc(D.seeds||'?')} seed(s) per cell \u00b7 every family to the top of its ladder${profile.max_nodes?` (truncated at ${esc(profile.max_nodes)} nodes: NOT authoritative)`:''} \u00b7 \u0394 = |measured \u2212 theory| \u00b7 \u03c3 = spread across seeds \u00b7 the bar is the tolerance band with theory at its centre and the measured value marked</div>`;
    } else ladders.innerHTML='<div class="empty">no cells measured yet</div>';
  }
  if(refusals){
    const R=D.refusals||[];
    if(R.length){
      const agg={};R.forEach(e=>{const k=`${e.family}|${e.channel}|${e.gate}`;agg[k]=agg[k]||{family:e.family,channel:e.channel,gate:e.gate,seeds:0,rungs:new Set()};agg[k].seeds+=+e.count||0;agg[k].rungs.add(e.n)});
      refusals.innerHTML=`<table class="calib-table"><thead><tr>${['family','probe','gate that refused','seeds refused','at N'].map(h=>calibTh(h)).join('')}</tr></thead><tbody>${Object.values(agg).sort((a,b)=>a.family.localeCompare(b.family)||a.channel.localeCompare(b.channel)).map(a=>`<tr><td>${esc(a.family)}</td><td><b>${esc(a.channel)}</b></td><td>${esc(a.gate)}</td><td>${esc(a.seeds)}</td><td>${Array.from(a.rungs).sort((x,y)=>x-y).map(esc).join(', ')}</td></tr>`).join('')}</tbody></table><div class=muted>d_s refuses when AICc prefers spectral-gap decay over a power law; d_w has no comparable model-selection gate. Counting refusals beside successes is what makes that asymmetry visible.</div>`;
    }else refusals.innerHTML='<div class=muted>no probe refused on any measured cell</div>';
  }
  const refs=S?(S.references?Object.values(S.references):(Array.isArray(S.by_n)&&S.by_n.length?[S]:[])):[];
  if(refs.length){
    sweeps.innerHTML=refs.map(R=>{
      const ramp=R.ramp||[];
      const head=`<tr>${calibTh('N')}${ramp.map(r=>calibTh(`${r} sw`)).join('')}${calibTh('required')}${calibTh('band')}</tr>`;
      const rows=(R.by_n||[]).map(row=>{
        const cells=ramp.map(r=>{
          const cell=(row.cells||[]).find(c=>c.sweeps===r)||{};
          const cls=cell.meets_floor?'calib-floor-met':(cell.resolved===false?'calib-unresolved':'');
          const label=cell.median_ess==null?'\u2014':(+cell.median_ess).toFixed(1);
          const band=(cell.ess_min!=null&&cell.ess_max!=null&&cell.ess_min!==cell.ess_max)?` <small class=muted>[${(+cell.ess_min).toFixed(0)}\u2013${(+cell.ess_max).toFixed(0)}]</small>`:'';
          return `<td class="${cls}" title="${cell.resolved===false?'tau finer than recording grid; ESS overestimates':''}">${label}${band}${cell.resolved===false?'<sup>?</sup>':''}</td>`;
        }).join('');
        const band=row.crossing_band||[null,null];
        const bandText=(band[0]==null&&band[1]==null)?'\u2014':`[${band[0]==null?'\u2014':esc(band[0])}, ${band[1]==null?'>'+esc(ramp[ramp.length-1]||'?'):esc(band[1])}]`;
        return `<tr><td><b>${esc(row.n)}</b></td>${cells}<td>${row.required_sweeps==null?`&gt; ${esc(ramp[ramp.length-1]||'?')}`:`<b>${esc(row.required_sweeps)}</b>`}</td><td>${bandText}</td></tr>`;
      }).join('');
      const law=R.law||{};
      const lawHtml=law.status==='fitted'
        ?`suggested law: <b>${esc(law.best)}</b> \u00b7 fits (log-RMS): ${(law.fits||[]).map(f=>`${esc(f.law)}=${esc(f.log_rms)}`).join(' \u00b7 ')}`
        :`law: ${esc(law.detail||law.status||'not fitted')}`;
      return `<div class="calib-scan-block"><b>${esc(R.reference||String(R.candidate_spec||'reference').split('/').pop())}</b><table class="calib-table"><thead>${head}</thead><tbody>${rows}</tbody></table><div class=muted>median ESS over ${esc(R.seeds||'?')} seed(s) \u00b7 floor ${esc(R.floor)} \u00b7 band = [first budget any seed certified, first budget every seed certified] \u00b7 <sup>?</sup> = unresolved tau \u00b7 values saturate at ${esc(R.ess_recording_ceiling||72)} (recording-grid ceiling, not sampling abundance) \u00b7 ${lawHtml}</div></div>`;
    }).join('')+`<div class=muted>this is evidence for the S0 decision (policy.initial_sweeps_multiplier in the campaign spec), not the decision.</div>`;
  }else sweeps.innerHTML='<div class="empty">run <code>tools/probe_calibration.py --sweep-scan</code> to populate (an explicit operator run; never launched automatically)</div>';
  const runs=d.runs||[];const hours=runs.reduce((a,r)=>a+(+r.elapsed_seconds||0),0)/3600;
  prov.innerHTML=`<div>${authoritative?'<b>Authoritative table.</b>':'<b>NOT an authoritative table.</b>'} ${esc(plan.current||0)} of ${esc(plan.total_cells||'?')} cells at ${esc(profile.seeds||'?')} seed(s) per cell${profile.max_nodes?`, ladders truncated at ${esc(profile.max_nodes)} nodes`:', every family to the top of its ladder'}; ${origin.adopted?`adopted from ${esc(origin.adopted_from||'elsewhere')} on ${localTimeHtml(origin.adopted_utc||'')} after verification`:`computed on ${esc(origin.computed_on||'this host')}`}; ${hours.toFixed(1)} h of measurement across ${esc(runs.length)} run(s); last written ${d.written_utc?localTimeHtml(d.written_utc):'\u2014'}.</div>`
    +`<div>contract <b>${esc(d.contract||'\u2014')}</b> \u00b7 suite version <b>${esc(d.suite_version||'\u2014')}</b> \u00b7 science fingerprint <code>${esc(d.science_fingerprint||'\u2014')}</code> \u00b7 estimator fingerprint <code>${esc(d.estimator_fingerprint||'\u2014')}</code> \u00b7 suite fingerprint <code>${esc(d.suite_fingerprint||'\u2014')}</code> \u00b7 written by build <b>${esc(d.build_number||'\u2014')}</b> (provenance only, never a staleness key)</div>`
    +(P&&P.generated_utc?`<div>pipeline trial ${localTimeHtml(P.generated_utc)} on ${esc(P.host||'?')}</div>`:'')+(S&&S.generated_utc?`<div>sweep scan ${localTimeHtml(S.generated_utc)}${S.migrated_from?` (carried over from ${esc(S.migrated_from)})`:''}</div>`:'')
    +(d.path?`<div>file <code>${esc(d.path)}</code> (${esc(d.source||'')}) \u00b7 the file is the source of truth; the ledger holds a fingerprint-stamped cache \u00b7 raw cells: <code>/api/calibration/cells</code></div>`:'');
}
const REPORTS_LATE_MS=15*4000;let reportsAnsweredAt=0;
function reportsLate(e,now=Date.now()){return !!reportStatus&&reportsAnsweredAt>0&&now-reportsAnsweredAt<REPORTS_LATE_MS&&/HTTP 50[34]\b/.test(String(e))}
async function refreshReports(force=false){if(!campaign||(!force&&currentPage!=='reports')||reportBusy)return;reportBusy=true;try{await refreshReportCatalog();reportStatus=await get('/api/reports/status/'+encodeURIComponent(oneCampaign()));reportsAnsweredAt=Date.now();await refreshStudyBundles();renderReports(reportStatus)}catch(e){const b=document.getElementById('reportsBadge'),f=document.getElementById('reportFailure');if(reportsLate(e)){const ago=Math.round((Date.now()-reportsAnsweredAt)/1000);if(b){b.className='report-badge';b.textContent='reports late'}if(f)f.innerHTML=`<div class=report-late-line>the reports' status is late (last answer ${ago} s ago): the API is busy, most often making a study bundle; what is shown is its last answer</div>`;return}if(b){b.className='report-badge bad';b.textContent='reports offline'}if(f)f.innerHTML=`<div class=report-error-box><b>reports status unavailable</b><pre>${esc(String(e))}</pre></div>`}finally{reportBusy=false}}
async function triggerReports(action='start'){ if(!campaign||!reportAdmin||bundleBusy)return;if(action==='quiet'){if(quietAskedAt&&Date.now()-quietAskedAt<QUIET_ASK_WAIT_MS)return;quietAskedAt=Date.now();const btn=document.getElementById('reportsManual');if(btn){btn.disabled=true;btn.textContent='asked: pausing the fleet, please wait…'}}bundleBusy=true;reportTriggerError=null;try{await SYS.postJson('/api/reports/trigger',{campaign_id:campaign,action});setTimeout(()=>refreshReports(true),150)}catch(e){if(action==='quiet')quietAskedAt=0;reportTriggerError=String(e);renderReports(reportStatus)}finally{bundleBusy=false}}

async function refreshStudyBundles(){try{studyBundles=await get('/api/reports/study')}catch(_){studyBundles=null}}
function renderStudyBundles(){let box=document.getElementById('studyBundles');if(!box){const host=document.getElementById('reportQuiet');if(!host)return;box=document.createElement('div');box.id='studyBundles';box.className='bundle-ring';host.after(box)}
  const list=studyBundles&&Array.isArray(studyBundles.bundles)?studyBundles.bundles:[];
  if(!list.length){box.innerHTML='<div class=muted>study bundles appear here: every campaign of the folder in one archive, with its front page, the explorer and the gate trees</div>';return}
  const prefix=studyBundles.download_prefix||'/reports/study/bundles/';
  const nf=v=>Number(v||0).toLocaleString('en-US');
  const took=v=>v==null?'<span class=muted>&mdash;</span>':esc(durationText(v));
  const campsHtml=b=>{const cs=b.campaigns||[];if(!cs.length)return '<span class=muted>none</span>';
    if(!cs.some(c=>c.laws!=null||c.seconds!=null))return `<div class=study-camp title="${esc(cs.map(c=>c.label||c.campaign_id).join('; '))}">campaigns <b>${cs.map(c=>esc(c.campaign_id)).join(', ')}</b></div>`;
    return `<div class=study-camps-list>${cs.map(c=>`<div class=study-camp title="${esc(c.label||'')}"><b>${esc(c.campaign_id)}</b>${c.laws!=null?` <span class=muted>${nf(c.laws)} laws &middot; ${nf(c.graphs)} graphs</span>`:''}${c.seconds!=null?` <span class=muted>&middot; ${esc(durationText(c.seconds))}</span>`:''}</div>`).join('')}</div>`};
  box.innerHTML=`<table class="bundle-table study-table" title="One row per study bundle, newest first: every campaign's reports in one archive, with study.json and the gate trees, its campaigns side by side on the line under it. The one being made is the first row while it runs."><thead><tr><th title="When the study bundle was written, in this browser's time zone; hover a time for its UTC">study bundle, your time</th><th>age</th><th title="From the start of the report phase to its end: every campaign's reports">reports took</th><th title="Campaigns without a complete report cycle, named in study.json with the reason">missing</th><th class=num>size</th><th title="The front page (577), the gate trees (an interactive page since 578; a picture before it) and the explorer (572); a bundle made before the explorer keeps its Classify maps">pages</th><th></th></tr></thead><tbody>${studyLiveRow(reportStatus)}${list.map(b=>{const href=SYS.route(prefix+encodeURIComponent(b.filename)),gates=b.gates||b.svg?SYS.route(prefix+encodeURIComponent(b.gates||b.svg)):null,maps=b.maps&&!b.explorer?SYS.route(prefix+encodeURIComponent(b.maps)):null,explorer=b.explorer?SYS.route(prefix+encodeURIComponent(b.explorer)):null,front=b.front?SYS.route(prefix+encodeURIComponent(b.front)):null,miss=b.missing||[];return `<tr class=study-row><td>${localTimeHtml(b.built_utc||'')}</td><td class=muted>${esc(relativeTime(b.built_utc||''))}</td><td>${took(b.reporting_seconds)}</td><td>${miss.length?`<span class=warn title="${esc(miss.map(m=>m.campaign_id+': '+m.why).join('; '))}">${miss.length}</span>`:'<span class=ok>none</span>'}</td><td class=num>${fmtBytes(b.bytes)}</td><td class=study-actions>${front||gates||maps||explorer?`${front?`<a class=chip href="${front}" target=_blank rel=noopener title="the bundle's front page (577): what the study found, what deserves a closer look and why, what a law costs, and every view">front page</a> `:''}${gates?`<a class=chip href="${gates}" target=_blank rel=noopener title="${b.gates?"every campaign's tree of gates, rung by rung: hover, open a rung, compare the campaigns, and a gate's stops in the explorer (578)":"every campaign's gate tree side by side, as a picture (a bundle made before 578)"}">gate trees</a>`:''}${maps?` <a class=chip href="${maps}" target=_blank rel=noopener title="every campaign's Classify maps side by side, as a picture: a bundle made before the explorer (572) has only these">maps</a>`:''}${explorer?` <a class=chip href="${explorer}" target=_blank rel=noopener title="every law at every rung: filters, up to 16 maps at once, the spread over N, the curves, the counts and the laws, in a page that stands alone (572)">study explorer</a>`:''}`:'&mdash;'}</td><td class=study-actions><a class=chip href="${href}" download="${esc(b.filename)}" title="${esc(b.filename)}">download</a> <button type=button class="chip study-delete" data-admin-write data-study-delete="${esc(b.filename)}" title="delete ${esc(b.filename)} and its pages from disk; needs the admin link">delete</button></td></tr><tr class=study-camps-row><td colspan=7 class=study-camps title="The campaigns in it: laws, graphs and the seconds its reports took; hover one for its quadrant">${campsHtml(b)}</td></tr>`}).join('')}</tbody></table>${studyDeleteNote?`<div class=muted>${studyDeleteNote}</div>`:''}`;
  box.onclick=e=>{const b=e.target&&e.target.closest?e.target.closest('[data-study-delete]'):null;if(b)deleteStudyBundle(b.getAttribute('data-study-delete'))}}
async function deleteStudyBundle(filename){
  if(!filename||!window.confirm(`Delete ${filename} and its pages from disk? It cannot be undone.`))return;
  try{const r=await SYS.postJson('/api/study-bundles/delete',{filename});studyDeleteNote=`deleted ${esc(filename)}${r&&r.freed_bytes!=null?`, ${esc(fmtBytes(r.freed_bytes))} freed`:''}`}
  catch(e){studyDeleteNote=`<span class=warn>not deleted: ${esc(String(e&&e.message||e))}</span>`}
  await refreshStudyBundles();renderStudyBundles()}
function studyLiveRow(s){
  const q=(s||{}).quiet_report||{},sp=q.study_progress,lay=q.study_layout||{};
  if(!sp||!Object.keys(sp).length||!QUIET_STAGES.includes(q.stage))return '';
  const started=(q.study_process||{}).started_utc||q.stage_utc||'';
  const order=Object.keys(sp).sort((a,b)=>(+a||0)-(+b||0)||String(a).localeCompare(String(b)));
  const line=c=>{const v=sp[c]||{},st=String(v.state||'queued'),stage=String(v.stage||'');let frac=0,label;
    if(st==='queued')label=lay.at_once===1?'queued: one campaign at a time, see why below':'queued';
    else if(st==='unchanged'){frac=1;label='unchanged since its last cycle: its reports are kept'}
    else if(['complete','complete_with_errors','error'].includes(st)){frac=1;label=(st==='complete'?'done':st.replace(/_/g,' '))+(v.seconds!=null?` in ${durationText(v.seconds)}`:'')}
    else{const m=/(\d+) of (\d+)/.exec(stage);
      if(m){frac=0.4+0.6*(+m[1]-1)/Math.max(1,+m[2]);label=`report ${m[1]} of ${m[2]}: ${stage.split(' \u00b7 ').slice(2).join(' \u00b7 ')}`}
      else if(/^snapshot/.test(stage)){frac=0.15;label=stage.replace(/^snapshot \u00b7 campaign \S+ \u00b7 /,'snapshot: ')}
      else{frac=0.05;label=stage||'starting'}}
    const clock=st==='running'&&v.started_utc?` \u00b7 ${liveClock(v.started_utc)}`:'';
    return `<div class="study-camp study-live-camp"><b>${esc(c)}</b><span class="study-bar ${esc(st)}" title="${esc(stage||st)}"><i style="width:${(frac*100).toFixed(0)}%"></i></span><small>${esc(label)}${clock}</small></div>`};
  const clock=started?` &middot; ${liveClock(started)}`:'';
  return `<tr class="bundle-live study-live"><td>${started?localTimeHtml(started):'&mdash;'}</td><td class="muted study-live-state">making it<br>${esc(q.stage)}${clock}</td><td colspan=5 class="study-camps study-live-camps">${order.map(line).join('')}</td></tr>`
    +(lay.why?`<tr class="bundle-live study-live study-why-row"><td></td><td colspan=6 class="muted study-why">${esc(lay.why)}</td></tr>`:'')}
function fmtBytes(b){b=+b||0;return b>=1048576?(b/1048576).toFixed(1)+' MiB':b>=1024?(b/1024).toFixed(0)+' KiB':b+' B'}
function memoryAdmissionRow(rv,gib){
  const ad=rv&&rv.admission;
  if(!ad) return `<tr><td class=muted>budget</td><td>${gib(rv.budget_bytes)}</td><td colspan=2 class=muted>${esc(rv.note||'')}</td></tr>`;
  return `<tr class=mem-admission><td class=muted title="admission keeps this much available to the host; simulations are stopped under the second figure">floor</td>`
    +`<td>${gib(ad.floor_bytes)}</td><td colspan=2 class=muted>${gib(ad.available_bytes)} available \u00b7 ${gib(ad.unrealised_bytes)} still to be taken by running children \u00b7 `
    +`<b class="${(+ad.headroom_bytes||0)>0?'ok':'warn'}">${gib(ad.headroom_bytes)} headroom</b> \u00b7 simulations stop under ${gib(ad.shed_below_bytes)}</td></tr>`;
}
function scratchAlertsHtml(d){
  const rows=(d.operational_alerts||[]).filter(a=>String(a.alert_key||a.key||'').startsWith('scratch:')||a.source==='scratch');
  return rows.map(a=>`<div class="alert-box ${a.severity==='error'?'bad':'warn'} scratch-alert" data-alert="${esc(a.alert_key||a.key||'')}"><b>the RAM scratch: ${esc(a.message||a.alert_key||'')}</b><div class=muted>since ${esc(a.first_seen_utc||'')} · seen ${esc(a.occurrences||1)}x · <code>uv run python tools/scratch_holders.py</code> lists what fills it</div></div>`).join('');}
function renderStranded(d){const el=document.getElementById('strandedAlert');if(!el)return;
const behind=(d.operational_alerts||[]).find(a=>a.code==='DECISIONS_BEHIND');
const behindHtml=scratchAlertsHtml(d)+(behind?`<div class="alert-box ${behind.severity==='info'?'info':'warn'}"><b>${esc(behind.headline)}</b><div class=muted>${esc(behind.explanation||'')}</div></div>`:'');
const alert=(d.operational_alerts||[]).find(a=>a.code==='STRANDED_SCIENTIFIC_WORK');if(!alert){el.innerHTML=behindHtml;return}
const cols=['candidate','state','in this state'], rows=alert.candidates||[], states=Object.entries(alert.by_state||{});
const table=rows.length?`<table class="service-table stranded-table"><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(c=>`<tr><td><a href="${candidateHref(c.candidate_id,c.campaign_id)}" title="${candidateTitle(c)}"><code>${candidateLabel(c)}</code></a></td><td>${esc(c.state||'—')}</td><td class=muted>${c.candidate_state_age_seconds==null?'—':esc(Math.round(c.candidate_state_age_seconds)+'s')}</td></tr>`).join('')}</tbody></table>`:'';
el.innerHTML=behindHtml+`<div class="alert-box ${alert.severity==='warning'?'warn':'info'}"><b>${esc(alert.headline)}</b><div class=muted>${esc(alert.explanation||'')}</div>${states.length?`<div class=chiprow>${states.map(([k,n])=>`<span class=chip>${esc(k)} · ${n}</span>`).join(' ')}</div>`:''}${table}</div>`}
function renderWorkAccounting(d){
  const host=document.getElementById('workAccounting'); if(!host) return;
  const c=d.runtime_counts||{};
  const n=v=>Number(v||0);
  const burned=n(c.burned_graph_ordinals), churn=n(c.claims_without_execution);
  const rows=[
    ['graph jobs created', n(c.graph_jobs_created), 'simulate rows inserted; one per graph the campaign intends to realize', ''],
    ['highest ensemble ordinal', n(c.highest_graph_ordinal), 'the largest number any G-code carries; equals jobs created when nothing is burned', ''],
    ['burned ordinals', burned,
     burned?'ordinals reserved and never used, so G-codes run ahead of the graph count'
           :'no ordinal has been reserved and left unused; a G-code counts graphs',
     burned?'bad':'good'],
    ['simulation leases taken', n(c.simulation_leases), 'increments when a worker claims the row, before anything decides it will run', ''],
    ['simulations actually run', n(c.simulation_executions), 'child processes that started, from the attempts table', ''],
    ['claims that never ran', churn,
     churn?'leased then released without executing: memory refusal, lease expiry, or shutdown'
          :'every lease taken started a child process', churn?'warn':'good'],
    ['completed graph realizations', n(c.completed_graph_realizations), 'finished with a durable result artifact', ''],
    ['analysis leases taken', n(c.analysis_leases), 'counted separately; an analysis does not create a graph', ''],
  ];
  host.innerHTML=`<table><thead><tr><th>quantity</th><th>count</th><th>what it counts</th></tr></thead><tbody>${
    rows.map(([label,value,about,cls])=>
      `<tr><td>${esc(label)}</td><td class="${cls}" style="text-align:right;font-variant-numeric:tabular-nums">${esc(value)}</td><td class="muted">${esc(about)}</td></tr>`
    ).join('')}</tbody></table>`;
}

let memLedgerBusy=false,memLedgerAt=0;
function gib(b){return ((+b||0)/1073741824).toFixed(2)+' GiB'}
async function refreshMemoryLedger(){const host=document.getElementById('memoryLedger');if(!host||memLedgerBusy||Date.now()-memLedgerAt<15000)return;memLedgerBusy=true;
  try{const L=await get('/api/memory-ledger');memLedgerAt=Date.now();renderMemoryLedger(host,L)}catch(e){host.innerHTML=`<div class=muted>memory ledger unavailable: ${esc(String(e.message||e))}</div>`}finally{memLedgerBusy=false}}
function renderMemoryLedger(host,L){if(!L||L.error){host.innerHTML=`<div class=muted>${esc((L&&L.error)||'no ledger')}</div>`;return}
  const total=+L.mem_total_bytes||1;const rows=(L.lines||[]).filter(l=>l.bytes>0||l.key==='residual');
  const bar=rows.filter(l=>l.bytes>0).map(l=>`<span class="mem-seg mem-${esc(l.key)}" style="width:${(100*l.bytes/total).toFixed(2)}%" title="${esc(l.key)} ${gib(l.bytes)} (${l.percent_of_total}%)"></span>`).join('');
  const byN=(m,label)=>{const ks=Object.keys(m||{});if(!ks.length)return '';return `<div class=muted style="margin:4px 0 0 12px">${label}: ${ks.map(k=>`N=${esc(k)} × ${m[k].processes} = ${gib(m[k].pss_bytes)}`).join(' · ')}</div>`};
  const rv=L.reservation_vs_measured;
  const resHtml=rv?`<table class="mem-table" style="margin-top:8px"><thead><tr><th title="Admission lane">lane</th><th title="Bytes the admission ledger holds for leased work">reserved</th><th title="Physical memory (PSS) those children use right now">measured</th><th title="reserved / measured; above ~1.5 the model withholds admission for memory nobody uses">ratio</th></tr></thead><tbody>${['simulation','analysis'].map(k=>`<tr><td>${k}</td><td>${gib(rv[k].reserved_bytes)}</td><td>${gib(rv[k].measured_pss_bytes)}</td><td class="${rv[k].ratio>1.5?'warn':'ok'}">${rv[k].ratio==null?'–':rv[k].ratio.toFixed(2)+'×'}</td></tr>`).join('')}${memoryAdmissionRow(rv,gib)}</tbody></table>`:'';
  host.innerHTML=`<div class=muted>MemTotal ${gib(total)} · MemAvailable ${gib(L.mem_available_bytes)} · used by the header's definition (total − available) ${gib(L.used_by_available_bytes)} · ${L.process_count} processes read · sampled ${esc(String(L.sampled_utc||''))}</div>
  <div class="mem-bar" title="each segment is one ledger line; hover for bytes">${bar}</div>
  <table class="mem-table"><thead><tr><th title="What the memory is">line</th><th>bytes</th><th>% of total</th><th title="Whether the kernel can reclaim it under pressure">reclaimable</th><th>note</th></tr></thead><tbody>${rows.map(l=>`<tr><td><span class="mem-dot mem-${esc(l.key)}"></span>${esc(l.key.replace(/_/g,' '))}</td><td>${gib(l.bytes)}</td><td>${l.percent_of_total==null?'':l.percent_of_total+'%'}</td><td>${l.reclaimable?'yes':'no'}</td><td class=muted>${esc(l.note||'')}</td></tr>`).join('')}</tbody></table>
  ${byN(L.simulation_by_n,'simulation children by N')}${byN(L.analysis_by_n,'analysis children by N')}
  ${L.namespaces&&L.namespaces.stale_bytes>0?`<div class="warn" style="margin:6px 0 0 12px" title="Volatile namespaces left by previous runs. tmpfs pages are RAM until the files are deleted, so the admission budget subtracts them and no run reclaims a directory it does not own. Reclaim with: python3 main.py sweep">${gib(L.namespaces.stale_bytes)} in ${L.namespaces.namespaces.filter(n=>n.status==='stale').length} stale volatile namespace(s) from previous runs — run <code>main.py sweep</code> to reclaim</div>`:''}
  ${L.scratch&&L.scratch.available?`<div class=muted style="margin:4px 0 0 12px">scratch ${esc(L.scratch.root)}: ${Object.entries(L.scratch.dirs||{}).sort((a,b)=>b[1]-a[1]).slice(0,8).map(([k,v])=>`${esc(k)} ${gib(v)}`).join(' · ')}${L.scratch.truncated?' · (walk truncated)':''}</div>`:''}
  ${resHtml}`}
let workerCountNote='',workerCountBusy=false;
function renderWorkerCount(d){
  const host=document.getElementById('workerCount');if(!host)return;
  const w=d&&d.fleet_workers;if(!w){host.innerHTML='<div class="empty">the worker count arrives with the next poll</div>';return}
  const status=`<div id=workerCountStatus class=muted>${esc(w.reading||'')}${workerCountNote?` · <span class=warn>${esc(workerCountNote)}</span>`:''}</div>`;
  const input=document.getElementById('workerCountInput');
  if(input&&document.activeElement===input){const s=document.getElementById('workerCountStatus');if(s)s.outerHTML=status;return}
  const shown=w.target==null?(w.active_slots||''):w.target;
  host.innerHTML=`<div class=toolbar><label class=muted>workers <input id=workerCountInput data-admin-write type=number min=1 max="${esc(w.most)}" step=1 value="${esc(shown)}" style="width:6em"></label><button type=button class=gsd-control data-admin-write id=workerCountSet title="stop or start slots now to reach this count">set</button><button type=button class=gsd-control data-admin-write id=workerCountAuto${w.target==null?' disabled':''} title="hand the count back to the ramp">let the ramp decide</button><span class=muted>1 to ${esc(w.most)} on this machine${w.target==null?'':` · you asked for ${esc(w.target)}`}</span></div>${status}`;
  document.getElementById('workerCountSet').onclick=()=>setWorkerCount(Number(document.getElementById('workerCountInput').value||0));
  document.getElementById('workerCountAuto').onclick=()=>setWorkerCount(null);
  document.getElementById('workerCountInput').onkeydown=ev=>{if(ev.key==='Enter'){ev.preventDefault();setWorkerCount(Number(ev.target.value||0))}};
}
async function setWorkerCount(value){
  if(workerCountBusy)return;workerCountBusy=true;workerCountNote='';let answer=null;
  try{answer=await SYS.postJson('/api/campaigns/manage',{action:'fleet_workers',workers:value});if(last)last.fleet_workers=answer;workerCountNote=answer.target==null?'the ramp decides again':`asked for ${answer.target}; slots stop or start within a second`}
  catch(e){workerCountNote=String((e&&e.message)||e)}
  finally{workerCountBusy=false;const input=document.getElementById('workerCountInput');if(input&&document.activeElement===input&&input.blur)input.blur();renderWorkerCount(answer?{fleet_workers:answer}:last)}}
let workloadNote='',workloadBusy=false;
function renderWorkload(d){
  const host=document.getElementById('workload');if(!host)return;
  const w=d&&d.workload;if(!w){host.innerHTML='<div class="empty">the workload arrives with the next poll</div>';return}
  const shares=Object.entries(w.shares||{}).map(([g,v])=>`${esc(g)} ${Math.round(100*v)}%`).join(' \u00b7 ')||'every campaign alike';
  const kept=(w.system_cpus||[]).join(',');
  const mates=Object.entries(w.shares_a_core||{}).map(([c,m])=>`CPU ${esc(c)} shares its core with ${esc((m||[]).join(', '))}, which simulations may still use`).join('; ');
  const status=`<div id=workloadStatus class=muted>groups: ${shares} \u00b7 system CPUs: ${esc(kept||'none')} \u00b7 simulations on ${esc((w.work_cpus||[]).length)} of ${esc(w.cpus)} CPUs${mates?` \u00b7 ${mates}`:''}${workloadNote?` \u00b7 <span class=warn>${esc(workloadNote)}</span>`:''}</div>`;
  const focused=['workloadSplit','workloadCpus'].map(id=>document.getElementById(id)).find(el=>el&&document.activeElement===el);
  if(focused){const s=document.getElementById('workloadStatus');if(s)s.outerHTML=status;return}
  host.innerHTML=`<div class=toolbar><label class=muted>split <input id=workloadSplit data-admin-write type=text value="${esc(w.split||'')}" placeholder="A=1,B=1" style="width:9em"></label><label class=muted>system CPUs <input id=workloadCpus data-admin-write type=text value="${esc(kept)}" placeholder="0,16" style="width:9em"></label><button type=button class=gsd-control data-admin-write id=workloadSet title="keep these CPUs for the system and share the slots this way">set</button></div>${status}`;
  const send=()=>setWorkload(document.getElementById('workloadSplit').value,document.getElementById('workloadCpus').value);
  document.getElementById('workloadSet').onclick=send;
  for(const id of ['workloadSplit','workloadCpus'])document.getElementById(id).onkeydown=ev=>{if(ev.key==='Enter'){ev.preventDefault();send()}};
}
async function setWorkload(split,cpus){
  if(workloadBusy)return;workloadBusy=true;workloadNote='';let answer=null;
  try{answer=await SYS.postJson('/api/campaigns/manage',{action:'workload',split:String(split??''),system_cpus:String(cpus??'')});if(last)last.workload=answer;workloadNote=`set; ${(answer.system_cpus||[]).length?`CPUs ${answer.system_cpus.join(',')} kept for the system`:'no CPU kept for the system'}`}
  catch(e){workloadNote=String((e&&e.message)||e)}
  finally{workloadBusy=false;for(const id of ['workloadSplit','workloadCpus']){const el=document.getElementById(id);if(el&&document.activeElement===el&&el.blur)el.blur()}renderWorkload(answer?{workload:answer}:last)}}
function renderSystem(d){
  const v=d.versions||{},u=d.compute_utilization||{},r=d.system_resources||{},io=d.io_summary||{},cap=d.operational_bottleneck||{};
  renderWorkerCount(d);renderWorkload(d);
  renderStranded(d);
  renderWorkAccounting(d);
  document.getElementById('identity').innerHTML=`Build <b>${esc(v.build)}</b> · runtime fingerprint <b>${esc(cfg.runtimeFingerprint||v.build_id||'')}</b><br>engine ${esc(v.engine||'')} · analysis ${esc(v.analysis||'')} · policy ${esc(v.policy||'')} · environment ${esc(v.environment_id||'')}`;
  refreshMemoryLedger();
  const bottleneck=document.getElementById('bottleneck');if(bottleneck){
    const scratch=io.scratch_backend||{},dbio=io.database||{},cls=cap.severity==='warning'?'warn':(cap.severity==='error'?'bad':'');
    const scratchName=scratch.path?(scratch.tmpfs?`tmpfs · ${scratch.mount_path||scratch.path}`:`persistent fallback · ${scratch.mount_path||scratch.path}`):'unavailable';
    const priorDetails=bottleneck.querySelector('.capacity-details'),detailsOpen=priorDetails?priorDetails.open:!!bottleneck.dataset.capacityDetailsOpen;
    const churn=(dbio.table_churn?.top||[]).slice(0,6),pgRoles=(dbio.process_roles||[]).map(x=>`${x.role}:${x.count}`).join(' · '),backend=(dbio.relation_io?.by_backend||[]).slice(0,5);
    const churnHtml=churn.length?`<div class=capacity-secondary><b>hot PostgreSQL tables</b><small>${churn.map(x=>`${esc(x.table)} ${fmt(x.mutations_per_second||0)}/s · HOT ${x.hot_update_percent==null?'—':fmt(x.hot_update_percent)+'%'} · dead ${fmt(x.dead_tuples||0)}`).join('<br>')}</small></div>`:'';
    const backendHtml=backend.length?`<div class=capacity-secondary><b>relation write sources</b><small>${backend.map(x=>`${esc(x.backend_type||'unknown')} / ${esc(x.context||'—')} · ${bytes(x.bytes_per_second)}/s`).join('<br>')}</small></div>`:'';
    bottleneck.innerHTML=`<div class="capacity-verdict ${cls}"><span class=capacity-kicker>current verdict</span><b>${esc(cap.state||'warming')}</b><div>${esc(cap.explanation||'Waiting for enough live evidence.')}</div></div><details class=capacity-details${detailsOpen?' open':''}><summary>storage attribution & secondary evidence</summary><div class=capacity-detail-grid><div><span>GSD services</span><b>R ${bytes(io.tracked_service_read_bytes_per_second)}/s · W ${bytes(io.tracked_service_write_bytes_per_second)}/s</b></div><div><span>PostgreSQL process pressure / WAL / SQL temp</span><b>R ${bytes(dbio.read_bytes_per_second)}/s · W ${bytes(dbio.write_bytes_per_second)}/s</b><small>all PostgreSQL descendants${pgRoles?' · '+esc(pgRoles):''}<br>WAL ${bytes(dbio.wal?.bytes_per_second)}/s · permanent relation I/O ${bytes(dbio.relation_io?.permanent_bytes_per_second)}/s · SQL temp ${bytes(dbio.sql_temp?.bytes_per_second)}/s · ${esc(dbio.sql_temp?.tablespace||'temp tablespace warming')}</small></div><div><span>host physical traffic</span><b>R ${bytes(io.host_read_bytes_per_second)}/s · W ${bytes(io.host_write_bytes_per_second)}/s</b><small>physical-device aggregate; compare against PostgreSQL source rates rather than subtracting unlike counter domains</small></div><div><span>scratch / raw envelope tier</span><b>${esc(scratchName)} · raw simulation bodies tmpfs-only until analysis</b>${scratch.used_bytes==null?'':`<small>${bytes(scratch.used_bytes)} held${scratch.tmpfs&&r.memory_total_bytes?` \u00b7 ${(100*scratch.used_bytes/r.memory_total_bytes).toFixed(0)}% of host RAM, not reclaimable and subtracted from the admission budget until retention deletes it`:''} \u00b7 ${bytes(scratch.free_bytes)} free</small>`}</div></div>${backendHtml}${churnHtml}<div class=muted>${esc(cap.note||'')} ${esc(io.interpretation||'')}</div></details>`;
    const nextDetails=bottleneck.querySelector('.capacity-details');if(nextDetails)nextDetails.ontoggle=()=>{bottleneck.dataset.capacityDetailsOpen=nextDetails.open?'1':''};
  }
  const rows=d.services||[];
  document.getElementById('services').innerHTML=`<table class=service-table><thead><tr><th>service</th><th>state / last event</th><th>process</th><th>I/O</th><th>last message</th></tr></thead><tbody>${rows.map(x=>`<tr><td><b>${esc(x.role)}</b><div class="muted pid-list">PID ${esc((x.pids||[]).join(', ')||'—')}</div></td><td><span class="service-${esc(x.state||'stale')}">${esc(x.state||'')}</span><div class=muted>heartbeat ${localTimeHtml(x.heartbeat_utc)} · ${x.heartbeat_age_seconds==null?'—':esc(x.heartbeat_age_seconds)+'s ago'}</div><div>event ${localTimeHtml(x.latest_event_utc)} · ${esc(x.last_event_topic||'no consumed event')}</div><div class=muted>${x.latest_event_age_seconds==null?'—':esc(x.latest_event_age_seconds)+'s ago'}</div></td><td>CPU ${x.cpu_percent_one_core==null?'—':esc(x.cpu_percent_one_core)+'%'}<br>RSS ${bytes(x.rss_bytes)}</td><td>R ${bytes(x.read_bytes_per_second)}/s<br>W ${bytes(x.write_bytes_per_second)}/s<div class=muted>${esc(x.io_status||'—')}</div></td><td><code>${esc(x.last_message||'—')}</code></td></tr>`).join('')}</tbody></table>`;
  const rawText=JSON.stringify({campaign_id:d.campaign_id,paused:d.paused,compute_utilization:u,system_resources:r,io_summary:io,operational_bottleneck:cap,analysis_queue:d.analysis_queue,services:d.services,operational_alerts:d.operational_alerts,
    dashboard_response:d.dashboard_response},null,2);document.getElementById('raw').textContent=rawText;document.getElementById('raw').dataset.copyText=rawText
}
for(const id of ['explorerQ','explorerGroup','explorerState','explorerEstimate','explorerSample','explorerCoupling','explorerScaling','explorerCoeffScale','explorerMinN','explorerTermMode']){const el=document.getElementById(id);if(el)el.oninput=(id==='explorerQ'?drawExplorerSoon:drawExplorer)}document.getElementById('explorerBody')?.addEventListener('click',ev=>{const th=ev.target.closest('th[data-sort]');if(th)explorerSortBy(th.dataset.sort)});document.getElementById('explorerTerms')?.addEventListener('click',ev=>{const b=ev.target.closest('button[data-op]');if(!b)return;const op=b.dataset.op;if(explorerSelectedTerms.has(op))explorerSelectedTerms.delete(op);else explorerSelectedTerms.add(op);renderExplorerFilters();drawExplorer()});const explorerReload=document.getElementById('explorerReload');if(explorerReload)explorerReload.onclick=()=>loadExplorer(true);const explorerScope=document.getElementById('explorerScope');if(explorerScope)explorerScope.oninput=()=>{const chosen=String(explorerScope.value||'');if(chosen.startsWith('c:')){explorerScope.value='';SYS.switchCampaign(chosen.slice(2));return}explorerLoaded=false;explorerRows=[];drawExplorer();loadExplorer(true)};document.getElementById('studyNow')?.addEventListener('click',ev=>{const card=ev.target.closest('[data-campaign]');if(card)SYS.switchCampaign(card.dataset.campaign)});document.getElementById('landMeta')?.addEventListener('change',ev=>{if(ev.target&&ev.target.id==='landLattices')chooseLandLattices(ev.target.checked)});document.getElementById('homeFilters')?.addEventListener('change',chooseFilter);document.getElementById('homeFilters')?.addEventListener('click',ev=>{if(ev.target&&ev.target.id==='filterClear')clearFilters()});const explorerClear=document.getElementById('explorerClear');if(explorerClear)explorerClear.onclick=clearExplorerFilters;const reportsManual=document.getElementById('reportsManual');if(reportsManual)reportsManual.onclick=()=>triggerReports('quiet');setInterval(()=>refreshReports(false),4000 );setInterval(updateLiveClocks,250);
window.addEventListener('rr:campaign',ev=>{const next=String(ev.detail.campaign);if(campaign!==next){campaign=next;explorerLoaded=false;explorerRows=[];explorerMeta={};explorerSelectedTerms.clear();landscapeRevision=null;homeLoading={campaign:next,overview:false};markHomeLoading()}renderStudyNow(studyNow);paintCampaignScope();scheduleLandscape(0);if(currentPage==='explorer')loadExplorer(true);if(currentPage==='reports')refreshReports(true);if(currentPage==='campaigns')refreshGate()});window.addEventListener('rr:overview',ev=>{if(homeLoading)homeLoading.overview=true;last=ev.detail;renderHome(last);if(currentPage==='system')renderSystem(last);
  if(currentPage==='reports'){updateLiveClocks();reportTick=(reportTick||0)+1;if(reportTick%5===0)refreshReports()}});
async function copyText(text){if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(text);return true}const area=document.createElement('textarea');area.value=text;area.style.position='fixed';area.style.opacity='0';document.body.appendChild(area);area.select();let ok=false;try{ok=document.execCommand('copy')}finally{area.remove()}return ok}

const GATE_RULE_LABEL={no_finite_dimension:'no finite dimension',no_giant_component:'fragmented (no giant component)',gate_audit:'audited past a refusal'};
function gateHtml(g){
  if(!g||g.error)return `<div class="muted">the structure gate's record is unavailable${g&&g.error?': '+esc(g.error):''}</div>`;
  const early=g.early_stage||{},rule=g.rule||{},c=g.campaign||null;
  const needed=+early.agreements_needed||100,agree=+early.agree||0;
  const switchText=!early.switch?'off: recorded as "would refuse", never acted on':(agree>=needed?'on and acting':`on, and acts once ${needed} agree (${agree} so far)`);
  const campaignRows=c?Object.entries(c.laws_by_latest_rule||{}).map(([name,n])=>`<tr><td>${esc(GATE_RULE_LABEL[name]||name)}</td><td>${esc(n)}</td></tr>`).join(''):'';
  return `<p class="muted">From N=${esc(rule.gate_at_n)} a rung is bought only for a law whose graphs have a finite dimension on both chains: the gap exponent over ${esc((rule.gap_window||[]).join(' to '))} at most ${esc(rule.gap_exponent_at_most)} and the diameter exponent over ${esc((rule.diameter_window||[]).join(' to '))} at least ${esc(rule.diameter_exponent_at_least)}, the thresholds the fifteen calibration families committed. It only refuses; the share it lets through and every refusal near a threshold are followed past it, at most ${esc(rule.audit_in_flight_at_most)} at once.</p>`
    +`<table class="gate-table"><tr><th>what</th><th>now</th><th></th></tr>`
    +`<tr><td>the clear case at N=${esc(rule.early_gate_at_n)}</td><td>${esc(switchText)}<div class="muted">would have refused ${esc(early.would_refuse||0)} law(s) read again at N=${esc(rule.gate_at_n)}: the full rule agreed on ${esc(agree)}, read finite on ${esc(early.disagree||0)}</div></td><td><button type="button" class="gsd-control" data-admin-write data-gate="early" data-on="${early.switch?'false':'true'}">${early.switch?'turn off':'turn on'}</button></td></tr>`
    +`</table>`
    +(c?`<table class="gate-table"><tr><th>campaign ${esc(c.campaign_id)}: laws whose latest decision is the gate's</th><th>laws</th></tr>${campaignRows||'<tr><td colspan="2" class="muted">none yet</td></tr>'}</table>`:'')}
function renderGate(g){const root=document.getElementById('gateBody');if(!root)return;root.innerHTML=gateHtml(g);
  root.querySelectorAll('button[data-gate]').forEach(button=>{button.onclick=()=>gateAction(button)})}
async function refreshGate(){if(gateBusy)return;gateBusy=true;
  try{gateData=await get('/api/gate'+(campaign&&String(campaign)!=='study'?'/'+encodeURIComponent(campaign):''));renderGate(gateData)}
  catch(e){renderGate({error:String(e&&e.message||e)})}finally{gateBusy=false}}
async function gateAction(button){
  try{if(button.dataset.gate==='early')await SYS.postJson('/api/gate/early_stage',{on:button.dataset.on==='true'})}
  catch(e){alert('the gate did not change: '+String(e&&e.message||e))}
  refreshGate()}

const CAMPAIGN_STATE_CLASS={active:'ok',running:'ok',surveyed:'ok','at its law budget':'ok',done:'idle',paused:'warn',pausing:'warn',closed:'idle',completed:'idle',archived:'idle',failed:'bad'};
async function manageCampaign(body){campaignActionError=null;try{return await SYS.postJson('/api/campaigns/manage',body)}
catch(e){campaignActionError=String(e&&e.message||e);renderCampaigns(campaignsData);throw e}}
function campaignsStale(message){const el=document.getElementById('campaignsStale');if(!el)return;
  if(!message){el.hidden=true;el.innerHTML='';return}
  el.hidden=false;el.innerHTML=`<span class=warn>out of date</span> since ${localTimeHtml(campaignsFailedSince)} · ${esc(message)} · retrying in ${campaignsRetryTicks*4}s`}
async function refreshCampaigns(force=false){
  if((!force&&currentPage!=='campaigns')||campaignsBusy)return;campaignsBusy=true;
  if(campaignsRetryTimer){clearTimeout(campaignsRetryTimer);campaignsRetryTimer=null}
  refreshGate();
  try{campaignsData=await get('/api/campaigns/overview');campaignsNotePauses(campaignsData);renderCampaigns(campaignsData);
    campaignsFailedSince=null;campaignsRetryTicks=1;campaignsStale(null);
    if(campaignsPausing.size)campaignsRetryTimer=setTimeout(()=>refreshCampaigns(false),4000 );
    if(campaignSelected)await openCampaignPanel(campaignSelected);}
  catch(e){const message=String(e&&e.message||e);
    if(!campaignsFailedSince)campaignsFailedSince=new Date().toISOString();
    if(campaignsData)campaignsStale(message);
    else{const h=document.getElementById('campaignsBody');if(h)h.innerHTML=`<div class="muted">campaigns unavailable: ${esc(message)} · retrying in ${campaignsRetryTicks*4}s</div>`}
    campaignsRetryTimer=setTimeout(()=>refreshCampaigns(false),campaignsRetryTicks*4000 );
    campaignsRetryTicks=Math.min(8,campaignsRetryTicks*2)}
  finally{campaignsBusy=false}}
function campaignsNotePauses(d){
  const now=Date.now(),pausing=new Set();
  (d&&d.campaigns||[]).forEach(row=>{const id=String(row.campaign_id);
    if(row.state==='pausing')pausing.add(id);
    else if(campaignsPausing.has(id)&&row.state==='paused')campaignsSavedAt[id]=now});
  Object.keys(campaignsSavedAt).forEach(id=>{if(now-campaignsSavedAt[id]>=4000)delete campaignsSavedAt[id]});
  campaignsPausing=pausing}
function campaignStateTitle(row,state){
  if(state==='surveyed'&&row.surveyed&&row.surveyed.reading)return row.surveyed.reading;
  if(state==='done'&&!(row.law_budget&&row.law_budget.law_budget))return `every one of its ${row.laws_total||0} laws is decided and nothing of it is in flight: a campaign fed by hand proposes none, so it has nothing more to run`;
  if(state==='done')return `every one of its ${row.laws_total||0} laws is decided: the law budget is spent and nothing of it is in flight; its workers went to the campaigns still under theirs`;
  if(state==='at its law budget')return 'it proposes no more; the laws it holds go on being measured, and its workers go to the campaigns still under their budget as its work runs out';
  if(state==='pausing')return 'the chains are saving their position so the rung resumes byte-identically, and the analyses of finished rungs are completing';
  return state;}
function campaignPausingNote(row){
  const chains=Number(row.slots_held||0),analyses=Number(row.analyses_running||0),parts=[];
  if(chains||!analyses)parts.push(`${esc(chains)} chain(s) saving`);
  if(analyses)parts.push(`${esc(analyses)} analys${analyses===1?'is':'es'} finishing`);
  return parts.join(' · ');}
function campaignStateNote(row,state){
  if(state==='pausing')return `<div class="muted">${campaignPausingNote(row)}</div>`;
  const saved=campaignsSavedAt[String(row.campaign_id)];
  if(state==='paused'&&saved)return `<div class="saving-done" style="animation-delay:-${Math.min(4000,Date.now()-saved)}ms">saving done</div>`;
  if(state==='surveyed'&&row.surveyed)return `<div class="muted">all ${esc(row.surveyed.held)} laws proposed</div>`;
  return '';}
function campaignVerdictChip(row){
  const v=row.control_verdict;if(!v)return '';
  const cls=v.overall==='pass'?'good':v.overall==='fail'?'bad':'muted';
  const why=(v.laws||[]).map(l=>`${l.label}: ${l.verdict}${l.why&&l.why!=='as expected'?' ('+l.why+')':''}`).join('\n');
  const laws=(v.laws||[]).map(l=>`<div class="control-law ${l.verdict==='pass'?'good':l.verdict==='fail'?'bad':'muted'}" title="${esc(l.what||'')}\n${esc(l.why||'')}"><b>${esc(l.label)}</b> ${esc(l.verdict)}${l.why&&l.why!=='as expected'?` <small>${esc(l.why)}</small>`:''}</div>`).join('');
  return `<div class="${cls} control-verdict" title="${esc(v.criterion+'\n'+why)}">control: <b>${esc(v.overall)}</b></div>${laws}`;}
function campaignOutcomeCell(row){
  const rows=row.stopped_by_rule||[];
  const verdict=campaignVerdictChip(row);
  if(!rows.length)return verdict||'<span class=muted>nothing stopped yet</span>';
  return `<div class="rule-chips">${rows.map(r=>`<span class="rule-chip" title="${esc(r.example||r.rule)}">${esc(r.rule.replace(/_/g,' '))} <b>${esc(Number(r.laws).toLocaleString('en-US'))}</b></span>`).join('')}</div>`+verdict;}
function campaignScoreCell(row){
  const s=row.high_score;
  if(!s)return '<span class=muted title="no landscape has been built for this campaign yet; the reporter writes one per campaign">&mdash;</span>';
  if(s.score==null)return `<span class=muted title="the first law of its Top 100, ${esc(s.candidate_id||'?')}, is not scored yet: the controller reads every decided law a page at a time">not yet</span>`;
  const how=s.score>0?` \u00b7 ${esc(SCORE_WHO[s.by]||s.by||'?')} held to N=${esc(s.to_n)}`:'';
  return `<b class="${s.score>0?'good':'muted'}" title="best of ${esc(s.candidate_id||'?')}, out of ${esc(s.max)}${how} \u00b7 from the landscape built ${esc(s.generated_utc||'at an unknown time')}">${esc(s.score)}</b>`;}
function campaignMeetingCell(row){
  const t=row.meeting_readings||{};
  const order=[['agreeing','agree'],['converging','converging'],['frozen','frozen'],
    ['disagreeing_while_moving','disagreeing'],['not_enough_points','too short']];
  const parts=order.filter(([k])=>t[k]).map(([k,label])=>`<span class="rule-chip">${esc(label)} <b>${esc(t[k])}</b></span>`);
  return parts.length?parts.join(''):'<span class=muted title="no rung carries this reading">&mdash;</span>';}
function campaignComputeCell(row){
  const h=row.compute_hours;
  if(h==null)return '<span class=muted>&mdash;</span>';
  if(h<0.1)return `<span class=muted title="${esc(row.core_seconds)} core-seconds">&lt;0.1h</span>`;
  return `<span title="${esc(row.core_seconds)} core-seconds of attempt wall time">${esc(h)}h</span>`;}
function campaignTermCell(row){
  const terms=row.terms||[];if(!terms.length)return '<span class=muted>none declared</span>';
  const pool=row.hand_fed?`<div class="muted" title="${esc(row.term_pool?'the pool it was created with, which it never draws from: '+row.term_pool.join(', '):'its laws are given, not drawn')}">hand-fed: the terms its laws use</div>`:'';
  return terms.map(op=>`<span class="term-chip" style="--c:${esc(TERMS.color?TERMS.color(op):'#888')}" title="${esc(op)}">${esc(TERMS.label?TERMS.label(op):op)}</span>`).join('')+pool;}
function campaignShareCell(row,pool){
  if(!(row.controls||{}).workers)return `<span class="muted">${esc(row.worker_share)}</span>`;
  const value=row.worker_share==='all'?'':esc(row.worker_share);
  return `<input class="gsd-control share-input" data-admin-write type="number" min="0" max="${esc(pool*4)}" step="1"
    value="${value}" placeholder="all" data-share="${esc(row.campaign_id)}"
    title="simulation slots this campaign may hold at once, out of about ${esc(pool)}. Blank takes whatever is going; 0 pauses it."
  ><div class="muted">${esc(row.slots_held||0)} held${row.work_queued?` &middot; ${esc(row.work_queued)} queued`:''}</div>${campaignAnalysesLine(row)}`;}
function campaignAnalysesLine(row){
  const running=Number(row.analyses_running||0),queued=Number(row.analyses_queued||0);
  if(!running&&!queued)return '';
  return `<div class="muted campaign-analyses" title="analyses of this campaign's finished rungs: the probes read each seed's graphs, in slots of their own beside the chains">analyses ${esc(running)} running${queued?` &middot; ${esc(queued.toLocaleString('en-US'))} queued`:''}</div>`;}
function campaignTemperatureCell(row){
  const t=String(row.temperature||'finite');
  return t==='zero'?'<span class="regime-chip regime-zero_temperature" title="zero temperature: only moves that do not raise the energy">zero</span>'
    :t==='both'?'<span class="regime-chip" title="each law draws finite or zero temperature">both</span>'
    :'<span class="regime-chip" title="finite temperature: Metropolis at the law’s beta">finite</span>';}
function degreeWindowText(w){
  if(!w||w.max==null)return '—';
  const f=x=>Number(x).toLocaleString('en-US',{maximumFractionDigits:2});
  return `${f(w.min==null?0:w.min)} to ${f(w.max)}`;}
function campaignDegreeCell(row){
  return `<span title="the mean-degree window a chain is held inside; from N=256 the engine stops a law at its top">${esc(degreeWindowText(row.mean_degree_window))}</span>`;}
function campaignGraphsLine(row){
  const n=v=>esc(Number(v||0).toLocaleString('en-US'));
  const finished=row.graphs_finished==null?'':`<span title="graphs the campaign has: each seed of each law at a rung once, however many simulations ran it">${n(row.graphs_finished)} graphs</span> &middot; `;
  return `<div class="muted">${finished}<span title="simulations finished: every finished simulation of every seed of every law, at every rung (a seed run again, as a longer chain, counts again)">${n(row.graphs_total)} simulations</span></div>`;}
function hoursText(h){if(h==null)return 'unknown';const v=Number(h);if(v<1)return `${Math.round(v*60)} min`;if(v<48)return `${v.toFixed(1)} h`;return `${(v/24).toFixed(1)} days`}
function campaignWorkLine(row){
  const w=row.work_left;if(!w)return '';
  if(!w.graphs_queued&&!w.laws_to_budget)return '<div class="muted work-left">nothing queued</div>';
  const n=x=>Number(x||0).toLocaleString('en-US');
  const tip=`at least: ${n(w.graphs_queued)} seeds queued (${Object.entries(w.queued_by_n||{}).map(([k,v])=>`N=${n(k)} ${n(v)}`).join(', ')||'none'}) priced at ${w.queued_core_hours} core-h by what a seed took at each rung here`
    +(w.laws_to_budget?`; ${n(w.laws_to_budget)} laws to the budget at ${w.core_hours_a_law} core-h a law so far, ${w.laws_core_hours} core-h`:'')
    +`; analyses at ${Math.round(100*(w.analysis_ratio||0))}% of the simulation time. Last hour: ${w.cores_last_hour} cores; a fair share: ${w.share_cores==null?'none (not running)':w.share_cores+' cores'}.`
    +((w.unpriced_rungs||[]).length?` Not priced, no seed finished there yet: N=${w.unpriced_rungs.map(n).join(', ')}.`:'')
    +((w.rungs_priced_at_a_floor||[]).length?` Priced at a floor, most seeds reach their budget: N=${w.rungs_priced_at_a_floor.map(n).join(', ')}.`:'');
  const climbing=+w.laws_climbing||0,refill=climbing?`${n(climbing)} law${climbing===1?'':'s'} still climbing: each rung one earns queues its seeds (four times the size of the last), and a rung whose seeds disagree or fail asks for more, so this count can rise again until every one of them stops, settles or reaches the top. `:'';
  return `<div class="work-left" title="${esc(refill+tip)}"><div><b>${n(w.graphs_queued)}</b> graphs queued</div>${climbing?`<div class=muted>${n(climbing)} law${climbing===1?'':'s'} still climbing</div>`:''}${+w.core_hours_expected>+w.core_hours_left?`<div class=muted title="the queued seeds at their size's mean time, which the slow seeds raise above the median, and the sizes the laws still climbing are expected to buy, from the share of laws that went on at each size">about ${esc(Number(w.core_hours_expected).toFixed(1))} core-h with the sizes to come</div>`:''}${+w.core_hours_left>0||!(w.unpriced_rungs||[]).length?`<div>&ge;${esc(Number(w.core_hours_left).toFixed(1))} core-h left</div><div class=muted>&ge;${esc(hoursText(w.hours_at_last_hours_pace))} &middot; last hour's pace</div><div class=muted>&ge;${esc(hoursText(w.hours_at_fair_share))} &middot; a fair share</div>`:`<div class=muted>${esc(notPriced(w.unpriced_rungs).replace(/^ \u00b7 /,''))}</div>`}</div>`;}
function studyWorkLine(d){
  const w=d&&d.work_left;if(!w||!w.campaigns)return '';
  return `<div class="muted work-left-study" title="every campaign still at work: its work left summed, at the fleet's pace in the last hour (${esc(w.cores_last_hour)} cores) and at the whole pool (${esc(w.pool)} slots); at least, since the rungs a settled rung buys are not queued yet">the study: &ge;${esc(Number(w.core_hours_left).toFixed(1))} core-hours left in ${esc(w.campaigns)} campaign(s) &middot; &ge;${esc(hoursText(w.hours_at_last_hours_pace))} at the last hour's pace &middot; &ge;${esc(hoursText(w.hours_at_the_whole_pool))} on the whole pool${+w.core_hours_expected>+w.core_hours_left?` &middot; about ${esc(Number(w.core_hours_expected).toFixed(1))} core-hours with the sizes to come${+w.hours_expected_at_last_hours_pace>0?`, ${esc(hoursText(w.hours_expected_at_last_hours_pace))} at the last hour's pace`:''}`:''}</div>`;}
function campaignLawsCell(row){
  const b=row.law_budget;
  if(!b)return `${esc(Number(row.laws_total||0).toLocaleString('en-US'))} laws${campaignGraphsLine(row)}`;
  return `<input class="gsd-control share-input" data-admin-write type="number" min="1" step="1" value="${esc(b.law_budget)}" data-budget="${esc(row.campaign_id)}"
    title="laws this campaign tries before it proposes no more; its laws go on being measured and its workers go to the campaigns still under their budget. Blank takes the budget away.">
    <div class="muted">${esc(Number(b.laws_held||0).toLocaleString('en-US'))} of ${esc(Number(b.law_budget).toLocaleString('en-US'))} laws${b.done?' &middot; done':b.reached?' &middot; proposing no more':''}</div>${campaignGraphsLine(row)}`;}
function campaignActionButton(row,action,label,title){
  if(!(row.controls||{})[action])return '';
  return `<button type="button" class="gsd-control" data-admin-write data-campaign="${esc(row.campaign_id)}" data-action="${esc(action)}" title="${esc(title)}">${esc(label)}</button>`;}
function autoExtendControl(a){
  if(!a)return '';
  const laws=Number(a.laws||50),last=a.last,moved=last&&last.campaigns?Object.keys(last.campaigns).length:0;
  const when=last&&last.at?(SYS.localTimeHtml?SYS.localTimeHtml(last.at):esc(last.at)):'';
  return `<label class="muted" title="${esc(`Off unless ticked. When on: once every campaign with a law budget is finished (every law drawn and decided, nothing in flight), each of them gets ${laws} more laws and the fleet runs on; again each time they finish, until this is unticked or the fleet is stopped. The new laws are drawn the way the first ones were, from each campaign's own seed.`)}"><input type="checkbox" id="autoExtend"${a.on?' checked':''}> auto extend: ${laws} more laws a campaign each time all are finished</label>${moved?`<span class="muted"> &middot; last extended ${when}: ${moved} campaign${moved===1?'':'s'}</span>`:''}`;}
function renderCampaigns(d){
  const host=document.getElementById('campaignsBody');if(!host)return;
  registerLiveRegion(host);if(deferrableRedraw(host,()=>renderCampaigns(d)))return;
  if(!d||!d.campaigns){host.innerHTML='<div class=empty>no campaign has been created in this folder yet</div>';return}
  if(!d.campaigns.length){host.innerHTML='<div class=empty>no campaign has been created in this folder yet. Start the first one with <code>main.py campaign start --spec campaign_engine_survey.json</code>, then clone it here.</div>';return}
  const err=campaignActionError?`<div class="alert-box warn">${esc(campaignActionError)}</div>`:'';
  const rows=d.campaigns.map(row=>{
    const state=String(row.state||'');
    return `<tr data-campaign-row="${esc(row.campaign_id)}"${row.campaign_id===campaignSelected?' class="selected"':''}>
      <td class="mono"><a href="#" data-open-campaign="${esc(row.campaign_id)}">${esc(row.campaign_id)}</a>${row.parent_campaign_id?`<div class="muted">from ${esc(row.parent_campaign_id)}</div>`:''}</td>
      <td class="state"><span class="report-badge ${esc(CAMPAIGN_STATE_CLASS[state]||'idle')}" title="${esc(campaignStateTitle(row,state))}">${esc(state)}</span>${campaignActionButton(row,'pause','pause','stop this campaign spending the fleet, keeping its work')}${campaignActionButton(row,'resume','resume','let it claim work again')}${campaignActionButton(row,'reopen','reopen','bring a closed campaign back with its own seed')}${campaignActionButton(row,'delete','delete','remove this campaign and everything it measured, permanently')}${campaignStateNote(row,state)}</td>
      <td>${SYS.localTimeHtml?SYS.localTimeHtml(row.created_utc,{dateOnly:true}):esc(row.created_utc||'')}</td>
      <td class="num share">${campaignShareCell(row,d.worker_pool||0)}</td>
      <td>${campaignTermCell(row)}</td>
      <td>${campaignTemperatureCell(row)}</td>
      <td class="num">${campaignDegreeCell(row)}</td>
      <td class="num share">${campaignLawsCell(row)}</td>
      <td class="work">${campaignWorkLine(row)}</td>
      <td class="num">${campaignScoreCell(row)}</td>
      <td class="outcome">${campaignOutcomeCell(row)}</td>
      <td class="num">${campaignComputeCell(row)}</td>
      <td class="num" title="laws whose latest engine decision was a hold: alive and waiting on a gate, not failed">${esc(row.held||0)}</td>
      <td class="given_chains">${campaignMeetingCell(row)}</td>
    </tr>`}).join('');
  host.innerHTML=`${err}<section class="panel">${studyWorkLine(d)}<div class="table-scroll"><table class="campaign-table">
  <colgroup><col class="c-id"><col class="c-state"><col class="c-date"><col class="c-workers"><col class="c-termset"><col class="c-temp"><col class="c-degree"><col class="c-laws"><col class="c-work"><col class="c-score"><col class="c-outcome"><col class="c-compute"><col class="c-held"><col class="c-meetings"></colgroup>
  <thead><tr>
    <th>campaign</th><th title="what the campaign is doing, and the control that changes it">state</th><th>started</th><th class="num">workers</th><th>term set</th><th title="the temperature its laws draw: finite (Metropolis at the law's beta), zero (only moves that do not raise the energy), or both">temperature</th><th class="num" title="the mean-degree window a chain is held inside; from N=256 the engine stops a law at its top (too dense)">mean degree</th>
    <th class="num" title="laws the campaign has tried, and its law budget where it has one (533): at the budget it proposes no more; under it, the graphs its laws grew (542)">laws &middot; graphs</th><th title="the work queued and when it should be done, from what this campaign has recorded (544); every figure is a floor">work left</th><th class="num" title="the best score this campaign has produced, who built a space times how far it held (608), from the landscape the reporter last built. It is not rebuilt for this page.">high&nbsp;score</th><th title="why the engine stopped the laws it stopped: what this term set and grid actually bought">what stopped the laws</th><th class="num" title="core-hours of attempt wall time, successful or not, on the same basis as the System page's compute tile">compute</th><th class="num" title="laws whose latest engine decision was a hold">held</th><th title="what the comparison of each law's chains says at its deepest rung: agreeing, converging (out of budget, not stuck), frozen (depends on the start), disagreeing while moving. A reading, not a verdict: nothing decides on it (513)">chains meet</th>
  </tr></thead><tbody>${rows}</tbody></table></div>
  <div class="toolbar"><button type="button" class="gsd-control" data-admin-write data-fleet="${d.fleet_paused?'fleet_resume':'fleet_pause'}">${d.fleet_paused?'resume the fleet':'stop the fleet'}</button>
    <label class="muted"><input type="checkbox" id="campaignFence"${campaignFenceNext?' checked':''}> pause fast, discarding the rungs in flight</label>
    ${autoExtendControl(d.auto_extend)}
    <span class="muted">${d.fleet_paused?'every campaign is stopped and every leased job is back in its queue':'stopping the fleet returns every leased job to its queue at once, so those rungs start again from the beginning. A campaign pause instead saves each rung where it is, which is why it takes a few seconds per chain.'}</span></div>
  <div class="muted">${esc(d.reading||'')}</div></section>`;
  host.querySelectorAll('[data-action]').forEach(b=>{b.onclick=()=>campaignAction(b.dataset.campaign,b.dataset.action)});
  host.querySelectorAll('[data-fleet]').forEach(b=>{b.onclick=()=>fleetAction(b.dataset.fleet)});
  const fence=document.getElementById('campaignFence');
  if(fence)fence.onchange=()=>{campaignFenceNext=!!fence.checked};
  const extend=document.getElementById('autoExtend');
  if(extend)extend.onchange=async()=>{const on=!!extend.checked;
    try{await manageCampaign({action:'auto_extend',on});await refreshCampaigns(true)}catch(_){extend.checked=!on}};
  host.querySelectorAll('[data-share]').forEach(input=>{input.onchange=async()=>{
    const raw=String(input.value).trim();
    try{await manageCampaign({action:'workers',campaign_id:input.dataset.share,
      workers_target:raw===''?'all':Number(raw)});await refreshCampaigns(true)}catch(_){}}});
  host.querySelectorAll('[data-budget]').forEach(input=>{input.onchange=async()=>{
    const raw=String(input.value).trim();
    if(raw===''&&!askFirst(`Clear campaign ${input.dataset.budget}'s law budget of ${input.defaultValue}?\n\nIt will propose `
       +'laws again with no limit, and the page does not keep the old number.')){input.value=input.defaultValue;return}
    try{await manageCampaign({action:'budget',campaign_id:input.dataset.budget,
      law_budget:raw===''?'none':Number(raw)});await refreshCampaigns(true)}catch(_){}}});
  host.querySelectorAll('[data-open-campaign]').forEach(a=>{a.onclick=ev=>{ev.preventDefault();openCampaignPanel(a.dataset.openCampaign)}});}
const rungsInFlight=id=>((campaignsData&&campaignsData.campaigns)||[]).filter(r=>id==null||String(r.campaign_id)===String(id))
  .reduce((sum,r)=>sum+Number(r.slots_held||0),0);
const askFirst=text=>(typeof confirm==='function')?confirm(text):false;
async function fleetAction(action){
  if(fleetBusy)return;
  if(action==='fleet_pause'&&!askFirst(`Stop the fleet?\n\n${rungsInFlight(null)} rung(s) in flight will be discarded `
     +'and start again from the beginning. A campaign pause saves each rung where it is instead.'))return;
  fleetBusy=true;
  try{await manageCampaign({action});await refreshCampaigns(true)}catch(_){}finally{fleetBusy=false}}
async function campaignAction(id,action){
  if(action==='author')return openCampaignAuthor(id);
  if(action==='delete')return deleteCampaign(id);
  const body={action,campaign_id:id};
  if(action==='pause'&&campaignFenceNext){
    if(!askFirst(`Pause campaign ${id} fast?\n\n${rungsInFlight(id)} rung(s) in flight will be discarded and start `
       +'again from the beginning. Untick "pause fast" to save them instead.'))return;
    body.fence=true;campaignFenceNext=false;}
  try{await manageCampaign(body);await refreshCampaigns(true)}catch(_){}}
async function deleteCampaign(id){
  const row=((campaignsData&&campaignsData.campaigns)||[]).find(r=>String(r.campaign_id)===String(id))||{};
  const typed=(typeof prompt==='function')?prompt(
    `Delete campaign ${id} permanently?\n\nThis removes its ${row.laws_total||0} laws, their decisions and measurements, `
    +`and ${row.compute_hours||0} core-hours of results from the database. It cannot be undone.\n\nType ${id} to confirm.`):null;
  if(typed===null||String(typed).trim()!==String(id))return;
  try{await manageCampaign({action:'delete',campaign_id:id,confirm:String(typed).trim()});
    if(String(campaignSelected)===String(id)){campaignSelected=null;const h=document.getElementById('campaignPanel');if(h)h.innerHTML=''}
    await refreshCampaigns(true);
    if(SYS.refreshCampaignList)await SYS.refreshCampaignList()}catch(_){}}
async function openCampaignPanel(id){
  campaignSelected=id;const host=document.getElementById('campaignPanel');if(!host)return;
  try{campaignPanelData=await get('/api/campaigns/panel/'+encodeURIComponent(id))}
  catch(e){host.innerHTML=`<div class="muted">campaign ${esc(id)} unavailable: ${esc(String(e&&e.message||e))}</div>`;return}
  renderCampaignPanel(campaignPanelData);}
function campaignDefinitionHtml(row){
  const saved=[authorParent,authorTerms,authorGrid,authorCheck,authorReadOnly],grid=row.grid||{};
  try{
    authorParent=String(row.campaign_id);authorTerms=new Set(row.terms||[]);authorReadOnly=true;
    authorGrid=grid.per_term?{per_term:grid.per_term}:{};
    authorCheck={grid,complexity_budget:row.complexity_budget};
    const html=authorPerTermHtml()+authorBetaHtml()+authorDynamicsHtml()+authorGridHtml();
    return html.replace(/<button\b/g,'<button disabled').replace(/<input\b/g,'<input readonly');
  }finally{[authorParent,authorTerms,authorGrid,authorCheck,authorReadOnly]=saved}}
function campaignSaltText(def){
  const pct=x=>`${Math.round(1000*Number(x||0))/10}%`,shares=def.salt_shares||[];
  if(!shares.length)return pct(def.salt);
  const confirmed=shares.filter(s=>Number(s[1])<=0.01).length+shares.filter(s=>Number(s[2])<=0.01).length;
  return `per gate: ${confirmed} of ${2*shares.length} gate stops confirmed`;}
function campaignSaltWhy(def){
  const pct=x=>`${Math.round(1000*Number(x||0))/10}%`,shares=def.salt_shares||[];
  if(!shares.length)return 'every gate lets this share of the laws it would stop go on, so each gate is measured on its own sample (533)';
  return 'each gate lets its own share through, set when the study began from what it had let through before (554): 50% up to 4,096 and 10% from 16,384 while testing, 1% once confirmed. '
    +shares.map(s=>`${esc(s[0])} ${pct(s[1])} / ${pct(s[2])}`).join(' · ');}
function campaignLimitsHtml(def){
  const n=x=>x==null?'—':Number(x).toLocaleString('en-US'),w=def.mean_degree_window||{},b=def.law_budget||{};
  const budgets=(def.work_budgets||[]).map(([at,units,sec])=>`<span title="${esc(sec?`about ${budgetText(sec)} where the unit was fitted`:'')}">${n(at)}: ${esc(unitsText(units)||'—')}</span>`).join(' · ');
  const row=(k,v,why)=>`<tr><td>${k}</td><td><b>${v}</b></td><td class="muted">${why}</td></tr>`;
  return `<h3>Limits and the ladder</h3><table class="definition-table"><tbody>
    ${row('mean degree window',esc(degreeWindowText(w)),`a chain is held inside it; from N=${n(def.dense_from_n)} the engine stops a law at a mean degree of ${n(def.dense_cap)} or more (too dense)`)}
    ${row('empty',esc(n(def.empty_mean_degree)),`a law whose mean degree stays at or under this at every rung is stopped, from N=${n(def.empty_from_n)}`)}
    ${row('connectivity floor',esc(n(def.connectivity_floor)),`a largest component under this share of the graph, and not growing, stops a law from N=${n(def.connectivity_from_n)}`)}
    ${row('the let-through',campaignSaltText(def),campaignSaltWhy(def))}
    ${row('ladder',(def.ladder||[]).map(n).join(', '),`budgets in units of work per rung, fixed in the design: ${budgets||'—'}`)}
    ${row('complexity budget',esc(n(def.complexity_budget)),'the most a law\u2019s terms may cost together')}
    ${row('law budget',b.law_budget?`${n(b.laws_held)} of ${n(b.law_budget)}`:'none','this and the share of the fleet are what can still change, in the table above')}
    ${def.search_seed!=null?row('search seed',esc(String(def.search_seed)),'the draws are reproducible from it'):''}
  </tbody></table>`;}
function campaignFrozenHtml(rows){
  if(!(rows||[]).length)return '';
  const differ=rows.filter(r=>!r.shipped_default).length;
  const body=rows.map(r=>{const text=JSON.stringify(r.value);
    return `<tr class="${r.shipped_default?'':'differs'}"><td><code>${esc(r.field)}</code></td><td class="muted">${esc(r.reading)}</td>
      <td><code title="${esc(text)}">${esc(text.length>90?text.slice(0,88)+'…':text)}</code></td><td>${r.shipped_default?'<span class="muted">shipped default</span>':'<b>differs</b>'}</td></tr>`}).join('');
  return `<details class="inherited"><summary>Everything else it was frozen with: ${rows.length} fields, ${differ?`<b>${differ} differ from the shipped defaults</b>`:'all of them the shipped defaults'}</summary>
    <table class="inherited-table"><thead><tr><th>field</th><th>what it is</th><th>value</th><th></th></tr></thead><tbody>${body}</tbody></table></details>`;}
function renderCampaignPanel(d){
  const host=document.getElementById('campaignPanel');if(!host)return;
  if(!d||d.available===false){host.innerHTML=`<div class="muted">${esc(d&&d.reason||'no campaign selected')}</div>`;return}
  const c=d.campaign||{},def=d.definition||{},terms=c.terms||[];
  const termList=terms.map(op=>`<span class="term-chip" style="--c:${esc(TERMS.color?TERMS.color(op):'#888')}" title="${esc(op)}">${esc(TERMS.label?TERMS.label(op):op)}</span>`).join('')||'<span class=muted>none</span>';
  const diff=d.term_diff?`<div class="muted">against its parent: ${esc(d.term_diff.summary)}</div>`:'';
  const ladder=(c.rungs||[]).map(r=>`<tr><td class="num">${esc(r.n)}</td><td class="num">${esc(r.laws)}</td><td class="num">${esc(r.graphs==null?'':r.graphs)}</td><td class="num">${esc(r.measured)}</td><td class="num">${r.ceiling?esc(r.ceiling):'<span class=muted>&mdash;</span>'}</td></tr>`).join('')
    ||'<tr><td colspan=5 class="muted">no rung bought yet</td></tr>';
  const states=Object.entries(c.laws_by_state||{}).map(([k,v])=>`<tr><td>${esc(k)}</td><td class="num">${esc(v)}</td></tr>`).join('')
    ||'<tr><td colspan=2 class="muted">no law admitted yet</td></tr>';
  const events=(d.events||[]).slice().reverse().slice(0,18).map(e=>`<tr><td>${SYS.localTimeHtml?SYS.localTimeHtml(e.created_utc):esc(e.created_utc||'')}</td><td class="mono">${esc(e.event_type)}</td></tr>`).join('')
    ||'<tr><td colspan=2 class="muted">no event recorded</td></tr>';
  const summary=[campaignTemperatureCell({temperature:def.temperature||c.temperature})+' temperature',
    `mean degree <b>${esc(degreeWindowText(def.mean_degree_window||c.mean_degree_window))}</b>`,
    `${esc(c.term_count||terms.length)} terms`].join(' · ');
  host.innerHTML=`<section class="panel"><div class="panel-title-row"><div><h2>Campaign ${esc(c.campaign_id)}${(def.quadrant||c.quadrant)?` <span class="muted">· ${esc(def.quadrant||c.quadrant)}</span>`:''}</h2>
    <div class="muted">${esc(c.change_reason||'')}</div></div>
    <div class="toolbar"><button type="button" class="gsd-control" id="campaignPanelClose">close</button></div></div>
    <div class="definition-summary">${summary}</div>
    <div class="muted">As it was created, read-only: a campaign is frozen at creation, so a different setting is a new campaign (<b>new campaign</b> starts from this one). Its share of the fleet and its law budget are what can change, in the table above.</div>
    <h3>Term set (${esc(c.term_count||0)})</h3>${termList}${diff}
    ${((c.controls||{}).delete_problems||[]).length?`<div class="muted">not deletable yet: ${esc(c.controls.delete_problems.join('; '))}</div>`:''}
    <div class="campaign-definition">${campaignDefinitionHtml(c)}</div>
    ${campaignLimitsHtml(def)}
    ${campaignFrozenHtml(d.frozen)}
    <details class="campaign-run"><summary>What ran: laws per rung, law states and the lifecycle</summary>
    <div class="two-col">
      <div><h3>Ladder</h3><table><thead><tr><th class="num">N</th><th class="num">laws</th><th class="num" title="graphs grown at this N: finished simulations (542)">graphs</th><th class="num">measured</th><th class="num" title="the most a law reaching this rung can score: a space built from empty and held to it (608)">score ceiling</th></tr></thead><tbody>${ladder}</tbody></table></div>
      <div><h3>Law states</h3><table><tbody>${states}</tbody></table></div>
    </div>
    <div><h3>Lifecycle</h3><table><tbody>${events}</tbody></table></div></details>
    <div class="muted">science contract <code>${esc(String(c.science_contract_hash||'').slice(0,16))}</code>. Two campaigns with different term sets have different science contracts and are read side by side rather than pooled.</div>
  </section>`;
  const close=document.getElementById('campaignPanelClose');
  if(close)close.onclick=()=>{campaignSelected=null;host.innerHTML=''};}
async function openCampaignAuthor(parentId){
  authorParent=parentId;authorCheck=null;authorRequestId=null;
  const parent=authorParentRow();
  authorTerms=new Set(parent.terms||[]);authorGrid={};authorWindow=null;
  const host=document.getElementById('campaignAuthor');if(host)host.hidden=false;
  renderCampaignAuthor();await checkCampaignAuthor();}
const GRID_SCALES=['one','log_N','inv_log_N','inv_N','inv_sqrt_N','power'];
function authorParentRow(){
  if(authorParent==='defaults'){const d=(campaignsData&&campaignsData.defaults)||{};
    return {campaign_id:'defaults',terms:[],grid:d.grid,complexity_budget:d.complexity_budget}}
  return (campaignsData&&(campaignsData.campaigns||[]).find(r=>r.campaign_id===authorParent))||{};}
function authorParentGrid(){
  return (authorCheck&&authorCheck.grid)||authorParentRow().grid||{};}
function authorGridValue(key){
  const g=authorParentGrid();
  return authorGrid[key]!==undefined?authorGrid[key]:(g[key]||[]);}
function gridText(entry){
  if(entry&&typeof entry==='object'&&!Array.isArray(entry))return `${entry.min}..${entry.max}`;
  return (entry||[]).join(', ');}
function gridIsInterval(entry){
  return !!(entry&&typeof entry==='object'&&!Array.isArray(entry));}
function gridSpacing(entry){
  return gridIsInterval(entry)?String(entry.spacing||(Number(entry.min)>0?'log':'linear')):null;}
function authorNotes(v){
  const s=v.space||{};
  const notes=(v.notes||[]).filter(n=>!(s.continuous&&String(n).includes('no last law')));
  return notes.length?notes.map(esc).join(' '):'No caveats.';}
function authorSpaceLine(v){
  const s=v.space||{};
  if(s.distinct_physical===undefined)return 'this selection draws laws.';
  const n=s.distinct_physical,pool=v.pool_min;
  if(s.continuous)return `this selection draws its coupling from an interval, so it has no last law (${n} distinct in ${s.draws} draws).`;
  const size=s.exhaustive?`${n} physically distinct laws`:`at least ${n} distinct laws, and the sample has not seen the end of the space`;
  return `this selection can write ${size}${pool?`, against a pool of ${pool}`:''}.`;}
function authorAdviceHtml(v){
  const rows=v.advice||[];
  if(!rows.length)return '';
  return `<div class="muted">What would widen it, measured on this grid: ${rows.map(r=>{
    const to=r.continuous?'no limit':(r.to===null||r.to===undefined?'':r.to);
    return `<span class="rule-chip" title="${esc(r.detail)}">${esc(r.change)}${to===''?'':` <b>${esc(r.from)}&rarr;${esc(to)}</b>`}</span>`}).join('')}</div>`;}
const SIGN_CHOICES=[['both','\u00b1'],['positive','+'],['negative','\u2212']];
function authorTermGrid(op){return ((authorGrid.per_term||{})[op])||{};}
function authorSetTermGrid(op,patch){
  const per=Object.assign({},authorGrid.per_term||{});
  const next=Object.assign({},per[op]||{},patch);
  Object.keys(next).forEach(k=>{if(next[k]===null)delete next[k]});
  if(Object.keys(next).length)per[op]=next;else delete per[op];
  if(Object.keys(per).length)authorGrid.per_term=per;else delete authorGrid.per_term;
  renderCampaignAuthor();checkCampaignAuthor();}
function authorSignOf(own){
  const signs=own.signs;
  if(!Array.isArray(signs)||signs.length!==1)return 'both';
  return signs[0]>0?'positive':'negative';}
function rfGet(target){
  return target.startsWith('term:')?authorTermGrid(target.slice(5)).magnitudes:authorGridValue(target.slice(5));}
function rfInherited(target){return target.startsWith('term:')?authorGridValue('magnitudes'):null;}
function rfSet(target,value){
  if(target.startsWith('term:')){authorSetTermGrid(target.slice(5),{magnitudes:value});return}
  const key=target.slice(5);
  if(value===null)delete authorGrid[key];else authorGrid[key]=value;
  renderCampaignAuthor();checkCampaignAuthor();}
const RF_FIELDS={
  'grid:localities':{ok:n=>n>=0&&n<1,range:{min:0,max:0.99,spacing:'linear'},values:[0.5,0.9],
    isOff:e=>!gridIsInterval(e)&&!(e||[]).some(v=>Number(v)>0),offValue:()=>[0],
    offLabel:'off',offText:()=>'every move is global',offTitle:'no local moves'},
  'grid:swap_shares':{ok:n=>n>=0&&n<1,range:{min:0,max:0.99,spacing:'linear'},values:[0],
    isOff:e=>!gridIsInterval(e)&&!(e||[]).length,offValue:()=>[Number((authorGridValue('move_mix')||{}).swap??0.15)],
    offLabel:'fixed',offText:()=>{const m=authorParentGrid().move_mix||{};return `every law uses the campaign's move mix, ${Math.round(100*Number(m.swap??0.15))}% swaps`},
    offTitle:'the move mix the campaign carries'},
  'grid:power_exponents':{ok:n=>n>=-2&&n<=2,range:{min:-2,max:2,spacing:'linear'},values:[-1,-0.5,0.5,1]},
  'grid:anchor_k':{ok:n=>n>=1&&Number.isInteger(n),range:{min:2,max:32,spacing:'linear'},values:[4,8]},
};
function rfField(target){return RF_FIELDS[target]||{ok:n=>n>0};}
function rfMode(entry,target){
  const f=rfField(target);
  if(f.isOff&&f.isOff(entry))return 'off';
  return entry===undefined||entry===null?'default':(gridIsInterval(entry)?'range':'values');}
function rfSwitch(target,mode){
  const f=rfField(target);
  if(mode==='default'){rfSet(target,null);return}
  if(mode==='off'){rfSet(target,authorParentGrid()[target.slice(5)]!==undefined?f.offValue():null);return}
  const cur=rfGet(target),off=f.isOff&&f.isOff(cur);
  const base=(cur===undefined||cur===null||off)?rfInherited(target):cur;
  if(mode==='range'){
    if(gridIsInterval(base)){rfSet(target,Object.assign({},base));return}
    const xs=(base||[]).map(Number).filter(n=>isFinite(n)&&f.ok(n));
    if(!xs.length){rfSet(target,Object.assign({},f.range||{min:0.01,max:1}));return}
    const lo=Math.min(...xs),hi=Math.max(...xs);
    rfSet(target,hi>lo?{min:lo,max:hi}:Object.assign({},f.range||{min:lo,max:lo*10}));return}
  if(gridIsInterval(base)){rfSet(target,[Number(base.min),Number(base.max)]);return}
  const xs=(base||[]).slice();
  rfSet(target,xs.length?xs:(f.values||[]).slice());}
function rangeFieldHtml(target){
  const f=rfField(target),entry=rfGet(target),inherited=rfInherited(target),mode=rfMode(entry,target);
  const modes=(inherited!==null?['default']:[]).concat(f.isOff?['off']:[],['range','values']);
  const pills=modes.map(m=>`<button type="button" class="filter-pill${mode===m?' active':''}" data-rf-mode="${esc(target)}|${m}" title="${m==='default'?'use the campaign default below':m==='off'?esc(f.offTitle):m==='range'?'draw continuously between a minimum and a maximum':'draw only these values'}">${m==='off'?esc(f.offLabel):m}</button>`).join('');
  let body;
  if(mode==='default')body=`<span class="muted rf-default">${esc(gridText(inherited))}</span>`;
  else if(mode==='off')body=`<span class="muted rf-default">${esc(f.offText())}</span>`;
  else if(mode==='range'){
    const sp=gridSpacing(entry),crosses=Number(entry.min)<=0;
    body=`<span class="rf-range"><label>min <input type="number" step="any" class="gsd-control" data-rf-part="${esc(target)}|min" value="${esc(entry.min)}"></label>
      <label>max <input type="number" step="any" class="gsd-control" data-rf-part="${esc(target)}|max" value="${esc(entry.max)}"></label>
      ${['log','linear'].map(m=>`<button type="button" class="filter-pill${sp===m?' active':''}" data-rf-spacing="${esc(target)}|${m}"${m==='log'&&crosses?' disabled title="a range through zero cannot be log-spaced"':` title="${m==='log'?'draw evenly across decades':'draw evenly across the range'}"`}>${m}</button>`).join('')}</span>`;}
  else body=`<input type="text" class="gsd-control rf-list" data-rf-part="${esc(target)}|list" value="${esc((entry||[]).join(', '))}" placeholder="0.05, 0.1, 0.2">`;
  return `<div class="rf"><span class="rf-modes">${pills}</span>${body}</div>`;}
function authorWireRangeFields(host){
  host.querySelectorAll('[data-rf-mode]').forEach(b=>{b.onclick=()=>{
    const [target,mode]=b.dataset.rfMode.split('|');rfSwitch(target,mode)}});
  host.querySelectorAll('[data-rf-spacing]').forEach(b=>{b.onclick=()=>{
    const [target,mode]=b.dataset.rfSpacing.split('|');
    rfSet(target,Object.assign({},rfGet(target)||{},{spacing:mode}))}});
  host.querySelectorAll('[data-rf-part]').forEach(box=>{box.onchange=()=>{
    const [target,part]=box.dataset.rfPart.split('|');
    const ok=rfField(target).ok;
    if(part==='list'){rfSet(target,String(box.value||'').split(/[,\s]+/).filter(Boolean).map(Number).filter(n=>isFinite(n)&&ok(n)));return}
    const n=Number(box.value);if(!isFinite(n))return;
    rfSet(target,Object.assign({},rfGet(target)||{},{[part]:n}))}});}
function authorInheritedSign(){
  const signs=authorGridValue('signs');
  if(!Array.isArray(signs)||signs.length!==1)return 'both';
  return signs[0]>0?'positive':'negative';}
function authorPerTermHtml(){
  const ops=[...authorTerms];
  if(!ops.length)return '<h3>Terms</h3><div class="muted">select at least one term above</div>';
  const defaultMags=authorGridValue('magnitudes'),defaultScales=authorGridValue('scales');
  const defaultSign=authorInheritedSign();
  const rows=ops.map(op=>{
    const own=authorTermGrid(op);
    const ownSign=own.signs!==undefined,ownScales=Array.isArray(own.scales);
    const sign=ownSign?authorSignOf(own):defaultSign;
    const scales=ownScales?own.scales:defaultScales;
    const setCount=Object.keys(own).length;
    return `<tr class="${setCount?'set':'inherits'}"><td><span class="term-chip" style="--c:${esc(TERMS.color?TERMS.color(op):'#888')}" title="${esc(op)}">${esc(TERMS.label?TERMS.label(op):op)}</span>
        <div class="muted">${setCount?'own settings':'campaign defaults'}</div></td>
      <td>${rangeFieldHtml('term:'+op)}</td>
      <td>${SIGN_CHOICES.map(([k,label])=>`<button type="button" class="filter-pill${sign===k?(ownSign?' active':' inherit'):''}" data-term-sign="${esc(op)}:${esc(k)}" title="${k==='both'?'either sign':'pin the coefficient '+k}${!ownSign&&sign===k?' · the campaign default':''}">${esc(label)}</button>`).join('')}</td>
      <td>${GRID_SCALES.map(sc=>`<button type="button" class="filter-pill${scales.indexOf(sc)>=0?(ownScales?' active':' inherit'):''}" data-term-scale="${esc(op)}:${esc(sc)}">${esc(sc)}</button>`).join('')}${ownScales?`<button type="button" class="filter-pill" data-term-scale="${esc(op)}:*" title="go back to the campaign default">default</button>`:''}</td></tr>`}).join('');
  return `<h3>Terms</h3>
    <div class="muted">Each term's coefficient: its magnitude, its sign, and how it scales with N. A dimmed value is the campaign default below; set one to override it for that term only. The energy is minimised, so a reward is a <b>&minus;</b> coefficient: the founder Hamiltonian is <code>edge</code> at 1 with sign &minus;, and <code>&Sigma;d&sup2;</code> free with sign +.</div>
    <table class="per-term-table"><thead><tr><th>term</th><th>magnitude</th><th>sign</th><th>scales</th></tr></thead><tbody>${rows}</tbody></table>
    ${authorTermCountsHtml()}`;}
function authorTermCap(){
  const budget=Number((authorCheck&&authorCheck.complexity_budget)||authorParentRow().complexity_budget||7);
  const cat=(campaignsData&&campaignsData.terms)||[],items=[];
  [...authorTerms].forEach(op=>{
    const t=cat.find(x=>x.op===op)||{},cost=Math.max(1,Number(t.cost)||1);
    const repeats=Object.keys(t.params||{}).length?Math.floor(budget/cost):1;
    for(let i=0;i<repeats;i++)items.push(cost)});
  items.sort((a,b)=>a-b);let n=0,spent=0;
  for(const c of items){if(spent+c>budget)break;spent+=c;n++}
  return {max:Math.max(1,n),budget};}
function authorTermCountsHtml(){
  const counts=authorGridValue('term_counts'),own=authorGrid.term_counts!==undefined;
  const lo=counts.length?Math.min(...counts):1,hi=counts.length?Math.max(...counts):1;
  const cap=authorTermCap(),selected=authorTerms.size;
  const stepper=(part,value,min,max)=>`<span class="stepper${own?'':' inherit'}"><button type="button" class="gsd-control" data-tc="${part}|-1"${value<=min?' disabled':''}>&minus;</button><input type="number" class="gsd-control" data-tc-input="${part}" min="${min}" max="${max}" value="${value}"><button type="button" class="gsd-control" data-tc="${part}|1"${value>=max?' disabled':''}>+</button></span>`;
  const notes=[];
  if(hi>cap.max)notes.push(`a law can hold at most ${cap.max} of the selected terms (a term without a parameter appears once, and the complexity budget is ${cap.budget}); draws above that are rejected and redrawn`);
  if(selected>1&&lo<Math.min(selected,cap.max))notes.push(`laws with fewer than ${Math.min(selected,cap.max)} terms will leave some of your selected terms out`);
  return `<div class="term-counts"><span class="muted">terms per law</span> min ${stepper('min',lo,1,cap.max)} max ${stepper('max',hi,1,cap.max)}${own?' <button type="button" class="filter-pill" data-tc-reset="1">default</button>':''}
    ${notes.length?`<div class="muted">${notes.map(esc).join('; ')}.</div>`:''}</div>`;}
function authorSetTermCounts(lo,hi){
  const cap=authorTermCap().max;
  lo=Math.max(1,Math.min(cap,Math.round(lo)));hi=Math.max(lo,Math.min(cap,Math.round(hi)));
  const out=[];for(let n=lo;n<=hi;n++)out.push(n);
  authorGrid.term_counts=out;renderCampaignAuthor();checkCampaignAuthor();}
function authorBetaHtml(){
  const betas=authorGridValue('betas');
  return `<h3>Temperature</h3>
    <div class="grid-fields"><div><span class="muted">beta (inverse temperature, one per law)</span>${rangeFieldHtml('grid:betas')}</div></div>
    <div class="muted">P &prop; exp(&minus;&beta;&middot;H). A large beta makes the graph obey the energy; a small one lets entropy in, and entropy grows with ln N, so mean degree drifts as the ladder climbs. Measured on the founder Hamiltonian at c=0.05: &beta;=1 gives &lang;d&rang; 18.0 to 26.5 from N=256 to 2048, &beta;=100 gives 5.05 to 5.09.</div>`;}
const TEMPERATURES=[[false,'finite','Metropolis at the law\'s beta'],[true,'zero','accept exactly the moves that do not raise the energy']];
function authorDynamicsHtml(){
  const temps=authorGridValue('zero_temperature');
  const tempsOn=temps.length?temps:[false];
  const regimes=new Set();
  tempsOn.forEach(t=>regimes.add(t?'zero temperature':'equilibrium'));
  const pill=(attr,value,label,on,title)=>`<button type="button" class="filter-pill${on?' active':''}" ${attr}="${esc(String(value))}" title="${esc(title)}">${esc(label)}</button>`;
  return `<h3>Dynamics</h3>
    <div class="grid-fields"><div><span class="muted">locality (share of moves that pick a node and toggle the edge between two of its neighbours)</span>${rangeFieldHtml('grid:localities')}</div></div>
    <div class="filter-pills"><span class="muted">temperature</span> ${TEMPERATURES.map(([k,label,title])=>pill('data-zero-t',k,label,tempsOn.indexOf(k)>=0,title)).join('')}</div>
    <div class="grid-fields"><div><span class="muted">swap share (of the global moves: a swap rewires two edges and keeps every degree; add and delete share the rest)</span>${rangeFieldHtml('grid:swap_shares')}</div></div>
    <div class="muted">Laws drawn here are <b>${[...regimes].join(', ')}</b>. Each law draws its own settings, and every setting is stored with the law. The rest of every law's moves are the global add, delete and swap. With only edge and degree terms at zero temperature, a swap never raises the energy, so such a law with swaps keeps moving.</div>`;}
function authorWindowProblem(){
  if(!authorWindow)return null;
  const lo=Number(authorWindow.min),hi=Number(authorWindow.max);
  if(!isFinite(lo)||!isFinite(hi))return 'the window needs a number at each end';
  if(lo<0)return 'the window cannot start below 0';
  if(hi<=lo)return 'the window must end above where it starts';
  return null;}
function authorWindowHtml(){
  const w=(authorCheck&&authorCheck.mean_degree_window)||{};
  const lo=authorWindow?authorWindow.min:w.min,hi=authorWindow?authorWindow.max:w.max;
  const armed=Number(w.armed_from_n||0),problem=authorWindowProblem();
  const field=(end,label,v)=>`<label class="muted">${label} <input type="number" class="gsd-control" data-window="${end}" min="0" step="0.5" value="${v===undefined||v===null?'':esc(String(v))}"></label>`;
  return `<h3>Mean degree</h3>
    <div class="grid-fields"><div><span class="muted">the window a law's mean degree must stay in; the top is also the engine's too-dense stop</span>
      ${field('min','from',lo)} ${field('max','to',hi)}${authorWindow?' <button type="button" class="filter-pill" data-window-reset="1">back to the starting point\'s</button>':''}</div></div>
    ${problem?`<div class="alert-box warn"><b>${esc(problem)}.</b></div>`:''}
    <div class="muted">${armed>0?`The cap is armed from N = ${armed.toLocaleString()}, so at the first rung a law may go fully connected under any cap.`:'The cap is armed from the first rung.'} Temperature and zero temperature are set above.</div>`;}
function authorToggleListKey(key,value,order){
  const cur=authorGridValue(key),now=(cur.length?cur:[order[0]]).slice(),at=now.findIndex(v=>v===value);
  if(at>=0)now.splice(at,1);else now.push(value);
  if(now.length)authorGrid[key]=order.filter(x=>now.indexOf(x)>=0);else delete authorGrid[key];
  renderCampaignAuthor();checkCampaignAuthor();}
function authorInheritedHtml(){
  const rows=(authorCheck&&authorCheck.inherited)||[];
  if(!rows.length)return '';
  const differ=rows.filter(r=>!r.shipped_default).length;
  const source=authorParent==='defaults'?'the shipped defaults':`campaign ${authorParent}`;
  const body=rows.map(r=>{const text=JSON.stringify(r.value);
    return `<tr class="${r.shipped_default?'':'differs'}"><td><code>${esc(r.field)}</code></td><td class="muted">${esc(r.reading)}</td>
      <td><code title="${esc(text)}">${esc(text.length>90?text.slice(0,88)+'…':text)}</code></td><td>${r.shipped_default?'<span class="muted">shipped default</span>':'<b>differs</b>'}</td></tr>`}).join('');
  return `<details class="inherited"${differ?' open':''}><summary>Carried over from ${esc(source)}: ${rows.length} fields, ${differ?`<b>${differ} differ from the shipped defaults</b>`:'all of them the shipped defaults'}</summary>
    <table class="inherited-table"><thead><tr><th>field</th><th>what it is</th><th>value</th><th></th></tr></thead><tbody>${body}</tbody></table></details>`;}
function authorGridHtml(){
  const scales=authorGridValue('scales'),mags=authorGridValue('magnitudes');
  const pills=GRID_SCALES.map(s=>`<button type="button" class="filter-pill${scales.indexOf(s)>=0?' active':''}" data-scale="${esc(s)}" title="how the coefficient depends on N">${esc(s)}</button>`).join('');
  const dirty=Object.keys(authorGrid).length;
  const ops=[...authorTerms],per=authorGrid.per_term||{};
  const ownMags=ops.filter(op=>(per[op]||{}).magnitudes!==undefined).length;
  const unused=ops.length&&ownMags===ops.length;
  return `<details class="grid-defaults"${unused?'':' open'}><summary>Defaults for terms you do not set${unused?' <span class="muted">(every selected term sets its own magnitude, so the default magnitude is unused)</span>':''}</summary>
    <div class="muted">A blind survey across many terms uses one range for all of them; that shared range is its denominator. Anything a term row above leaves unset is drawn from here.</div>
    <div class="filter-pills">${pills}</div>
    <div class="grid-fields">
      <div><span class="muted">default magnitude</span>${rangeFieldHtml('grid:magnitudes')}</div>
      <div><span class="muted">default sign</span> ${SIGN_CHOICES.map(([k,label])=>`<button type="button" class="filter-pill${authorInheritedSign()===k?' active':''}" data-grid-sign="${esc(k)}" title="${k==='both'?'either sign':'every coefficient '+k}">${esc(label)}</button>`).join('')}</div>
      <div><span class="muted">power exponent p (for the power scale, N^p)</span>${rangeFieldHtml('grid:power_exponents')}</div>
      <div><span class="muted">anchor k (the degree a degree anchor pulls towards)</span>${rangeFieldHtml('grid:anchor_k')}</div>
    </div>
    <div class="muted"><b>range</b> draws continuously between min and max; <b>values</b> draws only the numbers listed.</div></details>
    ${dirty&&!authorReadOnly?`<div><button type="button" class="gsd-control" id="authorGridReset">back to the parent's grid</button></div>`:''}`;}
function renderCampaignAuthor(){
  const host=document.getElementById('campaignAuthor');if(!host||!authorParent)return;
  const cat=(campaignsData&&campaignsData.terms)||[];
  const group=name=>cat.filter(t=>t.group===name).map(t=>{
    const on=authorTerms.has(t.op);
    const note=t.reduces_to&&t.reduces_to.length?` = ${t.reduces_to.join(' + ')}`:(t.defines_sparse_phase?' · can define a sparse phase':'');
    return `<button type="button" class="filter-pill${on?' active':''}" data-term="${esc(t.op)}" title="cost ${esc(t.cost)}${esc(note)}">${esc(TERMS.label?TERMS.label(t.op):t.op)}</button>`}).join('');
  const v=authorCheck;
  const verdict=!v?'<div class="muted">checking this selection…</div>'
    :v.status==='REFUSED'?`<div class="alert-box warn"><b>this selection cannot be run.</b> ${(v.problems||[]).map(esc).join(' ')}</div>`
    :`<div class="alert-box info"><b>${authorSpaceLine(v)}</b> ${authorNotes(v)}</div>${authorAdviceHtml(v)}`;
  const parents=`<option value="defaults"${authorParent==='defaults'?' selected':''}>the shipped defaults (no parent, no terms selected)</option>`+((campaignsData&&campaignsData.campaigns)||[]).map(r=>
    `<option value="${esc(r.campaign_id)}"${r.campaign_id===authorParent?' selected':''}>campaign ${esc(r.campaign_id)}${r.name?' \u00b7 '+esc(r.name):''} \u00b7 ${esc(r.term_count)} term(s)</option>`).join('');
  host.innerHTML=`<section class="panel"><div class="panel-title-row"><div><h2>New campaign</h2>
    <div class="muted">Start from the shipped defaults, or from a campaign this folder holds. The page sets the terms, their coefficients, the temperature and how many terms a law carries; <b>everything else is carried over</b> from the starting point and frozen at creation, and the list at the bottom says exactly what.</div>
    <label class="muted">start from <select id="authorParent" class="gsd-control">${parents}</select></label></div>
    <div class="toolbar"><button type="button" class="gsd-control" id="authorCancel">cancel</button>
    <button type="button" class="gsd-control" data-admin-write id="authorStart"${(!v||v.status!=='PASS'||authorBusy||authorWindowProblem())?' disabled':''}>start campaign</button></div></div>
    <h3>Degree sequence</h3><div class="filter-pills">${group('degree_sequence')}</div>
    <h3>Topology</h3><div class="filter-pills">${group('topology')}</div>
    <div class="muted">A term marked <code>= a + b</code> is exactly those terms by an algebraic identity, so leaving it out does not remove that physics from the search.</div>
    ${verdict}
    ${authorPerTermHtml()}
    ${authorBetaHtml()}
    ${authorDynamicsHtml()}
    ${authorWindowHtml()}
    ${authorGridHtml()}
    ${authorInheritedHtml()}
    <label class="muted">why this campaign <input id="authorReason" class="gsd-control" type="text" placeholder="added triangle_count to the three-term pool" value="${esc(authorReasonText)}"></label>
    <h3>The fleet</h3>
    <label class="muted"><input type="checkbox" id="authorTakesFleet"${authorTakesFleet?' checked':''}> give this campaign the whole fleet and pause the others</label>
    <div class="muted">${authorTakesFleet?`${esc(((campaignsData&&campaignsData.campaigns)||[]).filter(r=>r.state==='active').map(r=>r.campaign_id).join(', ')||'nothing')} will be paused. A paused campaign keeps every unit of its work and resumes from where it stopped.`:'the new campaign shares the fleet with whatever else is running.'}</div>
  </section>`;
  host.querySelectorAll('[data-term]').forEach(b=>{b.onclick=()=>{
    const op=b.dataset.term;
    if(authorTerms.has(op)){authorTerms.delete(op);
      if(authorGrid.per_term&&authorGrid.per_term[op]){
        const per=Object.assign({},authorGrid.per_term);delete per[op];
        if(Object.keys(per).length)authorGrid.per_term=per;else delete authorGrid.per_term}}
    else authorTerms.add(op);
    renderCampaignAuthor();checkCampaignAuthor()}});
  host.querySelectorAll('[data-scale]').forEach(b=>{b.onclick=()=>{
    const s=b.dataset.scale,now=authorGridValue('scales').slice(),at=now.indexOf(s);
    if(at>=0)now.splice(at,1);else now.push(s);
    authorGrid.scales=GRID_SCALES.filter(x=>now.indexOf(x)>=0);
    renderCampaignAuthor();checkCampaignAuthor()}});
  authorWireRangeFields(host);
  host.querySelectorAll('[data-tc]').forEach(b=>{b.onclick=()=>{
    const [part,step]=b.dataset.tc.split('|'),counts=authorGridValue('term_counts');
    let lo=counts.length?Math.min(...counts):1,hi=counts.length?Math.max(...counts):1;
    if(part==='min')lo+=Number(step);else hi+=Number(step);
    authorSetTermCounts(lo,Math.max(lo,hi))}});
  host.querySelectorAll('[data-tc-input]').forEach(box=>{box.onchange=()=>{
    const counts=authorGridValue('term_counts'),n=Number(box.value);if(!isFinite(n))return;
    let lo=counts.length?Math.min(...counts):1,hi=counts.length?Math.max(...counts):1;
    if(box.dataset.tcInput==='min')lo=n;else hi=n;
    authorSetTermCounts(lo,Math.max(lo,hi))}});
  host.querySelectorAll('[data-tc-reset]').forEach(b=>{b.onclick=()=>{
    delete authorGrid.term_counts;renderCampaignAuthor();checkCampaignAuthor()}});
  host.querySelectorAll('[data-term-sign]').forEach(b=>{b.onclick=()=>{
    const [op,which]=b.dataset.termSign.split(':');
    authorSetTermGrid(op,{signs:which==='both'?null:(which==='positive'?[1]:[-1])})}});
  host.querySelectorAll('[data-term-scale]').forEach(b=>{b.onclick=()=>{
    const [op,sc]=b.dataset.termScale.split(':');
    if(sc==='*'){authorSetTermGrid(op,{scales:null});return}
    const own=authorTermGrid(op),now=Array.isArray(own.scales)?own.scales.slice():[];
    const at=now.indexOf(sc);if(at>=0)now.splice(at,1);else now.push(sc);
    authorSetTermGrid(op,{scales:now.length?GRID_SCALES.filter(x=>now.indexOf(x)>=0):null})}});
  host.querySelectorAll('[data-grid-sign]').forEach(b=>{b.onclick=()=>{
    const k=b.dataset.gridSign;
    authorGrid.signs=k==='both'?[-1,1]:(k==='positive'?[1]:[-1]);renderCampaignAuthor();checkCampaignAuthor()}});
  host.querySelectorAll('[data-zero-t]').forEach(b=>{b.onclick=()=>{
    authorToggleListKey('zero_temperature',b.dataset.zeroT==='true',[false,true])}});
  host.querySelectorAll('[data-window]').forEach(box=>{box.onchange=()=>{
    const w=(authorCheck&&authorCheck.mean_degree_window)||{},v=Number(box.value);
    if(box.value===''||!isFinite(v))return;
    const now=Object.assign({min:w.min,max:w.max},authorWindow||{});now[box.dataset.window]=v;
    authorWindow={min:Number(now.min),max:Number(now.max)};
    renderCampaignAuthor();if(!authorWindowProblem())checkCampaignAuthor()}});
  host.querySelectorAll('[data-window-reset]').forEach(b=>{b.onclick=()=>{
    authorWindow=null;renderCampaignAuthor();checkCampaignAuthor()}});
  const reset=document.getElementById('authorGridReset');
  if(reset)reset.onclick=()=>{authorGrid={};renderCampaignAuthor();checkCampaignAuthor()};
  const parentPick=document.getElementById('authorParent');
  if(parentPick)parentPick.onchange=()=>{openCampaignAuthor(parentPick.value)};
  const takes=document.getElementById('authorTakesFleet');
  if(takes)takes.onchange=()=>{authorTakesFleet=!!takes.checked;renderCampaignAuthor()};
  const cancel=document.getElementById('authorCancel');
  if(cancel)cancel.onclick=()=>{authorParent=null;authorRequestId=null;authorReasonText='';host.hidden=true;host.innerHTML=''};
  const why=document.getElementById('authorReason');
  if(why)why.oninput=()=>{authorReasonText=why.value};
  const start=document.getElementById('authorStart');
  if(start)start.onclick=()=>startAuthoredCampaign();}
async function checkCampaignAuthor(){
  if(!authorParent)return;
  try{authorCheck=await manageCampaign({action:'preflight',parent_campaign_id:authorParent,operator_whitelist:[...authorTerms],grid:authorGrid,
    ...(authorWindow?{mean_degree_window:authorWindow}:{})})}
  catch(_){authorCheck=null}
  renderCampaignAuthor();}
async function startAuthoredCampaign(){
  if(!authorParent||authorBusy)return;authorBusy=true;renderCampaignAuthor();
  const reason=authorReasonText;
  const allocation={};
  if(authorTakesFleet)((campaignsData&&campaignsData.campaigns)||[]).forEach(r=>{
    if(r.state==='active')allocation[r.campaign_id]=0});
  authorRequestId=authorRequestId||newRequestId();
  try{const made=await manageCampaign({action:'create',parent_campaign_id:authorParent,request_id:authorRequestId,
        operator_whitelist:[...authorTerms],grid:authorGrid,reason,allocation,
        ...(authorWindow?{mean_degree_window:authorWindow}:{})});
    authorParent=null;authorRequestId=null;authorReasonText='';const host=document.getElementById('campaignAuthor');
    if(host){host.hidden=true;host.innerHTML=''}
    await refreshCampaigns(true);
    if(made&&made.campaign_id){
      if(SYS.refreshCampaignList)await SYS.refreshCampaignList(made.campaign_id);
      await openCampaignPanel(made.campaign_id)}}
  catch(_){}
  finally{authorBusy=false;renderCampaignAuthor()}}
const FOLDED_KEY='gsd-folded-panels';
function foldedPanels(){try{const v=JSON.parse(localStorage.getItem(FOLDED_KEY)||'[]');return new Set(Array.isArray(v)?v.map(String):[])}catch(_){return new Set()}}
function keepFoldedPanels(keys){try{localStorage.setItem(FOLDED_KEY,JSON.stringify([...keys].sort()))}catch(_){}}
function foldTitle(h2){const node=[...(h2.childNodes||[])].find(n=>n.nodeType===3&&String(n.textContent||'').trim());return String(node?node.textContent:(h2.textContent||'')).trim()}
function foldPanel(section,h2,folded){if(folded)section.classList.add('folded');else section.classList.remove('folded');h2.setAttribute('aria-expanded',folded?'false':'true')}
function toggleFold(section,h2){const key=h2.dataset.fold,keys=foldedPanels(),folded=!section.classList.contains('folded');foldPanel(section,h2,folded);if(folded)keys.add(key);else keys.delete(key);keepFoldedPanels(keys);dispatchEvent(new Event('resize'))}
function setUpFolds(root=document){const keys=foldedPanels();for(const main of root.querySelectorAll('main.gsd-app-page')){const page=(main.dataset&&main.dataset.page)||main.id||'';for(const section of main.querySelectorAll('section.panel')){const h2=section.querySelector(':scope>h2')||section.querySelector(':scope>.panel-title-row h2');if(!h2||h2.dataset.fold)continue;const title=foldTitle(h2);if(!title)continue;h2.dataset.fold=`${page}:${title}`;h2.classList.add('fold-title');h2.setAttribute('role','button');h2.setAttribute('tabindex','0');foldPanel(section,h2,keys.has(h2.dataset.fold));h2.addEventListener('click',e=>{const t=e&&e.target;if(t&&t!==h2&&t.closest&&t.closest('a,button,select,input,label'))return;toggleFold(section,h2)});h2.addEventListener('keydown',e=>{if(e&&(e.key==='Enter'||e.key===' ')){if(e.preventDefault)e.preventDefault();toggleFold(section,h2)}})}}}
setUpFolds();
document.getElementById('campaignsReload')?.addEventListener('click',()=>refreshCampaigns(true));
document.getElementById('campaignsNew')?.addEventListener('click',()=>{
  const rows=(campaignsData&&campaignsData.campaigns)||[];
  if(rows.length)openCampaignAuthor(rows[0].campaign_id)});
window.GSD_APP_READY=true; window.GSD_APP={renderWorkerCount,setWorkerCount,renderWorkload,setWorkload,renderFilters,chooseFilter,clearFilters,measureFilterHeight,homeFilterPasses,filteredTop,get homeFilter(){return homeFilter;},setUpFolds,toggleFold,chooseLandLattices,landChainPoints,loadExplorer,atlasEinstein,calibMarginBands,markHomeLoading,candidateHref,renderStudyBundles,renderStudyNow,studyCard,paintCampaignScope,explorerStudy,mergeFilterOptions,set homeLoading(v){homeLoading=v;},get homeLoading(){return homeLoading;},set landWaiting(v){landWaiting=v;},set studyBundles(v){studyBundles=v;},set reportStatusForTest(v){reportStatus=v;},refreshReports,oneSeedReading,readingFromLine,set reportsAnsweredAt(v){reportsAnsweredAt=v;},get reportsAnsweredAt(){return reportsAnsweredAt;},refreshCampaigns,drawLandscape,drawExplorer,explorerSortBy,set explorerRows(v){explorerRows=v||[];explorerLoaded=true;},get explorerRows(){return explorerRows;},set landscape(v){landscape=v;},get landscape(){return landscape;},set campaign(v){campaign=v;},get campaign(){return campaign;},get explorerSort(){return explorerSort;},set explorerSort(v){explorerSort=v;},renderHome,renderLive,renderSystem,renderStranded,reportQuietHtml,set reportAdmin(v){reportAdmin=!!v;},memoryAdmissionRow,renderReports,renderCalibration,renderGate,refreshGate,landingPage,renderCampaigns,refreshCampaigns,renderCampaignPanel,renderCampaignAuthor,openCampaignAuthor,set authorGrid(v){authorGrid=v||{};},get authorGrid(){return authorGrid;},set authorWindow(v){authorWindow=v||null;},get authorWindow(){return authorWindow;},set authorCheck(v){authorCheck=v||null;},set campaignsData(v){campaignsData=v||null;},get campaignsData(){return campaignsData;},renderProbeAtlas,renderTop,leaderRow,budgetText,rungLadderRow,get hitPoints(){return hitPoints;},get bandLayout(){return bandLayout;},get labelHits(){return labelHits;},set channelCounts(v){channelCounts=v||{};},get channelCounts(){return channelCounts;},
set landscapePayload(v){landscape=v?{campaign_id:campaign,...v}:null;} ,get landscapePayload(){return landscape;},set overviewPayload(v){last=v||null;},get overviewPayload(){return last;}};const stale=document.getElementById('gsdClientFailure');if(stale)stale.remove();const copyRaw=document.getElementById('copyRawJson');if(copyRaw)copyRaw.onclick=async()=>{const raw=document.getElementById('raw'),text=raw?.dataset.copyText||raw?.textContent||'';const prior=copyRaw.textContent;try{const ok=await copyText(text);copyRaw.textContent=ok?'copied':'copy failed'}catch(_){copyRaw.textContent='copy failed'}setTimeout(()=>{copyRaw.textContent=prior},1200)};
let filterHeight=0;
function measureFilterHeight(host){const el=host||document.getElementById('filterPanel');if(!el)return filterHeight;const box=typeof el.getBoundingClientRect==='function'?el.getBoundingClientRect():null;const measured=Math.ceil((box&&box.height)||el.offsetHeight||0);if(!(measured>0)||measured===filterHeight)return filterHeight;filterHeight=measured;document.documentElement.style.setProperty('--gsd-filter-h',measured+'px');try{window.dispatchEvent(new CustomEvent('rr:hero-metrics',{detail:{filterHeight:measured}}))}catch(_){}return measured}
(()=>{const el=document.getElementById('filterPanel');if(!el)return;measureFilterHeight(el);if(typeof ResizeObserver==='function'){try{new ResizeObserver(()=>measureFilterHeight(el)).observe(el)}catch(_){}}})();
const repaintLandscape=()=>{const shown=shownLandscape();if(shown&&currentPage==='home')drawLandscape(landChainPoints());if(currentPage==='explorer'&&explorerLoaded)drawExplorer()};
addEventListener('resize',repaintLandscape);window.addEventListener('rr:hero-metrics',repaintLandscape);if(window.GSD_CAMPAIGN){campaign=String(window.GSD_CAMPAIGN);scheduleLandscape(0)}
})();
