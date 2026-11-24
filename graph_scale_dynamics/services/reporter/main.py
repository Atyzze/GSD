from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid

from graph_scale_dynamics.domain.model import content_hash, utc_now
from graph_scale_dynamics.domain.version import BUILD_NUMBER, runtime_fingerprint
from graph_scale_dynamics.operations.dev_mode import provenance as dev_mode_provenance
from graph_scale_dynamics.operations.report_cycle import (
    COMPLETE, FAILED, apply_cycle_outcome, classify_cycle,
)
from graph_scale_dynamics.operations.volatile_storage import choose_volatile_dir
from graph_scale_dynamics.research.report_catalog import REPORTS, REPORT_BY_CODE, catalog_payload
from graph_scale_dynamics.reporting.evidence import EVIDENCE_CONTRACT, collect_evidence
from graph_scale_dynamics.research.report_pipeline import build_report

UNCHANGED_WRITE_BYTES_SKIPPED = 0
UNCHANGED_WRITES_SKIPPED = 0

def _atomic_text(path: Path, text: str) -> None:
    global UNCHANGED_WRITE_BYTES_SKIPPED, UNCHANGED_WRITES_SKIPPED
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = text.encode("utf-8")
    try:
        if path.stat().st_size == len(encoded) and path.read_bytes() == encoded:
            UNCHANGED_WRITE_BYTES_SKIPPED += len(encoded)
            UNCHANGED_WRITES_SKIPPED += 1
            return
    except OSError:
        pass
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(encoded)
    os.replace(tmp, path)


def _atomic_json(path: Path, payload: dict) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))


def _html_page(code: str, number: int | str, title: str, question: str | None = None) -> str:
    if question is None:
        question = str(title)
        title = str(number)
        number = REPORT_BY_CODE[str(code)].number
    number = int(number)
    nav = " ".join(f'<a href="{r.number}.html" class="navcode" data-code="{r.code}">{r.number}</a>' for r in REPORTS)
    return f'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Report {number} · {title} · Build {BUILD_NUMBER}</title>
