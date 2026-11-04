/* Twenty-five live, publisher-backed views. No example fixtures, wallet actions or rule changes. */
(()=>{
const esc=window.ryderMissionEscape||((v)=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));
const groups={radar:[1,2,3,4,5,6,7,8],research:[10,11,12,13,14,15,16],journal:[9,17,18,19,20,21,22,23],system:[24,25]};
let view='radar',query='',src='',minL='',minS='',maxA='',recent=false,logs='',snapshot=null,pins=[];
try{pins=JSON.parse(localStorage.getItem('ryder-observation-pins')||'[]');if(!Array.isArray(pins))pins=[]}catch{}
const colors=['#ff5365','#ce8bd1','#63d7af','#82b2ff','#ffca82'];
const fmt=v=>v==null?'Not recorded':typeof v==='number'?Number(v.toFixed(4)).toLocaleString():String(v);
const time=t=>t?new Date(t*1000).toLocaleString('en-US',{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'Not recorded';
function table(headers,rows){return `<div class="mc-scroll"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map((v,i)=>`<td>${esc(/^(Time|Training time|Saved time)$/.test(headers[i])&&typeof v==='number'?time(v):fmt(v))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function plot(series,unit=''){
 const all=series.flatMap(s=>(s.points||[]).filter(p=>Number.isFinite(p.t)&&Number.isFinite(p.v)));if(all.length<2)return '<p class="sub">Collecting chart observations.</p>';
 const low=Math.min(...all.map(p=>p.v)),high=Math.max(...all.map(p=>p.v)),pad=Math.max(.01,(high-low)*.1),lo=low-pad,hi=high+pad,t0=Math.min(...all.map(p=>p.t)),t1=Math.max(...all.map(p=>p.t));
 const x=t=>40+(t-t0)/Math.max(1,t1-t0)*410,y=v=>145-(v-lo)/(hi-lo)*120;
 return `<svg class="mc-chart" viewBox="0 0 475 180" role="img" aria-label="Recorded ${esc(unit)} observations over time">${[0,.5,1].map(v=>`<line x1="40" x2="450" y1="${25+v*120}" y2="${25+v*120}" stroke="#ffffff15"/><text x="0" y="${29+v*120}">${esc(fmt(hi-v*(hi-lo)))}</text>`).join('')}${series.map((s,i)=>`<polyline fill="none" stroke="${colors[i%colors.length]}" stroke-width="2.5" points="${s.points.filter(p=>Number.isFinite(p.t)&&Number.isFinite(p.v)).map(p=>`${x(p.t)},${y(p.v)}`).join(' ')}"/>`).join('')}<text x="40" y="170">${esc(time(t0))}</text><text x="450" y="170" text-anchor="end">${esc(time(t1))}</text></svg><div class="mc-legend">${series.map((s,i)=>`<span><i style="background:${colors[i%colors.length]}"></i>${esc(s.name)}</span>`).join('')} · ${esc(unit)}</div>`;
}
function bars(rows,index){const valid=rows.filter(r=>typeof r[index]==='number'&&Number.isFinite(r[index]));if(!valid.length)return'';const max=Math.max(.0001,...valid.map(r=>Math.abs(r[index])));return valid.slice(0,20).map((r,i)=>`<div class="mc-bar"><span>${esc(r[0])}</span><div><i style="width:${Math.abs(r[index])/max*100}%;background:${r[index]<0?'#ff809b':colors[i%5]}"></i></div><b>${esc(fmt(r[index]))}</b></div>`).join('')}
function visibleTokens(){return(snapshot.tokens||[]).filter(t=>((t.symbol+' '+t.mint).toLowerCase().includes(query.toLowerCase()))&&(!src||t.source===src)&&(!minL||(t.liquidity!=null&&t.liquidity>=Number(minL)))&&(!minS||(t.score!=null&&t.score>=Number(minS)))&&(!maxA||(t.age_s!=null&&t.age_s<=Number(maxA)*60))&&(!recent||t.observation_age_s<=120))}
function radar(){return `<div class="mc-filters"><input id="mc-search" placeholder="Token name or address" aria-label="Search radar" value="${esc(query)}"><select id="mc-source" aria-label="Radar source"><option value="">All sources</option>${[...new Set((snapshot.tokens||[]).map(t=>t.source))].map(s=>`<option ${s===src?'selected':''}>${esc(s)}</option>`).join('')}</select><input id="mc-liq" type="number" min="0" placeholder="Min liquidity USD" value="${esc(minL)}" aria-label="Minimum liquidity"><input id="mc-score" type="number" min="0" max="1" step=".01" placeholder="Min score" value="${esc(minS)}" aria-label="Minimum score"><input id="mc-age" type="number" min="0" placeholder="Max age minutes" value="${esc(maxA)}" aria-label="Maximum token age"><label><input type="checkbox" id="mc-recent" ${recent?'checked':''}> Observed ≤2m ago</label></div><div id="mc-radar-results"></div>`}
function radarResults(){const el=document.getElementById('mc-radar-results');if(!el)return;const ts=visibleTokens();el.innerHTML=ts.length?`<div class="mc-scroll"><table><thead><tr><th>Token</th><th>Source</th><th>Liquidity</th><th>Score</th><th>Observation</th><th>Pin</th></tr></thead><tbody>${ts.map(t=>`<tr><td><button data-token="${esc(t.mint)}">${esc(t.symbol)}</button></td><td>${esc(t.source)}<small>${esc(t.dex)}</small></td><td>${t.liquidity==null?'Unknown':'$'+esc(fmt(t.liquidity))}</td><td>${esc(fmt(t.score))}</td><td>${esc(t.freshness)}<small>${esc(Math.round(t.observation_age_s))}s ago</small></td><td><button data-pin="${esc(t.mint)}" aria-label="Pin ${esc(t.symbol)}">${pins.includes(t.mint)?'★':'☆'}</button></td></tr>`).join('')}</tbody></table></div>`:'<p class="sub">No observed tokens match these filters.</p>';bindActions(el)}
function pinned(){return pins.length?pins.map(m=>{const t=(snapshot.tokens||[]).find(t=>t.mint===m);return `<div class="mc-pin"><button data-token="${esc(m)}">${esc(t?.symbol||m.slice(0,10))}</button><span class="sub">${t?esc(t.freshness):'Outside current observation window'}</span><button data-pin="${esc(m)}" aria-label="Unpin token">★</button></div>`}).join(''):'<p class="sub">Use ☆ beside a radar token to pin it here.</p>'}
function detail(m){const t=(snapshot.tokens||[]).find(t=>t.mint===m);let dlg=document.getElementById('mc-token-dialog');if(!dlg){dlg=document.createElement('dialog');dlg.id='mc-token-dialog';document.body.appendChild(dlg)}dlg.innerHTML=`<h2>${esc(t?.symbol||m.slice(0,10))}</h2><p class="mc-address">${esc(m)}</p>${t?table(['Field','Observation'],[['Source',t.source],['DEX',t.dex],['Liquidity USD',t.liquidity],['Price USD',t.price],['Recorded score',t.score],['Pool age seconds',t.age_s],['Last observed',time(t.last_ts)]])+`<h3>Decision timeline</h3>${t.events.length?table(['Time','Event','Reason'],t.events.map(e=>[e.t,e.kind,e.reason||'Not recorded'])):'<p class="sub">No matching events in the bounded logger window.</p>'}`:'<p class="sub">This pinned token is outside the current snapshot. Pinning does not force monitoring.</p>'}<button data-five-token="${esc(m)}">Open full timeline</button><button id="mc-close">Close</button>`;dlg.querySelector('#mc-close').onclick=()=>dlg.close();dlg.showModal()}
function guide(){let dlg=document.getElementById('mc-recovery');if(!dlg){dlg=document.createElement('dialog');dlg.id='mc-recovery';document.body.appendChild(dlg)}dlg.innerHTML='<h2>Backup recovery guide</h2><ol><li>Stop the background service and confirm runner and publisher have exited.</li><li>Preserve a fresh copy of current state and the matching code version.</li><li>Check the chosen backup with SQLite integrity_check.</li><li>Restore the database only with compatible code, keeping the current file for recovery.</li><li>Run accounting tests, restart once, then verify balances and publisher.</li></ol><p class="sub">This guide performs no restore or deletion. Ask for a recovery walkthrough before changing memory.</p><button id="mc-guide-close">Close</button>';dlg.querySelector('button').onclick=()=>dlg.close();dlg.showModal()}
function body(c){
 if(c.id===1)return radar();
 if(c.id===2)return '<button data-open-radar>Open a token from radar ↗</button>';
 if(c.id===7)return `<div id="mc-pins">${pinned()}</div>`;
 if(c.id===9)return `<input id="mc-log-search" aria-label="Search decision timeline" placeholder="Search token, event or reason" value="${esc(logs)}"><div id="mc-log-results">${table(c.headers,c.rows.filter(r=>r.join(' ').toLowerCase().includes(logs.toLowerCase())))}</div>`;
 let h='';if(c.id===10&&c.votes?.length)h+=bars(c.votes,1)+table(['Agent','Vote','Recorded explanation'],c.votes);if(c.series?.length)h+=plot(c.series,c.unit||'');
 if([4,13,14,15,16,18,19,20].includes(c.id))h+=bars(c.rows,[13,14,15,20].includes(c.id)?3:c.id===4?2:c.id===19?1:1);
 if(c.id===11&&c.rows.length)h+=`<div class="mc-legend">Predicted versus observed winning openings (%)</div>`+c.rows.map(r=>`<div class="mc-cal"><b>${esc(r[0])} · n=${esc(r[1])}</b><div>Predicted ${esc(r[2])}% <meter min="0" max="100" value="${r[2]}"></meter></div><div>Observed ${esc(r[3])}% <meter min="0" max="100" value="${r[3]}"></meter></div></div>`).join('');
 if(c.headers?.length)h+=c.rows.length?`<details ${[5,6,8,10,21,23,24,25].includes(c.id)?'open':''}><summary>Recorded values · ${c.rows.length} rows</summary>${table(c.headers,c.rows)}</details>`:'<p class="sub">Not recorded yet for this window.</p>';
 if(c.id===25)h+='<button id="mc-guide">Open recovery guide</button>';
 return h;
}
function renderMission(){
 const d=data,m=d?.mission_control;let host=document.getElementById('mission-desk');if(!host){host=document.createElement('section');host.id='mission-desk';const anchor=document.querySelector('#dashboard .dexes');if(anchor)anchor.after(host);else document.getElementById('dashboard')?.appendChild(host)}
 if(!host)return;if(!m?.cards?.length){host.innerHTML='<section class="card"><h2>RYDER research desk</h2><p class="sub">Awaiting the upgraded publisher snapshot. '+(m?.error?'Collection error: '+esc(m.error):'')+'</p></section>';return}
 snapshot=m;
 host.innerHTML=`<div class="mc-heading"><h2>Research desk <span class="sub">/ 25 views</span></h2><span class="sub">${esc(time(m.generated_at))} PT</span></div><div class="mc-tabs" role="navigation" aria-label="Research desk views">${Object.keys(groups).map(k=>`<button data-mc-view="${k}" class="${k===view?'active':''}">${k[0].toUpperCase()+k.slice(1)}</button>`).join('')}</div><div class="mc-grid">${m.cards.filter(c=>groups[view].includes(c.id)).map(c=>`<article class="card mc-card" id="mc-${c.id}"><div class="row"><span class="mc-number">${String(c.id).padStart(2,'0')}</span><h2>${esc(c.title)}</h2></div>${body(c)}<p class="sub mc-note">${esc(c.note)}</p></article>`).join('')}</div><p class="sub mc-scope">${esc(m.scope)}</p>`;
 host.querySelectorAll('[data-mc-view]').forEach(b=>b.onclick=()=>{view=b.dataset.mcView;renderMission();host.scrollIntoView({behavior:'smooth',block:'start'})});
 const fields={'mc-search':['query',v=>query=v],'mc-source':['src',v=>src=v],'mc-liq':['minL',v=>minL=v],'mc-score':['minS',v=>minS=v],'mc-age':['maxA',v=>maxA=v]};
 for(const [id,[_,set]] of Object.entries(fields)){const el=document.getElementById(id);if(el)el.oninput=()=>{set(el.value);radarResults()}}
 const check=document.getElementById('mc-recent');if(check)check.onchange=()=>{recent=check.checked;radarResults()};
 const log=document.getElementById('mc-log-search');if(log)log.oninput=()=>{logs=log.value;const c=m.cards.find(c=>c.id===9);document.getElementById('mc-log-results').innerHTML=table(c.headers,c.rows.filter(r=>r.join(' ').toLowerCase().includes(logs.toLowerCase())))};
 document.getElementById('mc-guide')?.addEventListener('click',guide);bindActions(host);radarResults();
}
function bindActions(host){host.querySelectorAll('[data-token]').forEach(b=>b.onclick=()=>detail(b.dataset.token));host.querySelectorAll('[data-pin]').forEach(b=>b.onclick=()=>{const mint=b.dataset.pin;pins=pins.includes(mint)?pins.filter(p=>p!==mint):[...pins,mint];try{localStorage.setItem('ryder-observation-pins',JSON.stringify(pins))}catch{}radarResults();const p=document.getElementById('mc-pins');if(p){p.innerHTML=pinned();bindActions(p)}});host.querySelectorAll('[data-open-radar]').forEach(b=>b.onclick=()=>{document.getElementById('mc-1')?.scrollIntoView({behavior:'smooth'})})}
const before=render;render=function(){before.apply(this,arguments);try{renderMission()}catch(e){console.warn('Research desk render failed',e)}};
if(typeof data!=='undefined'&&data)renderMission();
})();

/* Live market-coverage and research extension. No sample fixtures or rule controls. */
function renderOpportunityLab(d){
 const value=d.opportunity_lab;if(!value)return;
 let el=document.getElementById('opportunity-lab');if(!el){el=document.createElement('section');el.id='opportunity-lab';el.className='card';document.getElementById('mission-desk')?.appendChild(el)}
 const e=x=>String(x??'Not recorded').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 if(value.error){el.innerHTML='<h2>Market coverage & capacity lab</h2><p class="sub">Collection unavailable: '+e(value.error)+'</p>';return}
 const s=value.scheduler||{},b=value.breadth||{},c=value.capacity||{},v=value.evaluation||{};
 el.innerHTML='<h2>Market coverage & capacity lab</h2><p class="sub">Separate research. Main trade limits are unchanged.</p>'+
 '<h3>Scanner health</h3><div class="reason"><span>Pending / maximum</span><b>'+e(s.pending)+' / '+e(s.max_pending)+'</b></div>'+
 '<div class="reason"><span>Dispatched candidates</span><b>'+e(s.dispatched)+'</b></div>'+
 '<div class="reason"><span>Expired or rejected backlog</span><b>'+e(s.expired_or_rejected)+'</b></div>'+
 '<div class="reason"><span>Overflow candidates</span><b>'+e(s.overflow??0)+'</b></div>'+
 '<div class="reason"><span>Deeper-feed candidates / errors</span><b>'+e(b.candidates??0)+' / '+e(b.errors??0)+'</b></div>'+
 '<h3>4-versus-8 entries/hour study</h3><p class="sub">'+e(c.status)+'</p>'+
 (c.books||[]).map(x=>'<div class="details"><b>'+e(x.book)+' · '+e(x.max_entries_per_hour)+'/hour</b><br>Simulated equity '+(x.equity==null?'Unknown (stale marks)':'$'+e(x.equity))+' · realized $'+e(x.realized)+'<br>'+e(x.open)+' open · '+e(x.closed)+' closed · '+e(x.stale_marks)+' stale marks</div>').join('')+
 '<p class="sub">'+e(c.note||'Collecting fully qualified signals. No shadow fills are inserted into the shared ledger.')+'</p>'+
 '<h3>Purged walk-forward evaluation</h3><p class="sub">'+e(v.status)+' · '+e(v.sample_n)+' matched completed openings</p>'+
 (v.folds||[]).map(f=>'<div class="details">Train n='+e(f.train_n)+' · unseen test threshold '+e(f.threshold)+'<br>Baseline n='+e(f.baseline.n)+' · mean net '+e(f.baseline.mean_net_pct)+'%<br>Challenger n='+e(f.challenger.n)+' · mean net '+e(f.challenger.mean_net_pct)+'%</div>').join('')+
 '<p class="sub">'+e(v.note)+'</p><p class="sub">Automatic promotion: disabled. More paper entries do not establish better returns.</p>';
}
{const beforeOpportunityLab=render;render=function(){beforeOpportunityLab.apply(this,arguments);try{renderOpportunityLab(data)}catch(e){console.warn('Capacity lab render failed',e)}};if(typeof data!=='undefined'&&data)renderOpportunityLab(data)}
