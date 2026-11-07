/* Evidence expansions in existing cards, never another Overview panel. */
(()=>{
const esc=v=>String(v??'Not recorded').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const p=s=>'<p class="sub">'+esc(s)+'</p>',box=(title,body)=>'<details class="di-detail"><summary>'+esc(title)+'</summary>'+body+'</details>';
const rows=(a,fn)=>a?.length?a.map(fn).join(''):p('No qualifying evidence recorded yet.');
function countdown(){document.querySelectorAll('[data-di-ready]').forEach(n=>{const at=Number(n.dataset.diReady),fresh=Date.now()/1000-Number(n.dataset.diBeat);n.textContent=!n.dataset.diReady?'Recheck time not recorded':fresh<0||fresh>120?'Stale — countdown paused':Date.now()/1000>=at?'Recheck due · not buy approval':Math.ceil(at-Date.now()/1000)+'s until recheck';});}
window.ryderInsightsDraw=(page,section,more)=>{
 document.querySelectorAll('[data-di-owned]').forEach(n=>n.remove());const d=data.desk_insights;
 const add=(host,html)=>{if(!host)return;const node=document.createElement('div');node.dataset.diOwned='1';node.innerHTML=html;host.append(node);};
 if(!d||d.error){if(page==='more'&&more==='system')add(document.getElementById('sleek-more'),p('Desk insights awaiting Mac report'+(d?.error?' · '+d.error:'')));return;}
 const stale=Date.now()/1000-d.at>300||Date.now()/1000<d.at;
 const health=p((stale?'STALE SNAPSHOT · ':'')+d.health.state)+p('Next check: '+d.health.next)+rows(d.health.sources,r=>p(r.host+' · '+r.status+' · '+r.errors+' recorded errors'))+rows(d.health.recent_errors,r=>p(r.where+' · '+new Date(r.at*1000).toLocaleString()));
 const recap=box('Morning recap · since 6 PM Pacific',p(d.recap.completed+' completed · '+d.recap.wins+' wins / '+d.recap.losses+' losses · $'+d.recap.net.toFixed(2)+' net')+p('Worked: '+d.recap.worked)+p('Needs review: '+d.recap.failed)+p('Next paper experiment: '+d.recap.experiment));
 const pending=rows(d.pending,r=>box(r.symbol+' · '+r.strategy,p(r.status)+'<p class="sub" data-di-ready="'+esc(r.ready_at??'')+'" data-di-beat="'+esc(d.health.heartbeat_at??0)+'">Awaiting timestamp</p>'+p(r.quote_fresh?'Fresh quote recorded':'Fresh quote not confirmed')+p(r.next)));
 if(page==='overview'){
  const roster=document.querySelector('.nd-agents');
  if(roster)d.activity.forEach(a=>{const row=[...roster.querySelectorAll('.nd-agent')].find(r=>r.querySelector('b')?.textContent===a.agent);add(row,box('Recorded work',p((a.symbol||'No token recorded')+' · '+a.status)+p(a.evidence)+p('Review next: '+a.next)));});
  const intel=document.querySelector('.nd-bottom section:last-child');add(intel,box('Feed & recovery',health)+recap);
  add(document.querySelector('.nd-positions'),box('Near-entry watch · '+d.pending.length,pending));
 }
 if(page==='radar')add(document.getElementById('hub-watch'),box('Entry recheck countdowns',pending));
 if(page==='research'){
  let html='';
  if(section==='missed')html=box('Skipped moves · after-cost evidence',rows(d.missed,r=>p(r.symbol+' · '+r.reason+' · $'+r.net.toFixed(2)+' modeled · '+r.classification))+p('Existing same-pool model includes pool impact and fees. Selected observations do not prove the token was safely tradable.'));
  if(section==='exits')html=box('Exit capture & giveback',rows(d.exits,r=>p(r.symbol+' · net $'+r.net.toFixed(2)+' · captured '+(r.capture_pct??'unknown')+'% of recorded peak gain · giveback '+(r.giveback_pp??'unknown')+' pp'))+p('Weighted by partial-fill cost. Recorded peaks may not have been executable; missing peaks remain unknown.'));
  if(section==='strategies')html=box('Strategy × token-market condition',rows(d.conditions,r=>p(r.strategy+' / '+r.condition+' · '+r.n+' completed · $'+r.net.toFixed(2)+' net · '+r.status)));
  if(section==='diagnostics')html=box('Agent score vs outcomes',rows(d.confidence,r=>p(r.agent+' · '+r.band+' score · n='+r.n+' · mean score '+r.mean_score+' · wins '+(r.win_rate*100).toFixed(1)+'% · '+r.status))+p('Agent scores are not calibrated probabilities. Compare bands within an agent; correlations are not causal.'))+box('Feed recovery',health);
  if(section==='session')html=recap;
  add(document.getElementById('sleek-research-body'),html+box('Insight evidence scope',p(d.scope)));
 }
 if(page==='more'&&more==='system')add(document.getElementById('sleek-more'),box('Feed recovery & runner state',health));
 countdown();
};
setInterval(countdown,1000);
})();