<link rel="stylesheet" href="../assets/system.css">
<style>
:root{{color-scheme:dark;background:#050607;color:#d8dee9;font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;--living:#63d58a;--living-hi:#94edb2;--living-dim:#173f29}}
body{{margin:0;background:var(--bg)}} header{{padding:10px 0;border-bottom:1px solid var(--line);margin-bottom:8px}}
h1{{font:600 20px/1.2 system-ui;margin:12px 0 4px}} .question{{color:#9aa8b7;max-width:1100px}} .nav{{display:flex;gap:5px;flex-wrap:wrap}}
.navcode{{border:1px solid #30443a;border-radius:4px;padding:2px 7px;color:#8edca7;text-decoration:none}} .navcode:hover{{border-color:#4c8d62;background:#0c1a12}} .navcode.active{{background:#153824;border-color:#4d9b67;color:#e3faea;box-shadow:0 0 10px rgba(99,213,138,.08)}}
#status{{margin:12px 0;color:#b5c1ce}} .good{{color:#75d890}} .warn{{color:#f0ca67}} .bad{{color:#ff8d8d}}
section{{border-top:1px solid #202832;padding:12px 0}} h2,h3{{font-family:system-ui;margin:8px 0}} table{{border-collapse:collapse;table-layout:auto;width:max-content;min-width:100%;font-size:12px}}
th,td{{border:1px solid #25313d;padding:5px 7px;vertical-align:top;text-align:left;max-width:56ch;overflow-wrap:anywhere}} th{{color:#8edca7;white-space:normal}} td.scalarcell{{white-space:normal}} td.objectcell{{min-width:28ch;max-width:64ch}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b0f13;padding:8px;margin:0;border-radius:5px;min-width:24ch;max-width:62ch}}
details{{border-left:2px solid #25313d;padding-left:10px;margin:7px 0}} summary{{cursor:pointer;color:#b8c7d8}} .scalar{{display:grid;grid-template-columns:minmax(170px,280px) 1fr;gap:8px;padding:2px 0}}
.key{{color:#8fa1b5}} .empty{{color:#73808e}} .stamp{{color:#7f8d9b;font-size:12px}}
.qcards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px;margin:10px 0}} .qcard{{border:1px solid #263544;background:#091018;border-radius:6px;padding:9px}} .qcard .v{{font:600 20px system-ui;color:#dffbea}} .qbarrow{{display:grid;grid-template-columns:64px 1fr 44px;gap:7px;align-items:center;margin:2px 0}} .qbartrack{{height:10px;background:#101a24;border:1px solid #263544;border-radius:3px;overflow:hidden}} .qbarfill{{height:100%;background:#4f8ed8}} .qhbarfill{{height:100%;background:#b68a24}} .qnote{{color:#9aa8b7;font-size:12px}}
.actions{{display:flex;gap:6px;flex-wrap:wrap;margin:9px 0 0}} button,.actionlink{{background:#0d1412;color:#bde5ca;border:1px solid #30443a;border-radius:4px;padding:4px 8px;font:12px ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer;text-decoration:none}} button:hover,.actionlink:hover{{background:#12251a;border-color:#4c8d62}} button:disabled{{opacity:.45;cursor:not-allowed}} #copyState{{font-size:12px;color:#7f8d9b;align-self:center}} #phaseState{{font-size:12px;color:#9aa8b7;align-self:center}}
</style></head>
<body><div id="gsdSystemHeader"></div><main class="report-shell"><header><div class="report-nav">{nav}</div><h1>Report {number} · {title}</h1><div class="question">{question}</div><div class="actions"><button id="reportNow">update reports now</button><a class="actionlink" href="../reports">report diagnostics</a><button id="copyJson">copy JSON</button><button id="saveJson">save JSON</button><button id="expandAll">expand all</button><button id="collapseAll">collapse all</button><span id="phaseState"></span><span id="copyState"></span></div><div id="status">initializing…</div></header>
<div id="content"></div></main>
<script>window.GSD_UI_CONFIG={{relativeApi:"..",navPrefix:"../",homeHref:"../",buildNumber:"{BUILD_NUMBER}",runtimeFingerprint:"{runtime_fingerprint()}",runtimeShort:"{runtime_fingerprint()[:8]}",devMode:{"true" if dev_mode_provenance()["development_mode"] else "false"},activePage:"reports"}};</script><script src="../assets/system.js"></script>
<script>
const CODE={json.dumps(code)}; const NUMBER={int(number)}; const POLL_MS=4000; const REQUEST_TIMEOUT_MS=1800; let displayedRevision=null; let inFlight=false; let currentPayload=null; let currentCampaign=null;
const HASH=new URLSearchParams(location.hash.slice(1)); const ADMIN_TOKEN=HASH.get('admin')||'';
document.querySelectorAll('.navcode').forEach(a=>{{if(Number(a.textContent)===NUMBER)a.classList.add('active'); if(location.hash)a.href+=location.hash;}});
function esc(v){{return String(v).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]))}}
function candidateLink(k,v){{if(v===null||v===undefined)return null; const key=String(k||'').toLowerCase(); if(!['candidate','candidate_id','candidateid'].includes(key))return null; const id=String(v); let href='../candidate?candidate='+encodeURIComponent(id)+(currentCampaign?'&campaign='+encodeURIComponent(currentCampaign):''); if(ADMIN_TOKEN)href+='#admin='+encodeURIComponent(ADMIN_TOKEN); return `<a class=\"candidate-link\" href=\"${{href}}\">${{esc(id)}}</a>`;}}
function scalar(k,v){{const link=candidateLink(k,v);return `<div class="scalar"><div class="key">${{esc(k)}}</div><div>${{v===null?'<span class=empty>null</span>':(link||esc(v))}}</div></div>`}}
function qHistogram(hist,title,klass='qbarfill'){{
 const bins=(hist||{{}}).bins||[]; if(!bins.length)return `<div class=qnote>${{esc(title)}}: no valid coordinates</div>`;
 const max=Math.max(...bins.map(b=>Number(b.count||0)),1);
 return `<h3>${{esc(title)}}</h3>`+bins.map(b=>`<div class=qbarrow><span>${{esc(b.center)}}</span><div class=qbartrack><div class="${{klass}}" style="width:${{100*Number(b.count||0)/max}}%"></div></div><span>${{esc(b.count||0)}}</span></div>`).join('');
}}
function renderQ(value){{
 const scope=value.scope_and_completeness||{{}}, dims=value.dimensional_classes||{{}}, conn=value.connectivity_viability||{{}}, seed=value.seed_replication||{{}};
 const dc=dims.counts||{{}}, cc=conn.classification_counts||{{}}; const occ=value.dimensional_occupancy||[];
 const multi=((seed.agreement||{{}}).multi_seed_groups??seed.candidates_with_any_multi_seed_base_rung??0);
 let html=`<section><h2>artifact vs landscape checkpoint</h2><div class=qnote>Reporting-only evidence audit. A cluster or gap becomes more landscape-like only as it survives scale, seed, sampler/null and exposure checks.</div><div class=qcards>`+
   `<div class=qcard><div class=key>complete base-block cohort</div><div class=v>${{esc(scope.complete_base_block_phenotypes??0)}}</div></div>`+
   `<div class=qcard><div class=key>stable on all four probes</div><div class=v>${{esc(dc.STABLE_ALL_PROBES??0)}}</div></div>`+
   `<div class=qcard><div class=key>stable on some probes</div><div class=v>${{esc(dc.STABLE_SOME_PROBES??0)}}</div></div>`+
   `<div class=qcard><div class=key>still drifting</div><div class=v>${{esc(dc.STILL_DRIFTING??0)}}</div></div>`+
   `<div class=qcard><div class=key>median stability score</div><div class=v>${{esc(((dims.stability||{{}}).score_median)??'')}}</div></div>`+
   `<div class=qcard><div class=key>connectivity floor failures</div><div class=v>${{esc(cc.FAILED_FLOOR??0)}}</div></div>`+
   `<div class=qcard><div class=key>multi-seed candidate/N groups</div><div class=v>${{esc(multi)}}</div></div></div></section>`;
 for(const row of occ){{
   html+=`<section><h2>N=${{esc(row.n)}} dimensional occupancy</h2><div class=qnote>joint occupied cells: ${{esc(row.joint_occupied_cells??0)}} · bin width ${{esc((row.d_s_histogram||{{}}).bin_width??'')}}</div>`;
   html+=`<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px">`+(row.probes||['d_s','d_V','d_B','d_w']).map((p,i)=>`<div>${{qHistogram(row[p+'_histogram'],p,i%2?'qhbarfill':undefined)}}</div>`).join('')+`</div></section>`;
 }}
 html+=`<section><h2>audit trail</h2><div class=qnote>The sections below preserve the complete structured evidence, including candidate gaps, recurrence, decision-barrier context, limitations and recommended follow-ups.</div>${{render(value,'structured audit',1)}}</section>`;
 return html;
}}
function render(value,key='report',depth=0){{
 if(value===null||typeof value!=='object') return scalar(key,value);
 if(key==='capacity_diagnosis' && !Array.isArray(value)){{
   const sev=value.severity==='error'?'bad':(value.severity==='good'?'good':'warn');
   const cpu=value.cpu||{{}}, mem=value.memory||{{}}, work=value.work||{{}};
   const pct=v=>v===null||v===undefined?'n/a':(100*Number(v)).toFixed(1)+'%';
   const hostCpu=cpu.host_cpu_percent===null||cpu.host_cpu_percent===undefined?'n/a':Number(cpu.host_cpu_percent).toFixed(1)+'%';
   return `<section><h2 class="${{sev}}">LIMITING STATE · ${{esc(value.state||'UNKNOWN')}}</h2>`+
     `<div class="question">${{esc(value.explanation||'')}}</div>`+
     `<div class="scalar"><div class="key">invariant</div><div>${{esc(value.invariant_status||'')}}</div></div>`+
     `<div class="scalar"><div class="key">compute slots</div><div>${{esc(cpu.active_compute??0)}} / ${{esc(cpu.configured_slots??0)}} · unused ${{esc(cpu.unused_slots??0)}} · host CPU ${{hostCpu}}</div></div>`+
     `<div class="scalar"><div class="key">RAM reservation</div><div>${{pct(mem.reservation_fraction)}} of admission budget · host RAM ${{pct(mem.host_fraction)}} · target ${{pct(mem.target_host_fraction)}} · emergency ${{pct(mem.emergency_host_fraction)}}</div></div>`+
     `<div class="scalar"><div class="key">runnable work</div><div>sim ${{esc(work.claimable_simulations??0)}} · analysis ${{esc(work.claimable_analyses??0)}} · deferred analysis ${{esc(work.deferred_analysis??0)}}</div></div>`+
     `<div class="scalar"><div class="key">pipeline</div><div>stranded ${{esc(work.stranded_nonterminal_candidates??0)}} · proposed ${{esc(work.proposed_waiting??0)}}</div></div>`+
     `<div class="scalar"><div class="key">next focus</div><div>${{esc(value.next_focus||'')}}</div></div>`+
     `<details open><summary>diagnostic detail</summary><pre>${{esc(JSON.stringify(value,null,2))}}</pre></details></section>`;
 }}
 if(Array.isArray(value)){{
   if(!value.length)return scalar(key,'[]');
   if(value.every(x=>x&&typeof x==='object'&&!Array.isArray(x)) && value.length<=250){{
     const keys=[...new Set(value.flatMap(x=>Object.keys(x)))].slice(0,14);
     const cellText=(x,k)=>{{const v=x[k]; if(v===null||v===undefined)return ''; return typeof v==='object'?JSON.stringify(v):String(v)}};
     const widthFor=k=>{{let m=String(k).length; for(const x of value.slice(0,80))m=Math.max(m,Math.min(72,cellText(x,k).length)); return Math.max(10,Math.min(48,m+2));}};
     const cols=keys.map(k=>`<col style="width:${{widthFor(k)}}ch">`).join('');
     const rows=value.map(x=>`<tr>${{keys.map(k=>{{const v=x[k]; const obj=v&&typeof v==='object'; return `<td class="${{obj?'objectcell':'scalarcell'}}">${{obj?`<pre>${{esc(JSON.stringify(v,null,1))}}</pre>`:(candidateLink(k,v)||esc(v??''))}}</td>`}}).join('')}}</tr>`).join('');
     return `<section><h3>${{esc(key)}} <span class=stamp>(${{value.length}})</span></h3><div style="overflow:auto"><table><colgroup>${{cols}}</colgroup><thead><tr>${{keys.map(k=>`<th>${{esc(k)}}</th>`).join('')}}</tr></thead><tbody>${{rows}}</tbody></table></div></section>`;
   }}
   return `<details ${{depth<1?'open':''}}><summary>${{esc(key)}} (${{value.length}})</summary><pre>${{esc(JSON.stringify(value,null,2))}}</pre></details>`;
 }}
 let out=depth===0?'':`<details ${{depth<2?'open':''}}><summary>${{esc(key)}}</summary>`;
 for(const [k,v] of Object.entries(value)) out+=render(v,k,depth+1);
 return out+(depth===0?'':'</details>');
}}
function setCopyState(text,bad=false){{const e=document.getElementById('copyState'); e.textContent=text||''; e.style.color=bad?'#ff8d8d':'#75d890'; if(text)setTimeout(()=>{{if(e.textContent===text)e.textContent=''}},2200);}}
async function copyText(text){{
 if(navigator.clipboard&&window.isSecureContext){{await navigator.clipboard.writeText(text); return true;}}
 const ta=document.createElement('textarea'); ta.value=text; ta.style.position='fixed'; ta.style.opacity='0'; document.body.appendChild(ta); ta.focus(); ta.select();
 let ok=false; try{{ok=document.execCommand('copy')}}finally{{ta.remove()}} return ok;
}}
function downloadJson(text){{const blob=new Blob([text],{{type:'application/json'}}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=`report-${{String(NUMBER).padStart(2,'0')}}-${{displayedRevision||'snapshot'}}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);}}
document.getElementById('copyJson').onclick=async()=>{{
 if(!currentPayload){{setCopyState('no report snapshot yet',true); return;}}
 const text=JSON.stringify(currentPayload,null,2);
 try{{if(await copyText(text)) setCopyState('complete JSON copied'); else {{downloadJson(text); setCopyState('clipboard blocked; JSON downloaded')}}}}catch(e){{downloadJson(text); setCopyState('clipboard blocked; JSON downloaded')}}
}};
document.getElementById('saveJson').onclick=()=>{{
 if(!currentPayload){{setCopyState('no report snapshot yet',true); return;}}
 downloadJson(JSON.stringify(currentPayload,null,2)); setCopyState('complete JSON saved');
}};
document.getElementById('expandAll').onclick=()=>document.querySelectorAll('#content details').forEach(d=>d.open=true);
document.getElementById('collapseAll').onclick=()=>document.querySelectorAll('#content details').forEach(d=>d.open=false);

async function fetchJson(url){{
 const ctl=new AbortController(); const timer=setTimeout(()=>ctl.abort(),REQUEST_TIMEOUT_MS);
 try{{const r=await fetch(url,{{cache:'no-store',signal:ctl.signal}}); if(!r.ok){{const e=new Error(`HTTP ${{r.status}}`); e.status=r.status; throw e;}} return await r.json();}}
 finally{{clearTimeout(timer)}}
}}
async function ensureCampaign(){{
 if(currentCampaign)return currentCampaign;
 const m=await fetchJson('manifest.json');
 currentCampaign=String(m.campaign_id||'');
 return currentCampaign;
}}
async function triggerReport(){{
 if(!ADMIN_TOKEN)return;
 await ensureCampaign();
 const headers={{'Content-Type':'application/json','X-GSD-Admin-Token':ADMIN_TOKEN}};
 const r=await fetch('../api/reports/trigger',{{method:'POST',headers,body:JSON.stringify({{campaign_id:currentCampaign,action:'start'}})}});
 if(!r.ok){{let detail='';try{{const j=await r.json();detail=[j.error,j.hint].filter(Boolean).join(' · ')}}catch(_){{}}throw new Error(`report trigger HTTP ${{r.status}}${{detail?': '+detail:''}}`);}}
 return await r.json();
}}
document.getElementById('reportNow').onclick=async()=>{{try{{await triggerReport();await update()}}catch(e){{setCopyState(String(e),true)}}}};
const QUIET_ACTIVE=['pausing','draining','reporting','maintaining','resuming','bundling'];
function quietBusy(statusPayload){{return QUIET_ACTIVE.includes((statusPayload.quiet_report||{{}}).stage)}}
function renderPhase(statusPayload){{
 const quiet=statusPayload.quiet_report||{{}}; const busy=quietBusy(statusPayload);
 const button=document.getElementById('reportNow');
 button.disabled=!ADMIN_TOKEN || !currentCampaign || busy;
 button.textContent=busy?`updating reports · ${{quiet.stage}}`:'update reports now';
 button.title=ADMIN_TOKEN?'One report cycle for this campaign by the study runner, one report at a time; scientific compute goes on meanwhile, and the request is refused while work is in flight.':'Local admin capability required.';
 let text=busy?`reports: ${{quiet.stage}} · ${{((quiet.history||[]).slice(-1)[0]||{{}}).note||''}}`:'reports: idle';
 const flight=statusPayload.in_flight||{{}};
 if(flight.total)text+=` · ${{flight.total}} unit(s) of work in flight; a cycle waits for a quiet fleet`;
 document.getElementById('phaseState').textContent=text;
}}
async function update(){{
 if(inFlight)return; inFlight=true;
 try{{
   await ensureCampaign();
   const statusPayload=await fetchJson('../api/reports/status/'+encodeURIComponent(currentCampaign)+'?ts='+Date.now());
   renderPhase(statusPayload);
   const m=statusPayload.manifest||{{}};
   const r=(m.reports||{{}})[CODE]||{{}}; const status=document.getElementById('status');
   const busy=quietBusy(statusPayload); const stale=r.stale?' · stale: newer durable evidence pending':'';
   if(r.status==='error') status.innerHTML=`<span class=bad>report error</span> · ${{esc(r.error||'unknown')}}`;
   else if(r.revision && r.revision!==displayedRevision){{
      try{{
        const payload=await fetchJson(`../api/reports/${{NUMBER}}?rev=${{encodeURIComponent(r.revision)}}`);
        currentPayload=payload; displayedRevision=r.revision; document.getElementById('content').innerHTML=(CODE==='Q'?renderQ(payload.body):render(payload.body));
        status.innerHTML=`<span class=good>snapshot ${{esc(r.revision)}}</span> · generated ${{esc(payload.generated_utc)}}${{stale}}${{busy?' · newer refresh running':''}}`;
      }}catch(e){{
        if(e&&e.status===404){{
          status.innerHTML=`<span class=warn>report snapshot not present yet</span> · reports appear after a cycle, which runs only when requested and only while no work is in flight`;
          currentPayload=null; displayedRevision=null; document.getElementById('content').innerHTML='';
        }} else throw e;
      }}
   }} else {{
      status.innerHTML=`<span class=${{displayedRevision?'good':'warn'}}>${{displayedRevision?'last-good report ready':'waiting for first report snapshot'}}</span> · snapshot ${{esc(displayedRevision||'none')}}${{stale}}${{busy?' · refresh running':''}}`;
   }}
 }}catch(e){{document.getElementById('status').innerHTML=`<span class=bad>report API unavailable</span> · ${{esc(e)}}`;}}
 finally{{inFlight=false}}
}}
update(); setInterval(update,POLL_MS);
</script></body></html>'''


def initialize_site(root: Path, campaign_id: str) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    catalog = catalog_payload()
    _atomic_json(root / "catalog.json", catalog)
    for report in REPORTS:
        page = _html_page(report.code, report.number, report.title, report.question)
        _atomic_text(root / f"{report.number}.html", page)
    first = min(int(report.number) for report in REPORTS)
    _atomic_text(root / "index.html", f'<meta http-equiv="refresh" content="0; url={first}.html">')
    manifest_path = root / "manifest.json"
    manifest = None
    if manifest_path.is_file():
        try:
            prior = json.loads(manifest_path.read_text(encoding="utf-8"))
            if str(prior.get("campaign_id")) == str(campaign_id):
                manifest = prior
        except (OSError, json.JSONDecodeError):
            manifest = None
    if manifest is None:
        manifest = {
            "service_contract": "gsd-report-service-5-on-request-only",
            "reporting_capabilities": "build178-numbered-progress-tmpfs", "campaign_id": campaign_id,
            "build_number": BUILD_NUMBER,
            "build_hash": runtime_fingerprint(),
            "runtime_fingerprint": runtime_fingerprint(),
            "run_provenance": dev_mode_provenance(),
            "generation_status": "starting", "fast_generation_status": "starting",
            "heavy_generation_status": "waiting", "last_check_utc": utc_now(),
            "analysis_phase": {"state": "idle", "campaign_id": campaign_id, "paused": False},
            "reports": {r.code: {"number": r.number, "title": r.title, "question": r.question,
                                        "status": "waiting", "revision": None, "stale": False} for r in REPORTS},
            "catalog_version": catalog["version"],
            "ui": catalog["ui_contract"],
        }
    else:
        prior_build = manifest.get("build_number")
        prior_catalog = manifest.get("catalog_version")
        manifest["service_contract"] = "gsd-report-service-5-on-request-only"
        manifest["reporting_capabilities"] = "build178-numbered-progress-tmpfs"
        manifest["build_number"] = BUILD_NUMBER
        manifest["build_hash"] = runtime_fingerprint()
        manifest["runtime_fingerprint"] = runtime_fingerprint()
        manifest["catalog_version"] = catalog["version"]
        manifest["ui"] = catalog["ui_contract"]
        if str(prior_build) != str(BUILD_NUMBER) or prior_catalog != catalog["version"]:
            manifest["report_revisions"] = {}
            manifest["format_refresh_required"] = True
            manifest["bundle_downloadable"] = False
            manifest["bundle_complete"] = False
        manifest.setdefault("analysis_phase", {"state": "idle", "campaign_id": campaign_id, "paused": False})
        reports = manifest.setdefault("reports", {})
        for definition in REPORTS:
            entry = reports.setdefault(definition.code, {"status": "waiting", "revision": None, "stale": False})
            entry.update({"number": definition.number, "title": definition.title, "question": definition.question})
            if entry.get("revision") and not (root / "reports" / f"{definition.code}.json").is_file():
                entry.update({"status": "waiting", "revision": None, "stale": True,
                              "error": None, "note": "snapshot body absent; the next requested cycle regenerates it"})
            elif "pause" in str(entry.get("note") or "").lower():
                entry["note"] = "the next requested cycle refreshes this last-good body"
        for code in [code for code in reports if code not in REPORT_BY_CODE]:
            del reports[code]
            (root / "reports" / f"{code}.json").unlink(missing_ok=True)
        manifest["last_check_utc"] = utc_now()
    _atomic_json(root / "manifest.json", manifest)
    return manifest


def _proc_io() -> dict[str, int]:
    result = {"read_bytes": 0, "write_bytes": 0, "rchar": 0, "wchar": 0}
    try:
        for line in Path("/proc/self/io").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key in result:
                result[key] = int(value.strip() or 0)
    except (OSError, ValueError):
        pass
    return result


def _report_dag() -> dict:
    return {
        "contract": "gsd-report-dag-3",
        "execution_policy": "serial-low-impact",
        "preprocessing": [
            {"id": "revision_check", "label": "revision preflight", "parallelizable": False},
            {"id": "snapshot", "label": "REPEATABLE READ snapshot collection + serialization", "parallelizable": False},
            {"id": "transport", "label": "stream/decompress immutable snapshot", "parallelizable": False},
            {"id": "load", "label": "bind shared frozen evidence", "parallelizable": False},
        ],
        "report_groups": [
            {"id": "phenotype", "reports": ["04", "05", "22"], "parallelizable": True},
            {"id": "landscape", "reports": ["10"], "parallelizable": True},
            {"id": "compute", "reports": ["14", "16", "23", "25"], "parallelizable": True},
            {"id": "decisions", "reports": ["28"], "parallelizable": True},
        ],
        "note": (
            "All report builders consume the same immutable snapshot and are logically independent after "
            "preprocessing. They execute serially at low priority so automatic "
            "reporting has bounded interference with scientific compute; a remote reporter may parallelize groups."
        ),
    }


def _diagnostics_base(campaign_id: str, phase: dict) -> dict:
    return {
        "contract": "gsd-report-diagnostics-2",
        "campaign_id": str(campaign_id),
        "request_id": phase.get("request_id"),
        "trigger_source": phase.get("trigger_source"),
        "state": phase.get("state"),
        "stage": phase.get("stage"),
        "started_utc": phase.get("started_utc"),
        "snapshot_revision": phase.get("snapshot_revision"),
        "dag": _report_dag(),
        "preprocessing": {},
        "reports": {},
        "cycle": {},
    }


_POOL_SNAPSHOT: dict | None = None


CHILD_PRIVATE_PEAK = {"bytes": 0}


def _private_bytes() -> int:
    try:
        text = Path("/proc/self/smaps_rollup").read_text()
    except OSError:
        return 0
    return sum(int(line.split()[1]) * 1024 for line in text.splitlines()
               if line.startswith(("Private_Clean:", "Private_Dirty:")))


def _build_in_child(code: str) -> tuple[dict, float, int]:
    started = time.monotonic()
    payload = build_report(code, _POOL_SNAPSHOT)
    return payload, time.monotonic() - started, _private_bytes()


def start_report_pool(snapshot: dict, codes: list[str], workers: int):
    global _POOL_SNAPSHOT
    if workers <= 1:
        return None, {}
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    _POOL_SNAPSHOT = snapshot
    import gc
    gc.collect()
    gc.freeze()
    pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork"))
    return pool, {code: pool.submit(_build_in_child, code) for code in codes}


BUILT_BEFORE_THE_CHILDREN = ("04", "14", "16", "23", "28")


def build_before_the_children(snapshot: dict, codes: list[str], note) -> dict:
    early: dict = {}
    for code in [c for c in codes if c in BUILT_BEFORE_THE_CHILDREN]:
        note(code)
        started = time.monotonic()
        try:
            early[code] = (build_report(code, snapshot), time.monotonic() - started)
        except Exception as exc:  # noqa: BLE001
            early[code] = exc
    return early


def end_report_pool(pool) -> None:
    import gc
    pool.shutdown(wait=True, cancel_futures=True)
    gc.unfreeze()


def report_payload(futures: dict, code: str, snapshot: dict, early: dict | None = None) -> tuple[dict, float | None]:
    from concurrent.futures.process import BrokenProcessPool
    made = (early or {}).get(code)
    if isinstance(made, BaseException):
        raise made
    if made is not None:
        return made
    future = futures.get(code)
    if future is not None:
        try:
            payload, seconds, private = future.result()
            CHILD_PRIVATE_PEAK["bytes"] = max(CHILD_PRIVATE_PEAK["bytes"], int(private or 0))
            return payload, seconds
        except BrokenProcessPool:
            pass
    return build_report(code, snapshot), None


def reports_in_catalog_order() -> list:
    return sorted(REPORTS, key=lambda d: int(d.number))


def run_report_cycle(client, campaign_id: str, root: Path) -> int:
    global UNCHANGED_WRITE_BYTES_SKIPPED, UNCHANGED_WRITES_SKIPPED
    UNCHANGED_WRITE_BYTES_SKIPPED = 0
    UNCHANGED_WRITES_SKIPPED = 0
    try:
        if client.nice:
            os.nice(int(os.environ.get("GSD_REPORT_NICE", "10")))
    except (AttributeError, OSError, ValueError):
        pass

    manifest = initialize_site(root, campaign_id)
    snapshot_file: Path | None = None
    pool = None
    cycle_started = time.monotonic()
    io_started = _proc_io()
    phase: dict = {}
    diagnostics: dict = {}
    cycle_id = uuid.uuid4().hex
    preflight_revisions: dict = {}
    try:
        state = client.state(campaign_id)
        phase = state or {}
        if phase.get("state") not in {"requested", "running"}:
            return 0

        diagnostics = _diagnostics_base(campaign_id, phase)
        diagnostics["state"] = "running"
        diagnostics["stage"] = "revision_check"
        diagnostics["preprocessing"]["revision_check"] = {
            "status": "running", "started_utc": utc_now(), "detail": "checking report-relevant revisions"
        }
        client.phase(campaign_id, state="running", started=True,
                      stage="preprocessing · revision check", error="", diagnostics=diagnostics)
        preflight_t0 = time.monotonic()
        try:
            preflight = client.revisions(campaign_id)
            preflight_revisions = {k: v for k, v in preflight.items()
                                   if str(k).endswith("_revision")}
        except Exception:
            preflight = {}
            preflight_revisions = {}
        diagnostics["preprocessing"]["revision_check"] = {
            "status": "ready", "finished_utc": utc_now(),
            "seconds": round(time.monotonic() - preflight_t0, 4),
            "detail": "report-relevant revision probe complete",
            "report_revision": preflight.get("report_revision"),
        }
        diagnostics["state"] = "running"
        diagnostics["stage"] = "snapshot"
        diagnostics["preprocessing"]["snapshot"] = {
            "status": "running", "started_utc": utc_now(), "fraction": 0.0,
            "detail": "collecting immutable database snapshot",
        }
        client.phase(campaign_id, state="running",
            stage="preprocessing · immutable REPEATABLE READ snapshot",
            error="", diagnostics=diagnostics,
        )
        manifest["generation_status"] = "running"
        manifest["analysis_phase"] = {**phase, "state": "running",
                                      "stage": "preprocessing · immutable snapshot"}
        manifest["report_dag"] = diagnostics["dag"]
        manifest["cycle"] = {"started_utc": utc_now(), "trigger_source": phase.get("trigger_source")}
        client.publish(campaign_id, "manifest", manifest)

        root.mkdir(parents=True, exist_ok=True)
        volatile = choose_volatile_dir(required_bytes=int(os.environ.get(
            "GSD_REPORT_SNAPSHOT_EXPECTED_BYTES", str(768 * 1024 * 1024))))
        spill_root = Path(volatile.get("path") or root)
        spill_root.mkdir(parents=True, exist_ok=True)
        snapshot_file = spill_root / f".gsd-report-spill-{os.getpid()}.json.gz"
        diagnostics["preprocessing"]["transport"] = {
            "status": "running", "started_utc": utc_now(), "storage": volatile,
            "detail": "streaming/decompressing snapshot into reporter memory",
        }
        snap_t0 = time.monotonic()
        replication, transfer = client.snapshot(campaign_id, spill_to=snapshot_file)
        snapshot_seconds = time.monotonic() - snap_t0
        snapshot_bytes = int(transfer.get("compressed_bytes") or 0)
        try:
            live_phase = client.state(campaign_id)
            live_pre = ((live_phase.get("diagnostics") or {}).get("preprocessing") or {})
            diagnostics["preprocessing"].update(live_pre)
        except Exception:
            pass
        diagnostics["preprocessing"].setdefault("snapshot", {}).update({
            "status": "ready", "finished_utc": utc_now(), "seconds": round(snapshot_seconds, 3)
        })
        diagnostics["preprocessing"]["transport"] = {
            "status": "ready", "finished_utc": utc_now(), "seconds": round(snapshot_seconds, 3),
            "compressed_bytes": snapshot_bytes,
            "decompressed_bytes": int(transfer.get("decompressed_bytes") or 0),
            "scratch_write_bytes": int(transfer.get("scratch_bytes") or 0),
            "storage_target": transfer.get("storage_target"), "spill_storage": volatile,
            "spilled": bool(transfer.get("spilled")),
        }
        diagnostics["preprocessing"]["load"] = {
            "status": "ready", "finished_utc": utc_now(), "seconds": 0.0,
            "detail": "shared frozen evidence bound in memory",
        }
        load_seconds = 0.0
        campaign_snapshots = replication.get("campaign_snapshots") or []
        primary = next((row for row in campaign_snapshots
                        if str(row.get("campaign_id")) == str(campaign_id)), None)
        if primary is None:
            raise RuntimeError(f"the snapshot did not contain the primary campaign {campaign_id}")
        snapshot = dict(primary)
        snapshot["replication_snapshot"] = replication
        revision = str(snapshot.get("source_revision") or replication.get("source_revision") or "")
        evidence_revision = content_hash({
            "home": snapshot.get("heavy_source_revision", revision),
            "replication": replication.get("source_revision"),
        })[:20]
        diagnostics["snapshot_revision"] = revision
        diagnostics["stage"] = "reports"
        diagnostics["cycle"].update({
            "snapshot_seconds": round(snapshot_seconds, 3),
            "snapshot_compressed_bytes": int(snapshot_bytes),
            "snapshot_load_seconds": round(load_seconds, 3),
            "api_bytes_transferred": int(transfer.get("compressed_bytes") or 0),
            "snapshot_decompressed_bytes": int(transfer.get("decompressed_bytes") or 0),
            "scratch_write_bytes": int(transfer.get("scratch_bytes") or 0),
            "snapshot_storage_target": transfer.get("storage_target"),
            "snapshot_spilled_to_disk": bool(transfer.get("spilled")),
            "snapshot_profile": replication.get("snapshot_profile"),
            "snapshot_full_campaign_count": len(replication.get("full_campaign_ids") or []),
            "snapshot_compact_peer_count": len(replication.get("compact_peer_campaign_ids") or []),
            **({"snapshot_stages": transfer["stages"]} if transfer.get("stages") else {}),
            **({"snapshot_resident_bytes": int(transfer["resident_bytes"])} if transfer.get("resident_bytes") else {}),
            **({"snapshot_bytes_estimated": True} if transfer.get("size_estimated") else {}),
            **({"snapshot_parts": transfer["parts"], "snapshot_other_part_bytes": transfer.get("other_part_bytes")}
               if transfer.get("parts") else {}),
            **({"snapshot_peak_bytes": int(transfer["peak_bytes"])} if transfer.get("peak_bytes") else {}),
        })
        client.phase(campaign_id, snapshot_revision=revision,
                      stage="shared snapshot ready · building reports", diagnostics=diagnostics)
        manifest["source_revision"] = revision
        manifest["replication_source_revision"] = replication.get("source_revision")
        manifest["replication_campaign_ids"] = replication.get("campaign_ids")
        manifest["analysis_phase"] = {"state": "running", "campaign_id": campaign_id,
                                      "snapshot_revision": revision,
                                      "stage": "building reports from the immutable snapshot",
                                      "paused": bool(phase.get("paused"))}
        manifest["cycle"].update(diagnostics["cycle"])
        client.publish(campaign_id, "manifest", manifest)

        errors: list[str] = []
        failed_reports: dict[str, str] = {}
        report_timings: dict[str, float] = {}
        workers, why = client.pool_size(phase.get("trigger_source"), transfer, len(REPORTS))
        diagnostics["cycle"]["report_pool"] = {"workers": workers, "why": why}
        CHILD_PRIVATE_PEAK["bytes"] = 0
        ordered = reports_in_catalog_order()
        early = build_before_the_children(snapshot, [d.code for d in ordered], lambda code: client.phase(
            campaign_id, stage=f"report {int(code)} · built before the children: it reads every measurement")
        ) if workers > 1 else {}
        pool, futures = start_report_pool(snapshot, [d.code for d in ordered if d.code not in early], workers)
        for position, definition in enumerate(ordered, start=1):
            stage = f"report {definition.number} · {position} of {len(ordered)} · {definition.title}"
            diagnostics["stage"] = stage
            diagnostics["current_report"] = definition.code
            diagnostics["reports"].setdefault(definition.code, {})
            diagnostics["reports"][definition.code].update({
                "number": definition.number, "title": definition.title, "question": definition.question,
                "status": "generating", "started_utc": utc_now(),
                "parallelizable_after_snapshot": True,
            })
            client.phase(campaign_id, stage=stage, diagnostics=diagnostics)
            entry = manifest["reports"][definition.code]
            entry.update({"status": "generating", "source_revision": revision,
                          "stale": False, "error": None})
            manifest["analysis_phase"]["stage"] = stage
            client.publish(campaign_id, "manifest", manifest)
            t0 = time.monotonic()
            try:
                payload, built_seconds = report_payload(futures, definition.code, snapshot, early)
                payload["number"] = definition.number
                payload["report_cycle_id"] = cycle_id
                payload["bundle_revision"] = revision
                client.publish(campaign_id, definition.code, payload)
                elapsed = built_seconds if built_seconds is not None else time.monotonic() - t0
                report_timings[definition.code] = elapsed
                entry.update({"status": "ready", "revision": payload.get("source_revision") or revision,
                              "bundle_revision": revision, "report_cycle_id": cycle_id,
                              "number": definition.number, "title": definition.title, "question": definition.question,
                              "evidence_revision": evidence_revision,
                              "generated_utc": payload.get("generated_utc") or utc_now(), "error": None,
                              "seconds": round(elapsed, 3)})
                diagnostics["reports"][definition.code].update({
                    "status": "ready", "finished_utc": utc_now(), "seconds": round(elapsed, 3)
                })
            except Exception as exc:
                elapsed = time.monotonic() - t0
                report_timings[definition.code] = elapsed
                message = f"{definition.code}: {type(exc).__name__}: {exc}"
                errors.append(message)
                failed_reports[definition.code] = message
                entry.update({"status": "error", "error": message, "failed_utc": utc_now(),
                              "seconds": round(elapsed, 3), "stale": True,
                              "stale_reason": "retained from prior successful revision",
                              "last_good_revision": entry.get("revision")})
                diagnostics["reports"][definition.code].update({
                    "status": "error", "finished_utc": utc_now(), "seconds": round(elapsed, 3),
                    "error": message,
                })
            client.publish(campaign_id, "manifest", manifest)
        if pool is not None:
            end_report_pool(pool)
            pool = None
        diagnostics["cycle"]["report_child_private_peak_bytes"] = CHILD_PRIVATE_PEAK["bytes"]

        cycle_state = classify_cycle(snapshot_ok=True, failed_reports=failed_reports)
        final_state = "complete_with_errors" if errors else "complete"
        error_text = "\n".join(errors)
        io_finished = _proc_io()
        total_seconds = time.monotonic() - cycle_started
        diagnostics["state"] = final_state
        diagnostics["stage"] = "report refresh complete"
        diagnostics["current_report"] = None
        diagnostics["cycle"].update({
            "total_seconds": round(total_seconds, 3),
            "report_seconds": {k: round(v, 3) for k, v in report_timings.items()},
            "read_bytes": max(0, io_finished["read_bytes"] - io_started["read_bytes"]),
            "write_bytes": max(0, io_finished["write_bytes"] - io_started["write_bytes"]),
            "character_read_bytes": max(0, io_finished["rchar"] - io_started["rchar"]),
            "character_write_bytes": max(0, io_finished["wchar"] - io_started["wchar"]),
            "unchanged_writes_skipped": int(UNCHANGED_WRITES_SKIPPED),
            "unchanged_bytes_skipped": int(UNCHANGED_WRITE_BYTES_SKIPPED),
            "finished_utc": utc_now(),
        })
        final_phase = client.phase(campaign_id, state=final_state,
                                    stage="reports immutable checkpoint complete", error=error_text,
                                    snapshot_revision=revision, finished=True, diagnostics=diagnostics)
        manifest["fast_generation_status"] = "on_request"
        manifest["heavy_generation_status"] = "on_request"
        manifest["analysis_phase"] = final_phase
        manifest["service_contract"] = "gsd-report-service-5-on-request-only"
        manifest["reporting_capabilities"] = "build178-numbered-progress-tmpfs"
        manifest["cycle"] = diagnostics["cycle"]
        manifest["report_dag"] = diagnostics["dag"]
        try:
            manifest["evidence"] = collect_evidence(
                client.fetch, root, campaign_id)
        except Exception as exc:
            manifest["evidence"] = {"contract": EVIDENCE_CONTRACT, "error": f"{type(exc).__name__}: {exc}"}
        manifest = apply_cycle_outcome(
            manifest, state=cycle_state, cycle_id=cycle_id, revision=revision,
            finished_utc=utc_now(), failed_reports=failed_reports,
            error=error_text, seconds=total_seconds,
        )
        manifest["report_revisions"] = preflight_revisions
        if cycle_state == COMPLETE:
            manifest.pop("format_refresh_required", None)
        client.publish(campaign_id, "manifest", manifest)
        return 0 if not errors else 2
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        diagnostics = diagnostics or _diagnostics_base(campaign_id, phase or {})
        diagnostics.update({"state": "error", "stage": "report cycle failed", "current_report": None})
        diagnostics.setdefault("cycle", {})["total_seconds"] = round(time.monotonic() - cycle_started, 3)
        diagnostics["cycle"]["finished_utc"] = utc_now()
        try:
            phase = client.phase(campaign_id, state="error",
                                  stage="report cycle failed; scientific fleet unaffected",
                                  error=message, finished=True, diagnostics=diagnostics)
        except Exception:
            phase = {"state": "error", "campaign_id": campaign_id,
                     "stage": "report cycle failed", "error": message}
        manifest["analysis_phase"] = phase
        manifest["cycle"] = diagnostics.get("cycle", {})
        manifest = apply_cycle_outcome(
            manifest, state=FAILED, cycle_id=cycle_id, revision=None,
            finished_utc=utc_now(), error=message,
            seconds=time.monotonic() - cycle_started,
        )
        try:
            client.publish(campaign_id, "manifest", manifest)
        except Exception:
            _atomic_json(root / "manifest.json", manifest)
        return 1
    finally:
        if pool is not None:
            import gc
            pool.shutdown(wait=False, cancel_futures=True)
            gc.unfreeze()
        if snapshot_file is not None:
            snapshot_file.unlink(missing_ok=True)
