(() => {
  'use strict';
  const VERSION='hamiltonian-visual-1';
  const KNOWN={
    edge_count:'#58a6ff', degree_anchor:'#63d58a', degree_anchor_abs:'#32c5d2',
    degree_square_sum:'#b197fc', degree_cube_sum:'#d783ff', degree_fourth_sum:'#f078b8',
    degree_neighbor_gradient:'#ff8b63', wedge_count:'#e3b341', triangle_count:'#ffcf5c',
    triangle_edge_overlap:'#f29d49', square_count:'#4fd6be', induced_square_count:'#64c9ff',
    square_edge_overlap:'#8bafff'
  };
  const LABEL={
    edge_count:'edge',degree_anchor:'degree anchor',degree_anchor_abs:'|degree anchor|',
    degree_square_sum:'Σd²',degree_cube_sum:'Σd³',degree_fourth_sum:'Σd⁴',
    degree_neighbor_gradient:'neighbor Δd²',wedge_count:'wedge',triangle_count:'triangle',
    triangle_edge_overlap:'triangle overlap',square_count:'square',induced_square_count:'induced square',
    square_edge_overlap:'square overlap'
  };
  const SCALE={one:'1',log_N:'ln N',inv_log_N:'1/ln N',inv_N:'1/N',inv_sqrt_N:'1/√N',power:'N^p'};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function hash(s){let h=2166136261;for(const c of String(s||'')){h^=c.charCodeAt(0);h=Math.imul(h,16777619)}return h>>>0}
  function color(op){op=String(op||'unknown');if(KNOWN[op])return KNOWN[op];return `hsl(${hash(op)%360} 62% 58%)`}
  function label(op){op=String(op||'unknown');return LABEL[op]||op.replaceAll('_',' ')}
  function coeffText(term){const c=term?.coeff||{};const raw=c.c0;const n=Number(raw);return Number.isFinite(n)?`${n>=0?'+':''}${Number(n.toPrecision(6))}`:String(raw??'?')}
  function scaleText(term){const c=term?.coeff||{},s=String(c.scale||'one');if(s==='power')return `N^${Number.isFinite(+c.p)?Number((+c.p).toPrecision(5)):c.p??'?'}`;return SCALE[s]||s}
  function paramsText(term){const p=term?.params||{},pairs=Object.entries(p);return pairs.length?pairs.map(([k,v])=>`${k}=${v}`).join(', '):''}
  function normalize(input){if(Array.isArray(input))return input;if(input&&Array.isArray(input.terms))return input.terms;return []}
  function chip(term,{compact=false}={}){const op=String(term?.op||'unknown'),c=term?.coeff||{},n=Number(c.c0),sign=Number.isFinite(n)&&n<0?'negative':'positive',mag=Number.isFinite(n)?Math.min(1,Math.max(.18,Math.log10(1+Math.abs(n)*9)/1.5)):.45;const col=color(op),scale=scaleText(term),params=paramsText(term),label=LABEL[op]||op;const exact=`${coeffText(term)} × ${scale} · ${op}${params?' · '+params:''}`;return `<span class="gsd-term-chip gsd-term-${sign}" style="--term:${esc(col)};--term-alpha:${mag.toFixed(3)}" title="${esc(exact)}"><span class="gsd-term-dot"></span><b>${esc(label)}</b>${compact?'':`<span class="gsd-term-coeff">${esc(coeffText(term))}</span><span class="gsd-term-scale">${esc(scale)}</span>${params?`<span class="gsd-term-param">${esc(params)}</span>`:''}`}</span>`}
  function html(input,opts={}){const terms=normalize(input);if(!terms.length)return '<span class="gsd-term-none">no Hamiltonian terms</span>';return `<span class="gsd-term-strip" data-grammar="${VERSION}">${terms.map(t=>chip(t,opts)).join('')}</span>`}
  function summary(input){const terms=normalize(input),pos=terms.filter(t=>Number(t?.coeff?.c0)>=0).length,neg=terms.filter(t=>Number(t?.coeff?.c0)<0).length,scales=new Set(terms.map(t=>String(t?.coeff?.scale||'one')));return `${terms.length} terms · ${pos} positive · ${neg} negative · ${scales.size} scaling class${scales.size===1?'':'es'}`}
  window.GSD_TERMS={version:VERSION,color,label,chip,html,summary,scaleText,coeffText};
})();
