/* Evidence-only brain details inside existing Research and Agents views. */
(()=>{
const e=v=>String(v??'Unknown').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const p=v=>'<p class="sub">'+e(v)+'</p>',details=(t,b)=>'<details style="border-top:1px solid #78313d;padding:12px 0"><summary>'+e(t)+'</summary>'+b+'</details>';
const rows=(xs,f)=>xs?.length?xs.map(f).join(''):p('Waiting for qualifying recorded evidence.');
window.ryderIntelligenceDraw=(page,section,more)=>{
 document.getElementById('intelligence-detail')?.remove();
 const host=page==='research'?document.getElementById('sleek-research-body'):page==='more'&&more==='agents'?document.getElementById('agents'):null;
 if(!host)return;const a=data.intelligence;let html='';
 if(!a||a.error)html=details('Brain intelligence · awaiting report',p(a?.error?'Collection error: '+a.error:'Waiting for the Mac publisher to install intelligence-1.'));
 else{
 const stale=Date.now()/1000-a.at>300;
 html=p('Brain intelligence · '+(a.runner_release===a.release?'runner confirmed':'awaiting runner')+(stale?' · stale snapshot':'')+' · '+a.mode);
 if(page==='more'||section==='strategies')html+=details('Similar-setup memory · '+a.memory_cases+' recorded cases',rows(a.watch,w=>details(w.symbol+' · '+w.condition,p(w.memory.status+' · '+w.memory.n+' comparable openings')+p('Mean net return: '+(w.memory.mean_net_pct??'unknown')+'%')+rows(w.memory.examples,x=>p(x.symbol+' · '+x.net_pct+'% net')))))+details('Strategy results by market condition',rows(a.regimes,r=>p(r.strategy+' / '+r.regime+' · '+r.n+' completed · '+r.mean_net_pct+'% mean net · '+r.status)));
 if(page==='more'||section==='diagnostics')html+=details('Mistake review · evidence, not proven causes',rows(a.mistakes,r=>details(r.symbol+' · $'+r.net,rows(r.findings,p))))+details('Confidence calibration',rows(a.calibration,r=>p(r.n+' outcomes · predicted '+(r.predicted*100).toFixed(1)+'% / actual '+(r.actual*100).toFixed(1)+'% · Brier error '+r.brier)))+details('Input freshness and buyer evidence',rows(a.watch,w=>details(w.symbol,p(w.quality.confidence)+rows(w.quality.warnings,p)+p(w.quality.buyer_quality)+p('Buy share of transactions: '+(w.quality.buy_share==null?'unknown':(w.quality.buy_share*100).toFixed(1)+'%')))))+details('Agent disagreement outcomes',rows(Object.entries(a.objections),([k,v])=>p(k+' · objected before '+(v.objected_loss||0)+' losses / '+(v.objected_gain||0)+' gains / '+(v.objected_flat||0)+' flat outcomes')));
 if(section==='exits')html+=details('Liquidity resilience',rows(a.liquidity,r=>p(r.symbol+' · modeled proceeds $'+r.expected+' · at half liquidity $'+r.half)));
 if(section==='missed')html+=details('Skipped-token after-cost replay',rows(a.missed,r=>p(r.symbol+' · modeled net $'+r.net))+p('Existing matched same-pool replay, $25 allocation with modeled fees and impact. Not executable profit.'));
 if(section==='race'||section==='strategies')html+=details('Challenger / walk-forward evaluation',p(a.walk_forward.status)+p(a.walk_forward.note)+rows(a.walk_forward.folds,f=>p('Threshold '+f.threshold+' · train '+f.train_n+' · later baseline n='+f.baseline.n+' net $'+f.baseline.realized+' · challenger n='+f.challenger.n+' net $'+f.challenger.realized)));
 html+=details('Research version history',p('Active '+a.version+' · research settings only; no execution parameter changes')+rows(a.versions,v=>p(v.id+' · '+new Date(v.created*1000).toLocaleString()))+rows(a.history,h=>p(h.previous+' → '+h.version+' · '+h.reason)))+details('Scope and limitations',p(a.scope));
 }
 const box=document.createElement('div');box.id='intelligence-detail';box.innerHTML=html;host.append(box);
};
})();
