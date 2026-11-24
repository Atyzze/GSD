mermaid.initialize({startOnLoad:false, htmlLabels:false, theme:'neutral', flowchart:{htmlLabels:false, curve:'basis', nodeSpacing:40, rankSpacing:55, useMaxWidth:false}, themeVariables:{fontFamily:'DejaVu Sans, Arial, sans-serif', fontSize:'15px'}});
const FONT='DejaVu Sans, Arial, sans-serif';
function hex(c){const m=c.match(/rgba?\(([^)]+)\)/);if(!m)return null;const p=m[1].split(',').map(s=>parseFloat(s));if(p.length===4&&p[3]===0)return null;return {hex:'#'+p.slice(0,3).map(v=>Math.round(v).toString(16).padStart(2,'0')).join(''),alpha:p.length===4?p[3]:1};}
const f2=v=>(+v).toFixed(2).replace(/\.?0+$/,'');
const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
window.flatten=function(){
  const svg=document.querySelector('svg');const inv=svg.getScreenCTM().inverse();
  const toRoot=el=>inv.multiply(el.getScreenCTM());
  const pt=(m,x,y)=>({x:m.a*x+m.c*y+m.e,y:m.b*x+m.d*y+m.f});
  const out=[];let minX=1e9,minY=1e9,maxX=-1e9,maxY=-1e9;
  const grow=(x,y)=>{minX=Math.min(minX,x);minY=Math.min(minY,y);maxX=Math.max(maxX,x);maxY=Math.max(maxY,y)};
  const paint=cs=>{const a=[];const f=hex(cs.fill);a.push(`fill="${f?f.hex:'none'}"`);if(f&&f.alpha<1)a.push(`fill-opacity="${f2(f.alpha*(+cs.fillOpacity||1))}"`);else if(f&&+cs.fillOpacity<1)a.push(`fill-opacity="${f2(cs.fillOpacity)}"`);
    const s=hex(cs.stroke);if(s&&cs.stroke!=='none'&&parseFloat(cs.strokeWidth)>0){a.push(`stroke="${s.hex}"`,`stroke-width="${f2(parseFloat(cs.strokeWidth))}"`);if(s.alpha<1)a.push(`stroke-opacity="${f2(s.alpha)}"`);if(cs.strokeDasharray&&cs.strokeDasharray!=='none')a.push(`stroke-dasharray="${cs.strokeDasharray.replace(/px/g,'').replace(/,\s*/g,' ')}"`);}
    else a.push('stroke="none"');if(+cs.opacity<1)a.push(`opacity="${f2(cs.opacity)}"`);return a.join(' ')};
  const hidden=el=>{for(let e=el;e&&e!==svg;e=e.parentElement){const t=e.tagName.toLowerCase();if(t==='marker'||t==='defs'||t==='clippath'||t==='mask')return true;const cs=getComputedStyle(e);if(cs.display==='none'||cs.visibility==='hidden'||+cs.opacity===0)return true;}return false};
  const walker=document.createTreeWalker(svg,NodeFilter.SHOW_ELEMENT);let el;
  while((el=walker.nextNode())){
    const tag=el.tagName.toLowerCase();
    if(['path','rect','circle','ellipse','polygon','polyline','line'].includes(tag)){
      if(hidden(el))continue;const bb=el.getBBox();if(bb.width===0&&bb.height===0)continue;
      const cs=getComputedStyle(el);const m=toRoot(el);
      let d;
      if(tag==='rect'){const x=+el.getAttribute('x')||0,y=+el.getAttribute('y')||0,w=+el.getAttribute('width'),h=+el.getAttribute('height');const c=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]].map(([a,b])=>pt(m,a,b));d='M'+c.map(p=>f2(p.x)+' '+f2(p.y)).join(' L')+' Z';}
      else if(tag==='polygon'||tag==='polyline'){const ps=Array.from(el.points).map(p=>pt(m,p.x,p.y));d='M'+ps.map(p=>f2(p.x)+' '+f2(p.y)).join(' L')+(tag==='polygon'?' Z':'');}
      else{const L=el.getTotalLength();const n=Math.max(8,Math.min(400,Math.ceil(L/3)));const ps=[];for(let i=0;i<=n;i++){const q=el.getPointAtLength(L*i/n);ps.push(pt(m,q.x,q.y));}
        const closed=tag==='circle'||tag==='ellipse'||/z\s*$/i.test(el.getAttribute('d')||'');d='M'+ps.map(p=>f2(p.x)+' '+f2(p.y)).join(' L')+(closed?' Z':'');}
      d.replace(/-?[\d.]+ -?[\d.]+/g,s=>{const [x,y]=s.split(' ').map(Number);grow(x,y);return s});
      out.push(`<path d="${d}" ${paint(cs)}/>`);
      if(cs.markerEnd&&cs.markerEnd!=='none'&&tag==='path'){const L=el.getTotalLength();const a=pt(m,...Object.values((({x,y})=>({x,y}))(el.getPointAtLength(Math.max(0,L-6))))),b=pt(m,...Object.values((({x,y})=>({x,y}))(el.getPointAtLength(L))));
        const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,ux=dx/len,uy=dy/len,sz=9,hw=4.5;const tip=b,base={x:b.x-ux*sz,y:b.y-uy*sz};
        const s=hex(cs.stroke)||{hex:'#333333'};out.push(`<path d="M${f2(tip.x)} ${f2(tip.y)} L${f2(base.x-uy*hw)} ${f2(base.y+ux*hw)} L${f2(base.x+uy*hw)} ${f2(base.y-ux*hw)} Z" fill="${s.hex}" stroke="none"/>`);}
    } else if(tag==='text'){
      if(hidden(el))continue;const rows=Array.from(el.children).filter(c=>c.tagName.toLowerCase()==='tspan'&&c.textContent.trim());const lines=rows.length?rows:[el];
      const cs=getComputedStyle(el);const m=toRoot(el);const size=parseFloat(cs.fontSize);const col=(hex(cs.fill)||{hex:'#000000'}).hex;
      for(const r of lines){const t=r.textContent.replace(/\s+/g,' ').trim();if(!t)continue;const bb=r.getBBox();const c=pt(m,bb.x+bb.width/2,bb.y+bb.height*0.78);grow(c.x-bb.width/2,c.y-size);grow(c.x+bb.width/2,c.y+size*0.3);
        out.push(`<text x="${f2(c.x)}" y="${f2(c.y)}" text-anchor="middle" font-family="${FONT}" font-size="${f2(size)}"${+cs.fontWeight>=600?' font-weight="bold"':''} fill="${col}">${esc(t)}</text>`);}
    }
  }
  const pad=12;const x0=Math.floor(minX-pad),y0=Math.floor(minY-pad),w=Math.ceil(maxX-minX+2*pad),h=Math.ceil(maxY-minY+2*pad);
  return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="${w}" height="${h}" viewBox="${x0} ${y0} ${w} ${h}">\n<title>${esc(window.TITLE||'diagram')}</title>\n<rect x="${x0}" y="${y0}" width="${w}" height="${h}" fill="#ffffff" stroke="none"/>\n`+out.join('\n')+'\n</svg>\n';
};
window.go=async function(src){const r=await mermaid.render('flow',src);document.body.innerHTML=r.svg;window.fo=document.querySelectorAll('foreignObject').length;return window.flatten();};
