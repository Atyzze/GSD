(() => {
  'use strict';
  const cfg = window.GSD_UI_CONFIG || {};
  const build = String(cfg.buildNumber || '176');
  const fingerprint = String(cfg.runtimeFingerprint || '');
  const shortFingerprint = String(cfg.runtimeShort || fingerprint.slice(0, 8) || '????????');
  const basePath = String(cfg.basePath || '');
  const selfScript=[...document.scripts].find(x=>/\/assets\/system\.js(?:[?#]|$)/.test(x.src));
  const scriptPrefix=(()=>{try{const u=new URL(selfScript?.src||'',location.href);return u.pathname.replace(/\/assets\/system\.js$/, '').replace(/\/$/,'')}catch(_){return ''}})();
  const externalBase = basePath || scriptPrefix || '';
  const admin = new URLSearchParams(location.hash.slice(1)).get('admin') || '';
  const api = p => cfg.relativeApi ? cfg.relativeApi.replace(/\/$/, '') + p : externalBase + p;
  const pageName = () => (window.GSD_ACTIVE_PAGE || (location.pathname.replace(/^\/+/, '').split('/')[0] || 'home'));
  const headers = () => Object.assign({'X-GSD-Page': pageName()}, admin ? {'X-GSD-Admin-Token': admin} : {});
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = n => Number(n || 0).toLocaleString();
  const num = n => (n === null || n === undefined || n === '' || !Number.isFinite(+n)) ? null : +n;
  const unit = (n, render) => { const v = num(n); return v === null ? '—' : render(v); };
  const gib = n => unit(n, v => (v / 1073741824).toFixed(1) + ' GiB');
  const pct = n => unit(n, v => Math.round(v) + '%');
  const watts = n => unit(n, v => v.toFixed(0) + ' W');
  const temp = n => unit(n, v => v.toFixed(0) + '°C');
  const gbps = n => unit(n, v => v.toFixed(1) + ' GB/s');
  const mbps = n => unit(n, v => (v / 1048576).toFixed(v >= 104857600 ? 0 : 1) + ' MiB/s');

  function route(path) {
    const clean = path.startsWith('/') ? path : '/' + path;
    const url = externalBase + (clean === '/' ? '/' : clean);
    return admin ? url.split('#')[0] + '#admin=' + encodeURIComponent(admin) : url;
  }
  function spark(values) {
    const vals = (values || []).map(num).filter(v => v !== null);
    if (!vals.length) return '<span class="gsd-spark-empty">—</span>';
    const chars = '▁▂▃▄▅▆▇█', max = Math.max(...vals, 1e-9), min = Math.min(...vals, 0);
    return vals.slice(-18).map(v => chars[Math.max(0, Math.min(7, Math.round((v-min)/(max-min||1)*7)))]).join('');
  }
  function navLink(label, key, href) {
    return `<a class="gsd-nav-link" data-gsd-page="${esc(key)}" href="${esc(route(href))}">${esc(label)}</a>`;
  }
  function makeHeader() {
    const host = document.getElementById('gsdSystemHeader');
    if (!host) return null;
    host.className = 'gsd-system-header';
    host.innerHTML = `
      <div class="gsd-header-top">
        <a class="gsd-build-home build-identity" data-gsd-page="home" href="${esc(route('/'))}" data-base-title="Runtime fingerprint ${esc(fingerprint || shortFingerprint)}." title="Runtime fingerprint ${esc(fingerprint || shortFingerprint)}. The short #${esc(shortFingerprint)} code is the first 8 hexadecimal characters of the SHA-256-derived identity of this executable runtime payload. The complete fingerprint is shown on System / Provenance.">
          <span class="gsd-build-dot"></span><span title="build ${esc(build)}: a law's full code is this build, its campaign and its graph, B${esc(build)}-C6-G7">B${esc(build)}</span><span class="gsd-build-hash">#${esc(shortFingerprint)}</span>${cfg.devMode?'<span class="gsd-dev-mode" title="GSD_DEV_MODE is set: the science freeze is advisory and policy epochs are mutable. Every decision, report and bundle from this run is stamped development_mode=true.">DEV MODE</span>':''}
        </a>
        <nav class="gsd-main-nav">
          ${navLink('Home','home','/')}${navLink('Map','map','/map')}${navLink('Campaigns','campaigns','/campaigns')}${navLink('Explorer','explorer','/explorer')}${navLink('Reports','reports','/reports')}${navLink('Calibration','calibration','/calibration')}${navLink('System','system','/system')}
        </nav>
        <div class="gsd-header-actions">
          <span id="gsdAdmin" class="gsd-admin-link" hidden></span>
          <button id="gsdTheme" class="gsd-control" title="Toggle light/dark theme">☼</button>
        </div>
      </div>
      <div class="gsd-header-stats">
        <div class="gsd-stat"><span>CPU</span><strong id="gsdCpu">—</strong><small id="gsdCpuDetail">—</small></div>
        <div class="gsd-stat"><span>RAM</span><strong id="gsdRam">—</strong><small id="gsdRamDetail">—</small></div>
        <div id="gsdMembwTile" class="gsd-stat gsd-stat-wide"><span>MEM BW</span><strong id="gsdMembw">—</strong><small id="gsdMembwHistory">—</small></div>
        <div class="gsd-stat"><span>COMPUTE</span><strong id="gsdCompute">—</strong><small id="gsdComputeDetail">—</small></div>
        <div class="gsd-stat"><span>DISK I/O</span><strong id="gsdDisk">—</strong><small id="gsdDiskDetail">—</small></div>
        <div class="gsd-stat"><span>GRAPHS · ALL CAMPAIGNS</span><strong id="gsdGraphs">—</strong><small id="gsdGraphsDetail">—</small></div>
        <div class="gsd-stat"><span>FRESHNESS</span><strong id="gsdFresh">—</strong><small id="gsdApiDetail">API warming</small></div>
      </div>`;
    return host;
  }

  function renderIncidentBanner(items, refreshError, heading) {
    let host = document.getElementById('gsdIncidentBanner');
    if (!items.length && !refreshError) { if (host) host.remove(); return; }
    if (!host) {
      host = document.createElement('div');
      host.id = 'gsdIncidentBanner';
      host.className = 'gsd-incident-banner';
      const shell = document.querySelector('.gsd-app-page:not([hidden])')
        || document.querySelector('.candidate-content') || document.body;
      shell.insertBefore(host, shell.firstChild);
    }
    const top = items[0];
    const origin = top && top.origin ? ` · ${top.origin}` : '';
    const repeat = top && top.count > 1 ? ` · seen ${top.count}x` : '';
    host.innerHTML =
      `<strong>${esc(heading || 'the dashboard is serving a stale snapshot')}</strong>`
      + `<span>${esc(top ? `${top.where}: ${top.error}` : refreshError)}${esc(origin)}${esc(repeat)}</span>`
      + (items.length > 1 ? `<span class="gsd-incident-more">${items.length - 1} other active fault(s)</span>` : '');
    host.title = top && top.traceback ? top.traceback : String(refreshError || '');
  }

  function applyTheme(theme) {
    const chosen = theme === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = chosen;
    document.documentElement.classList.toggle('day', chosen === 'light');
    if (document.body) document.body.classList.toggle('day', chosen === 'light');
    try { localStorage.setItem('gsd-theme', chosen); } catch (_) {}
    const b = document.getElementById('gsdTheme');
    if (b) { b.textContent = chosen === 'dark' ? '☼' : '☾'; b.title = `Switch to ${chosen === 'dark' ? 'light' : 'dark'} theme`; }
  }
  async function getJson(path) {
    const target=api(path), r = await fetch(target, {cache:'no-store', headers:headers()});
    if (!r.ok) {
      let detail = '';
      try { const j = await r.json(); detail = [j.error, j.detail, j.hint].filter(Boolean).join(' · '); } catch (_) {}
      throw new Error(`GET ${path} → HTTP ${r.status}${detail ? ': ' + detail : ''}`);
    }
    return r.json();
  }
  async function postJson(path, body) {
    const h = {'Content-Type':'application/json', ...headers()}, target=api(path);
    const r = await fetch(target, {method:'POST', cache:'no-store', headers:h, body:JSON.stringify(body)});
    if (!r.ok) {
      let detail = '';
      try { const j = await r.json(); detail = [j.error, j.hint].filter(Boolean).join(' · '); } catch (_) {}
      throw new Error(`POST ${path} → HTTP ${r.status}${detail ? ': ' + detail : ''}`);
    }
    return r.json();
  }
  let campaign = null, overview = null;
  function setText(id, text) { const e=document.getElementById(id); if(e)e.textContent=text; }
  function setActivePage(page) {
    document.querySelectorAll('[data-gsd-page]').forEach(a => a.classList.toggle('active', a.dataset.gsdPage === page));
  }
  window.GSD_SET_ACTIVE_PAGE = setActivePage;
  const coreHours = v => ((Number.isFinite(v) ? v : 0) / 3600);
  function computeHours(counts) {
    const seconds = ((counts || {}).compute || {}).core_seconds;
    if (!seconds) return 'warming';
    const hours = coreHours(seconds);
    return (hours >= 10 ? Math.round(hours) : hours.toFixed(1)) + ' core-h accumulated';
  }
  const lastCpu = {value: null, at: 0};
  function cpuShown(value, busy, now = Date.now()) {
    const missed = !Number.isFinite(value) || (value === 0 && busy > 0);
    if (!missed) { lastCpu.value = value; lastCpu.at = now; return {text: pct(value), stale: false}; }
    if (lastCpu.value == null) return {text: pct(value), stale: false};
    return {text: pct(lastCpu.value), stale: true, age: Math.max(0, Math.round((now - lastCpu.at) / 1000))};
  }
  const STUDY_COUNT_FIELDS = ['graph_jobs_created', 'graphs_finished_last_hour', 'completed_graph_realizations',
    'burned_graph_ordinals', 'simulation_leases', 'simulation_executions', 'claims_without_execution',
    'graphs_grown', 'graphs_grown_last_hour'];
  function studyCounts(d) {
    const listed = Array.isArray(d.campaigns) && d.campaigns.length;
    const rows = listed ? d.campaigns.map(c => ({id: String(c.campaign_id), counts: c.runtime_counts || {}}))
      : [{id: String(d.campaign_id ?? campaign ?? ''), counts: d.runtime_counts || {}}];
    const total = {campaigns: rows, compute: {}};
    for (const {counts} of rows) {
      for (const key of STUDY_COUNT_FIELDS) {
        if (counts[key] != null) total[key] = (total[key] || 0) + (Number(counts[key]) || 0);
      }
      for (const [key, value] of Object.entries(counts.compute || {})) {
        total.compute[key] = (total.compute[key] || 0) + (Number(value) || 0);
      }
    }
    return total;
  }
  function updateHeader(d, roundtripMs) {
    overview = d;
    const r = d.system_resources || {}, bw = r.memory_bandwidth || {}, util = d.compute_utilization || {};
    const counts = studyCounts(d);
    const cpu = cpuShown(num(r.cpu_percent), Number(util.active_total ?? ((util.simulation_busy||0)+(util.analysis_busy||0))));
    setText('gsdCpu', cpu.text);
    const cpuNode = document.getElementById('gsdCpu');
    if (cpuNode) { if (cpu.stale) cpuNode.classList.add('stale-reading'); else cpuNode.classList.remove('stale-reading'); }
    setText('gsdCpuDetail', `${temp(r.cpu_temperature_celsius)} · ${watts(r.cpu_power_watts)}`);
    const cpuTile = document.getElementById('gsdCpu');
    const side = r.cpu_power_sidecar || {};
    const sidecarBecause = side.no_watts_because ? `\nWhy: ${side.no_watts_because}` : '';
    const withdrawn = side.watts_withdrawn_age_seconds == null ? ''
      : `\nLast wattage drawn ${Math.round(side.watts_withdrawn_age_seconds)}s ago and withheld since`;
    const startedWhere = side.started_by
      ? `\nSidecar started by the ${side.started_by}, ${side.exec_inside_scratch_namespace
          ? 'inside the scratch namespace' : 'outside the scratch namespace'}`
        + `; btop carries ${(side.btop_capabilities || []).join(', ') || 'no capabilities'}`
      : '';
    const sidecarWhy = side.last_error ? `\nSidecar: ${side.last_error}${sidecarBecause}${withdrawn}${startedWhere}`
      : (side.running === false ? `\nSidecar: not running${sidecarBecause}${startedWhere}`
        : (side.running && side.watts == null
          ? sidecarBecause + withdrawn
            + `\nSidecar running (pid ${side.pid ?? '?'}), ${side.frames_without_watts ?? 0} frame(s) drawn with a temperature and no watts`
            + startedWhere
            + (side.config_seeded_from ? `\nbtop config seeded from ${side.config_seeded_from}` : '\nbtop config is ours, not yours: it has none to copy')
            + (side.cpu_line_without_watts ? `\nLast CPU line: ${side.cpu_line_without_watts.slice(-160)}` : '')
          : ''));
    if (cpuTile) cpuTile.title =
      (cpu.stale ? `CPU ${cpu.text} is the last good reading, ${cpu.age} s ago: the newest sample had none.\n` : '')
      + (r.cpu_power_watts == null
        ? `No CPU package power reading. ${r.cpu_power_detail || 'no detail reported'}${sidecarWhy}`
        : `CPU package power from ${r.cpu_power_source || 'an unnamed source'}: ${r.cpu_power_detail || ''}`)
      + (r.cpu_power_limit_watts == null ? '' : `\nPackage limit ${r.cpu_power_limit_watts} W.`)
      + (r.cpu_temperature_source ? `\nTemperature from ${r.cpu_temperature_source}` : '')
      + (r.cpu_temperature_path ? ` (${r.cpu_temperature_path})` : '')
      + '\nRun `main.py hardware` outside the fleet to compare.';
    setText('gsdRam', `${gib(r.memory_used_bytes)} / ${gib(r.memory_total_bytes)}`);
    setText('gsdRamDetail', `${pct(r.memory_load_percent)} used · ${gib(r.memory_free_bytes)} available`);
    setText('gsdMembw', gbps(bw.bandwidth_gbps));
    const bwTile = document.getElementById('gsdMembwTile');
    const bwZeros = (bw.history_gbps || []).length >= 3 && (bw.history_gbps || []).every(v => +v === 0);
    if (bwTile) bwTile.title =
      (bw.available ? `Memory bandwidth from ${bw.source || 'an unnamed collector'}`
        + (bw.sample_age_seconds == null ? '' : `, its sample ${bw.sample_age_seconds} s old`)
        : `No memory-bandwidth reading: ${bw.status || 'no collector reported'}`)
      + (bw.cap_gbps == null ? '' : `\nCap ${bw.cap_gbps} GB/s (${bw.cap_source || 'unnamed'})`)
      + (bw.available && bw.status ? `\nCollector status: ${bw.status}` : '')
      + (bwZeros ? '\nEvery recent sample reads 0: a collector reading zeros has usually lost the AMD UMC counters '
        + 'to another perf session; `pgrep -af umc_mem_bandwidth` names every one.' : '');
    const bwNode=document.getElementById('gsdMembwHistory'); if(bwNode) bwNode.innerHTML=`${spark(bw.history_gbps)} ${bw.utilization_percent==null?'':Math.round(bw.utilization_percent)+'%'}`.trim();
    const active = util.active_total ?? ((util.simulation_busy||0)+(util.analysis_busy||0));
    const exposed = util.total_slots ?? util.scheduler_total_slots;
    const runnable = (util.queued_simulations||0) + (util.claimable_analyses||0);
    const bottleneck = d.operational_bottleneck || {};
    const analysesBusy = Number(util.analysis_busy || 0);
    setText('gsdComputeDetail', (analysesBusy ? `${analysesBusy} analys${analysesBusy === 1 ? 'is' : 'es'} · ` : '')
      + computeHours(counts));
    if (util.scheduler_snapshot_inconsistent || (num(exposed) !== null && num(active) > num(exposed))) {
      setText('gsdCompute', `${active} active · updating`);
      const warming = document.getElementById('gsdCompute');
      if (warming) warming.title =
        `${active} executor slots report busy while the scheduler snapshot is still settling, `
        + `so the cap is not quoted.\n${runnable} unit(s) of work runnable.`;
    } else {
      const sim = Number(util.simulation_busy || 0), ana = Number(util.analysis_busy || 0);
      setText('gsdCompute', `${active} active · cap ${exposed ?? '—'}`);
      const computeTile = document.getElementById('gsdCompute');
      if (computeTile) computeTile.title =
        `${active} of ${exposed ?? '—'} executor slots busy: ${sim} running a chain, `
        + `${ana} running probes.\n`
        + `Capacity verdict: ${bottleneck.state || 'warming'}.`
        + (bottleneck.explanation ? `\n${bottleneck.explanation}` : '')
        + '\nThe full verdict and its storage attribution are on the System page.'
        + '\nThe core-hours below are every campaign of this folder, as GRAPHS is (575).';
    }
    setText('gsdDisk', r.disk_write_bytes_per_second==null ? '—' : `W ${mbps(r.disk_write_bytes_per_second)}`);
    const iowait = d.io_summary?.cpu_iowait_percent;
    const ioLabel = bottleneck.state==='DISK_IO_LIMITED' ? 'I/O limiting' : 'not I/O-limited';
    setText('gsdDiskDetail', r.disk_read_bytes_per_second==null ? 'rate warming' : `R ${mbps(r.disk_read_bytes_per_second)} · ${iowait==null?'—':iowait+'%'} wait`);
    const diskTile = document.getElementById('gsdDisk');
    if (diskTile) diskTile.title =
      `Physical device aggregate. ${ioLabel}.\n`
      + 'Whether disk is the constraint is the capacity verdict, which is on the '
      + 'System page together with the PostgreSQL and scratch-tier attribution '
      + 'that says which writer is responsible.';
    const created = counts.graph_jobs_created || 0;
    const done = counts.completed_graph_realizations || 0;
    const burned = counts.burned_graph_ordinals || 0;
    const grown = counts.graphs_grown ?? created;
    setText('gsdGraphs', fmt(grown));
    const churn = counts.claims_without_execution || 0;
    const spend = counts.compute || {};
    const perHour = counts.graphs_finished_last_hour;
    const grownPerHour = counts.graphs_grown_last_hour ?? perHour;
    setText('gsdGraphsDetail', grownPerHour == null ? 'rate warming'
            : `${fmt(grownPerHour)}/h over the last hour`);
    const graphsTile = document.getElementById('gsdGraphs');
    const shown = counts.campaigns.filter(row => row.id);
    const perCampaign = shown.length > 1 ? '\n\n' + shown.slice()
      .sort((a, b) => a.id.localeCompare(b.id, undefined, {numeric: true}))
      .map(({id, counts: c}) => `C${id}: ${fmt(c.graphs_grown ?? c.graph_jobs_created ?? 0)} graphs from `
        + `${fmt(c.graph_jobs_created || 0)} simulations created, `
        + `${fmt(c.completed_graph_realizations || 0)} finished, ${fmt(c.graphs_finished_last_hour || 0)} in the last hour`)
      .join('\n') : '';
    const scope = counts.campaigns.length === 1
      ? (shown.length ? `campaign ${shown[0].id}, the folder's only one` : "the folder's one campaign")
      : `the ${fmt(counts.campaigns.length)} campaigns of this folder`;
    if (graphsTile) graphsTile.title =
      `${fmt(grown)} graphs grown in ${scope}: each simulation grows its seed's chains one after another (one from `
      + 'empty and one from each start its campaign lists), so a graph is one chain, as the fleet ladder counts them; '
      + `${fmt(grownPerHour || 0)} grown in the last hour.\n`
      + `${fmt(created)} simulations created, ${fmt(done)} of them finished; `
      + `${fmt(perHour || 0)} finished in the last hour. A simulation grows one seed of one law at one rung: it is `
      + 'created when its rung is bought, so the count steps up as rungs are bought and the finished count follows. '
      + 'A seed run again as a longer chain is a second simulation of the same graph, so each campaign\'s row on the '
      + 'Campaigns page gives both: its graphs (each seed of each law at a rung once) and its simulations, the '
      + 'finished ones this tile adds up.'
      + perCampaign + '\n\n'
      + (burned
         ? `${fmt(burned)} ordinals were reserved and never used, so codes run ahead of the graph count.`
         : 'No ordinals have been reserved and left unused, so an ensemble code counts graphs.')
      + `\n\n${fmt(counts.simulation_leases || 0)} simulation leases taken, `
      + `${fmt(counts.simulation_executions || 0)} of which started a child process. `
      + 'A lease is counted when a worker claims the row, before anything decides it will run: '
      + 'a job refused on memory or whose lease expires is counted and released without executing.'
      + (churn ? `\n${fmt(churn)} claims were taken and never ran.` : '')
      + `\n\nCompute spent: ${fmt(Math.round(spend.core_seconds || 0))} core-seconds of wall time `
      + 'summed across every attempt. One worker occupies one configured CPU slot, so wall time '
      + 'per attempt is core time.\n'
      + `Simulation ${coreHours(spend.simulation_core_seconds).toFixed(2)} core-h, `
      + `analysis ${coreHours(spend.analysis_core_seconds).toFixed(2)} core-h, `
      + `of which ${coreHours(spend.unsuccessful_core_seconds).toFixed(2)} core-h ended in a `
      + 'non-zero exit. Failed and cancelled attempts are included because they were paid for.';
    setText('gsdFresh', Number.isFinite(roundtripMs) ? Math.round(roundtripMs)+' ms' : 'live');
    setText('gsdApiDetail', 'API round-trip');
    const chip=document.getElementById('gsdCampaignState'); if(chip){chip.textContent=d.paused?'PAUSED':'RUNNING';chip.classList.toggle('paused',!!d.paused)}
    const identity=document.querySelector('.gsd-build-home');
    if(identity){
      identity.classList.toggle('paused',!!d.paused);
      identity.classList.add('build-identity');
      const base=identity.dataset.baseTitle||'';
      identity.title=(d.paused?'FLEET PAUSED \u00b7 ':'')+base;
    }
    window.dispatchEvent(new CustomEvent('rr:overview',{detail:d}));
  }
  let campaignRows = [];
  function studyOf(camp) {
    const row = (campaignRows || []).find(x => String(x.campaign_id) === String(camp));
    const study = row && row.study;
    return study == null || study === '' ? null : String(study);
  }
  function lawCode(camp, ordinal, law, study) {
    const s = study !== undefined ? study : studyOf(camp);
    if (ordinal != null && ordinal !== '') return s ? `S${s}C${camp}G${ordinal}` : `C${camp}-G${ordinal}`;
    return `${s ? `S${s}` : ''}C${camp}-${String(law || '').slice(0, 8)}`;
  }
  function lawCodeQuery(q) {
    const m = /^(?:s([a-z0-9._]+?)-?)?(?:b\d+-)?(?:c(\d+))?-?(?:g-?(\d+))?$/.exec(String(q || '').replace(/\s+/g, '').toLowerCase());
    return m && (m[2] != null || m[3] != null) ? {study: m[1] ?? null, campaign: m[2] ?? null, ordinal: m[3] != null ? +m[3] : null} : null;
  }

  function switchCampaign(next) {
    if (!next || String(next) === String(campaign)) return;
    campaign = String(next);
    window.GSD_CAMPAIGN = campaign;
    try {
      const url = new URL(location.href);
      url.searchParams.set('campaign', campaign);
      history.replaceState(null, '', url);
    } catch (err) {  }
    window.dispatchEvent(new CustomEvent('rr:campaign', { detail: { campaign } }));
    poll();
  }

  async function selectCampaign() {
    const rows = await getJson('/api/campaigns');
    campaignRows = Array.isArray(rows) ? rows : [];
    const requested = new URLSearchParams(location.search).get('campaign');
    const chosen = (requested && campaignRows.find(x=>String(x.campaign_id)===String(requested)))
      || campaignRows[0] || {};
    campaign = String(chosen.campaign_id || '1');
    if ((!requested || requested === 'study') && campaignRows.length > 1) {
      try {
        const study = await getJson('/api/landscape/study?meta=1');
        if ((study.batches || []).length > 1) campaign = 'study';
      } catch (err) {  }
    }
    window.GSD_CAMPAIGN = campaign;
    window.dispatchEvent(new CustomEvent('rr:campaign',{detail:{campaign}}));
  }

  async function refreshCampaignList(select) {
    try {
      const rows = await getJson('/api/campaigns');
      campaignRows = Array.isArray(rows) ? rows : campaignRows;
    } catch (err) { return campaignRows; }
    if (select && campaignRows.some(x => String(x.campaign_id) === String(select))) {
      switchCampaign(String(select));
    } else if (campaign !== 'study' && campaignRows.length
               && !campaignRows.some(x => String(x.campaign_id) === String(campaign))) {
      switchCampaign(String(campaignRows[0].campaign_id));
    }
    return campaignRows;
  }
  let pollTimer = null, failedPolls = 0;
  const STALE_AFTER_MS = 3 * 4000;
  function freshnessOf(response, failed) {
    if (failed >= 2) return {state: 'offline', why: 'the dashboard cannot reach its API; what is shown may be old'};
    if (!response) return {state: 'cold', why: null};
    const error = response.last_refresh_error || null;
    if (response.pending) return {state: 'cold', why: error};
    const age = Number(response.source_age_ms);
    const limit = Number(response.stale_after_ms) > 0 ? Number(response.stale_after_ms) : STALE_AFTER_MS;
    if (error || (Number.isFinite(age) && age > limit)) {
      return {state: 'stale', age, why: error || `the snapshot is ${Math.round(age / 1000)} s old`};
    }
    return {state: 'fresh', age, why: null};
  }
  function showFreshness(fresh, incidents) {
    if (document.body) document.body.dataset.gsdFreshness = fresh.state;
    if (fresh.state === 'stale') {
      setText('gsdFresh', Number.isFinite(fresh.age) ? `${Math.round(fresh.age / 1000)} s old` : 'stale');
      renderIncidentBanner(incidents, fresh.why);
    } else if (fresh.state === 'offline') {
      renderIncidentBanner([], fresh.why, 'the dashboard is offline');
    } else if (fresh.state === 'cold') {
      renderIncidentBanner(fresh.why ? incidents : [], fresh.why);
    } else {
      renderIncidentBanner([], null);
    }
  }
  async function poll() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    try {
      if (!campaign) await selectCampaign();
      const asked=campaign;
      const t0=performance.now(), d=await getJson('/api/overview/'+encodeURIComponent(asked));
      const roundtrip=performance.now()-t0;
      if (String(asked) !== String(campaign)) return;
      failedPolls = 0;
      if (!d.dashboard_response?.pending) {
        updateHeader(d,roundtrip);
        showFreshness(freshnessOf(d.dashboard_response, 0), d.dashboard_response?.incidents || []);
      } else {
        setText('gsdFresh',Math.round(roundtrip)+' ms');
        const refreshError=d.dashboard_response?.last_refresh_error;
        setText('gsdApiDetail', refreshError ? `overview refresh failed · ${refreshError}` : 'API warming');
        const apiDetail=document.getElementById('gsdApiDetail');
        if(apiDetail) apiDetail.title = refreshError
          ? `overview refresh failed\n\n${refreshError}\n\nThe dashboard is serving the last good snapshot, so every number on this page may be stale. The full traceback is on stderr and on the System page.`
          : 'API round-trip';
        showFreshness(freshnessOf(d.dashboard_response, 0), d.dashboard_response?.incidents || []);
      }
    } catch (e) {
      failedPolls += 1;
      setText('gsdFresh','offline'); setText('gsdApiDetail',String(e));
      showFreshness(freshnessOf(null, failedPolls), []);
    }
    finally { pollTimer = setTimeout(poll, 4000 ); }
  }
  function installRouter() {
    document.addEventListener('click', ev => {
      const a=ev.target.closest('a[data-gsd-page]');
      if(!a || !window.GSD_NAVIGATE || ev.defaultPrevented || ev.button!==0 || ev.metaKey||ev.ctrlKey||ev.shiftKey||ev.altKey) return;
      ev.preventDefault(); window.GSD_NAVIGATE(a.dataset.gsdPage, a.getAttribute('href'));
    });
  }
  let headerHeight = null;
  function measureHeaderHeight(host) {
    const el = host || document.getElementById('gsdSystemHeader');
    if (!el) return headerHeight;
    const box = typeof el.getBoundingClientRect === 'function' ? el.getBoundingClientRect() : null;
    const measured = Math.round((box && box.height) || el.offsetHeight || 0);
    if (!(measured > 0) || measured === headerHeight) return headerHeight;
    headerHeight = measured;
    document.documentElement.style.setProperty('--gsd-header-h', measured + 'px');
    try { window.dispatchEvent(new CustomEvent('rr:hero-metrics', {detail: {headerHeight: measured}})); }
    catch (_) {}
    return measured;
  }
  function watchHeaderHeight(host) {
    measureHeaderHeight(host);
    if (typeof ResizeObserver === 'function') {
      try { new ResizeObserver(() => measureHeaderHeight(host)).observe(host); } catch (_) {}
    }
    addEventListener('resize', () => measureHeaderHeight(host));
  }

  const headerHost = makeHeader();
  const ADMIN_SAYS = {
    current: ['admin', 'ok', "This page's admin link is this run's: its changes are accepted."],
    stale: ['admin link from an earlier run', 'warn', "This page's admin link is not this run's. Every start makes a new one and the old one stops working, so the server refuses this page's changes. Open the link the run made (var/run/dashboard-admin)."],
  };
  async function refreshAccess() {
    let link = admin ? 'stale' : 'none';
    try {
      const r = await fetch(api('/api/access'), {cache: 'no-store', headers: headers()});
      if (r.ok) link = (await r.json()).link || link;
      else if (!admin) link = 'none';
      else return;
    } catch (_) { return; }
    document.documentElement.dataset.admin = link;
    const badge = document.getElementById('gsdAdmin');
    if (!badge) return;
    const said = ADMIN_SAYS[link];
    badge.hidden = !said;
    if (said) { badge.textContent = said[0]; badge.className = 'gsd-admin-link ' + said[1]; badge.title = said[2]; }
  }
  refreshAccess();
  setInterval(refreshAccess, 30000);
  if (headerHost) {
    let theme='dark'; try { theme=localStorage.getItem('gsd-theme')||'dark'; } catch(_) {}
    applyTheme(theme);
    document.getElementById('gsdTheme').onclick=()=>applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
    installRouter(); watchHeaderHeight(headerHost); poll();
  }

  const LOCAL_ZONE = (() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'local'; }
    catch (e) { return 'local'; }
  })();

  function parseUtc(value){
    if(value==null||value==='') return null;
    const text=String(value).trim();
    if(text==='—'||text==='-') return null;
    const normalised=/[Zz]$|[+-]\d{2}:?\d{2}$/.test(text)?text:text.replace(' ','T')+'Z';
    const parsed=new Date(normalised);
    return Number.isNaN(parsed.getTime())?null:parsed;
  }

  function localTime(value,{seconds=true,dateOnly=false}={}){
    const parsed=parseUtc(value);
    if(!parsed) return value==null?'—':String(value);
    const opts=dateOnly
      ? {year:'numeric',month:'short',day:'2-digit'}
      : {year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',
         ...(seconds?{second:'2-digit'}:{}) ,hour12:false};
    try { return parsed.toLocaleString(undefined,opts); }
    catch (e) { return String(value); }
  }

  function localTimeHtml(value,opts){
    const parsed=parseUtc(value);
    if(!parsed) return esc(value==null?'—':String(value));
    return `<span class="local-time" title="${esc(String(value))} (UTC)">`
      + `${esc(localTime(value,opts))}</span>`;
  }

  function relativeTime(value){
    const parsed=parseUtc(value);
    if(!parsed) return '';
    const seconds=Math.round((Date.now()-parsed.getTime())/1000);
    const abs=Math.abs(seconds), suffix=seconds>=0?'ago':'from now';
    if(abs<60) return `${abs}s ${suffix}`;
    if(abs<3600) return `${Math.round(abs/60)}m ${suffix}`;
    if(abs<86400) return `${Math.round(abs/3600)}h ${suffix}`;
    return `${Math.round(abs/86400)}d ${suffix}`;
  }

  const hoverRegions=new Set();
  let pinnedKey=null;

  function registerLiveRegion(element){
    if(!element||hoverRegions.has(element)) return;
    for(const known of hoverRegions){ if(known.isConnected===false) hoverRegions.delete(known); }
    hoverRegions.add(element);
    const replay=()=>{ if(element._deferredRedraw){const fn=element._deferredRedraw;element._deferredRedraw=null;fn();} };
    element.addEventListener('pointerenter',()=>{element.dataset.hovering='1';});
    element.addEventListener('pointermove',replay);
    element.addEventListener('pointerleave',()=>{ delete element.dataset.hovering; replay(); });
  }

  function pointerIsOverLiveRegion(){
    for(const element of hoverRegions){ if(element.isConnected!==false&&element.dataset.hovering) return true; }
    return false;
  }

  function deferrableRedraw(element,redraw,{force=false}={}){
    if(force||!element||!element.dataset.hovering){ if(element) element._deferredRedraw=null; return false; }
    element._deferredRedraw=redraw;
    return true;
  }

  function setPinned(key){ pinnedKey=key||null; }
  function getPinned(){ return pinnedKey; }
  window.GSD_SYSTEM={freshnessOf,STALE_AFTER_MS,api,getJson,postJson,headers,route,esc,fmt,gib,mbps,measureHeaderHeight,updateHeader,registerLiveRegion,pointerIsOverLiveRegion,deferrableRedraw,setPinned,getPinned,localTime,localTimeHtml,relativeTime,parseUtc,LOCAL_ZONE,switchCampaign,refreshCampaignList,studyOf,lawCode,lawCodeQuery,set campaignRows(v){campaignRows=Array.isArray(v)?v:[];},get campaignRows(){return campaignRows;},get campaign(){return campaign;},get overview(){return overview;}};
})();
