/* Reference-layout Night Desk. Presentation only; all numbers come from the Mac snapshot. */
(()=>{
const h=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const usd=v=>Number.isFinite(v)?'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
const count=v=>Number.isFinite(v)?v.toLocaleString('en-US'):'—';
const pct=v=>Number.isFinite(v)?v.toFixed(1)+'%':'—';
const money=v=>Number.isFinite(v)?(v>=0?'+':'−')+usd(Math.abs(v)):'—';
const time=v=>{try{return new Date(v).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}catch{return '—'}};
function curve(d){
 const p=(Array.isArray(d.curve)?d.curve:[]).filter(x=>Number.isFinite(x.v));
 if(p.length<2)return '<div class="nd-empty">Waiting for at least two recorded equity points</div>';
 const values=p.map(x=>x.v),low=Math.min(...values),high=Math.max(...values),range=Math.max(high-low,1);
 const coords=p.map((x,i)=>[48+i*850/(p.length-1),216-(x.v-low)/range*175]);
 const path=coords.map(([x,y],i)=>(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)).join(' ');
 const grid=[0,1,2,3].map(i=>{const y=40+i*58;return '<line x1="48" y1="'+y+'" x2="898" y2="'+y+'" stroke="#722338" stroke-dasharray="4 8" opacity=".55"/><text x="8" y="'+(y+4)+'" fill="#a9949e" font-size="13">'+h(usd(high-i*range/3))+'</text>'}).join('');
 return '<svg viewBox="0 0 920 250" preserveAspectRatio="none" role="img" aria-label="Recorded paper equity curve"><defs><linearGradient id="ndFill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#ff254e" stop-opacity=".4"/><stop offset="1" stop-color="#ff254e" stop-opacity="0"/></linearGradient><filter id="ndGlow"><feGaussianBlur stdDeviation="4"/></filter></defs>'+grid+'<path d="'+path+' L898 236 L48 236 Z" fill="url(#ndFill)"/><path d="'+path+'" fill="none" stroke="#f82450" stroke-width="7" opacity=".45" filter="url(#ndGlow)"/><path d="'+path+'" fill="none" stroke="#ff4264" stroke-width="3"/><circle cx="'+coords.at(-1)[0]+'" cy="'+coords.at(-1)[1]+'" r="5" fill="#fff"/></svg><div class="nd-chart-times"><span>'+h(p[0].t)+'</span><span>RECORDED PAPER EQUITY</span><span>'+h(p.at(-1).t)+'</span></div>';
}
function build(){
 const dash=document.getElementById('dashboard');
 if(!dash||typeof data==='undefined'||!data)return;
 const old=document.getElementById('nd-reference');old?.remove();
 const d=data,delta=d.equity-d.start,win=d.wins+d.losses;
 const age=Date.now()-Date.parse(d.updated_at||'');
 const fresh=Number.isFinite(age)&&age>=0&&age<300000;
 const names=['Scout','Filter','Analyst','Executor','Risk','Logger','Hunter','Strategist','Sentinel'];
 const base=Array.isArray(d.agents)?d.agents:[];
 const advisory=Array.isArray(d.advisory_agents)&&d.advisory_source==='mac_publisher_snapshot'?d.advisory_agents:[];
 const agents=[...base,...advisory.filter(a=>!base.some(b=>b.name===a.name))];
 const stats=[['PAPER EQUITY',usd(d.equity),'◈'],['REALIZED PNL',money(d.realized),'↗'],['WIN RATE',win?pct(100*d.wins/win):'—','◎'],['TOTAL TRADES',count(d.trades),'⇄'],['SCANS (24H)',Number.isFinite(d.scans_24h)&&d.scans_24h_source==='recorded_scan_events'?count(d.scans_24h):'—','◎']];
 const el=document.createElement('div');el.id='nd-reference';el.dataset.deskPage='overview';
 const events=Array.isArray(d.tail)?d.tail.slice(-5).reverse():[];
 const opens=Array.isArray(d.opens)?d.opens:[];
 const recent=events.map(x=>'<div class="nd-event"><b>'+h(x.ag)+'</b><span>'+h(x.text)+'</span></div>').join('')||'<p class="nd-empty">No recent activity recorded</p>';
 const intel=[['MARKET SOURCE',d.market_mood?.mood||'Not reported'],['TOKENS SCANNED',count(d.seen)],['FILTER PASSED',count(d.passed)],['PAPER POSITIONS',count(opens.length)]].map(([a,b])=>'<div class="nd-info"><span>'+h(a)+'</span><b>'+h(b)+'</b></div>').join('');
 el.innerHTML='<div class="nd-kpis">'+stats.map(([k,v,icon])=>'<section class="nd-panel nd-kpi"><span class="nd-kpi-icon">'+icon+'</span><div><small>'+k+'</small><strong>'+v+'</strong></div></section>').join('')+'</div>'+
 '<div class="nd-workspace"><section class="nd-panel nd-curve"><div class="nd-panel-heading"><div><small>LIVE PERFORMANCE · PAPER ONLY</small><h2>EQUITY CURVE</h2></div><div class="nd-equity-value">'+usd(d.equity)+'<small>'+money(delta)+' since start</small></div></div><div class="nd-chart">'+curve(d)+'</div><div class="nd-chart-footer"><span>● EQUITY</span><span>Volume bars unavailable unless recorded</span></div></section>'+
 '<aside class="nd-sidebar"><section class="nd-panel nd-positions"><div class="nd-panel-heading"><h2>OPEN POSITIONS</h2><span class="nd-counter">'+opens.length+' OPEN</span></div>'+(opens.length?opens.slice(0,5).map(p=>'<div class="nd-pos"><b>'+h(p.sym)+'</b><span>'+usd(p.usd)+' allocated</span><strong>'+money(p.pnl)+'</strong></div>').join(''):'<p class="nd-empty">No open paper positions</p>')+'</section>'+
 '<section class="nd-panel nd-agents"><div class="nd-panel-heading"><h2>RYDER’S AGENTS</h2><span class="nd-counter">'+(fresh?'FEED FRESH':'FEED STALE')+'</span></div>'+names.map((name,i)=>{const a=agents.find(x=>x.name===name);return '<div class="nd-agent"><span class="nd-agent-symbol">'+['⌕','◇','◈','ϟ','⬡','≡','◎','✧','⬢'][i]+'</span><b>'+name+'</b><span class="nd-agent-note">'+h(a?.text||'Awaiting Mac report')+'</span><span class="nd-agent-state '+(a&&fresh?'nd-reported':'')+'">'+(a?(fresh?'REPORTED':'STALE'):'WAITING')+'</span></div>'}).join('')+'<p class="nd-footnote">Reported means present in the latest Mac snapshot, not independently verified as executing.</p></section></aside></div>'+
 '<div class="nd-bottom"><section class="nd-panel"><h2>MARKET INTEL</h2>'+intel+'</section><section class="nd-panel"><h2>RECENT ACTIVITY</h2>'+recent+'</section><section class="nd-panel"><h2>RYDER INTEL FEED</h2><div class="nd-info"><span>PUBLISHER</span><b>'+h(d.advisory_source||'Snapshot')+'</b></div><div class="nd-info"><span>LAST UPDATE</span><b>'+h(d.updated_at?time(d.updated_at):d.asof)+'</b></div><div class="nd-info"><span>SNAPSHOT</span><b>'+(fresh?'Fresh':'Stale / unverified')+'</b></div><p class="nd-footnote">No inferred market events or agent decisions.</p></section></div>';
 dash.prepend(el);
 const scanCard=el.querySelector('.nd-kpi:last-child div');if(scanCard){const note=document.createElement('small');note.style.cssText='display:block;color:#d2aab7;font-size:10px;margin-top:6px';note.textContent=Number.isFinite(d.scans)?'TOTAL: '+count(d.scans)+' · updates with Mac snapshot':'Waiting for Mac scan snapshot';scanCard.appendChild(note)}
 const brand=document.querySelector('main>header .brand>div');
 if(brand)brand.innerHTML='<strong>RYDER AI</strong><span>NIGHT DESK</span>';\n document.querySelector('main>header .brand .rd-mascot')?.remove();\n document.getElementById('rd-bigstar')?.remove();
 const pill=document.querySelector('main>.pills .paper');if(pill)pill.textContent='PAPER MODE';
 const label=document.getElementById('sourceLabel');if(label)label.textContent=fresh?'● Mac Publisher LIVE':'● Publisher STALE';
 const heading=document.querySelector('#nd-reference .nd-curve .nd-panel-heading h2');
 if(heading)heading.insertAdjacentHTML('afterbegin','<span class="nd-red-bar"></span>');
 const info=document.querySelector('#nd-reference .nd-chart-footer');
 if(info)info.insertAdjacentHTML('beforebegin','<div class="nd-time-filters"><button class="selected" type="button">24H</button><button type="button">7D</button><button type="button">1M</button><button type="button">ALL</button></div>');
 const filters=document.querySelectorAll('#nd-reference .nd-time-filters button');
 filters.forEach((button,i)=>button.addEventListener('click',()=>{
  filters.forEach(b=>b.classList.remove('selected'));button.classList.add('selected');
  const available=Array.isArray(d.curve)?d.curve:[];
  const range=[1,7,30,Infinity][i]*86400000,now=Date.parse(d.updated_at||'')||Date.now();
  const subset=available.filter(p=>{const t=Date.parse(p.t);return !Number.isFinite(t)||now-t<=range});
  const chartEl=document.querySelector('#nd-reference .nd-chart');
  if(chartEl)chartEl.innerHTML=curve({...d,curve:subset});
 }));
 const svg=document.querySelector('#nd-reference .nd-chart svg');
 if(svg)svg.insertAdjacentHTML('afterbegin','<text x="410" y="196" fill="#d20b32" opacity=".13" font-size="270" font-weight="900" font-style="italic">R</text>');
 const pos=document.querySelector('#nd-reference .nd-positions');
 const kpis=document.querySelector('#nd-reference .nd-kpis');
 if(pos&&kpis)kpis.appendChild(pos);
 const mainNav=document.querySelector('main>nav');
 if(mainNav&&mainNav.children.length===5&&!mainNav.querySelector('[href="#agents"]')){const agentsLink=document.createElement('a');agentsLink.href='#more';agentsLink.innerHTML='⌘<span>Agents</span>';agentsLink.addEventListener('click',ev=>{ev.preventDefault();mainNav.querySelector('[href="#more"]')?.click()});mainNav.insertBefore(agentsLink,mainNav.children[3]);}
 
 document.body.classList.toggle('nd-overview-active',location.hash===''||location.hash==='#overview');
}
window.ryderNightDeskDraw=build;
if(typeof data!=='undefined'&&data)build();
})();
