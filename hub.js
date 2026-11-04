/* Strategy release view inside the existing RYDER Hub. */
(()=>{
const e=v=>String(v??'Unknown').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const note=s=>'<p class="sub">'+e(s)+'</p>';
const row=(a,b)=>'<div class="reason"><span>'+e(a)+'</span><b>'+e(b)+'</b></div>';
const cash=n=>'$'+Number(n).toFixed(2);
function add(host,id,html,first=false){if(!host)return;document.getElementById(id)?.remove();const box=document.createElement('section');box.id=id;box.innerHTML=html;first?host.prepend(box):host.append(box);}
function replay(t){
 const pts=[[t.opened,t.entry],...t.fills.map(f=>[f[0],f[1]])];
 const vals=pts.map(p=>p[1]).concat(t.peak==null?[]:[t.peak]);
 const lo=Math.min(...vals),hi=Math.max(...vals),end=pts[pts.length-1][0];
 const y=v=>70-58*(v-lo)/(hi-lo||1),x=v=>8+304*(v-t.opened)/(end-t.opened||1);
 return '<details><summary>'+e(t.symbol)+' · '+e(t.reason)+'</summary><svg aria-label="Recorded entry and exit fills with peak price level" role="img" width="100%" height="92" viewBox="0 0 320 85" preserveAspectRatio="none">'+
 (t.peak==null?'':'<path stroke="#f88196" stroke-dasharray="4 4" d="M8 '+y(t.peak)+' H312"/>')+
 '<polyline fill="none" stroke="#62edab" stroke-width="2" points="'+pts.map(p=>x(p[0])+','+y(p[1])).join(' ')+'"/>'+
 pts.map(p=>'<circle r="3" fill="#e4fff0" cx="'+x(p[0])+'" cy="'+y(p[1])+'"/>').join('')+'</svg>'+
 note('Dots are recorded fills. Dashed line is the recorded peak; its time is unknown.')+
 row('Entry',t.entry)+row('Peak',t.peak)+t.fills.map(f=>row(f[2],f[1])).join('')+'</details>';
}
window.ryderHubDraw=(page,section)=>{
 const h=data.strategy_hub,ok=h?.release==='strategy-desk-1';
 const rows=data.mission_control?.cards?.find(c=>c.id===24)?.rows||[];
 const state=String(rows.find(r=>r[0]==='Updater')?.[1]||'');
 const sha=rows.find(r=>r[0]==='Installed code')?.[1];
 const age=(Date.now()-Date.parse(data.updated_at))/1000;
 const status=/fail/i.test(state)?'Update failed':/held|deferred/i.test(state)?'Update held':ok&&h.runner_release==='strategy-desk-1'?'Installed':!rows.length?'Awaiting Mac report':'Pending Mac confirmation';
 const badge='<b class="hub-badge">'+e(status)+'</b>';
 if(page==='overview')add(document.getElementById('balance'),'hub-guide',badge+
 '<details'+(location.hash==='#layout'?' open':'')+'><summary>Hub layout</summary>'+note('Overview · shared paper equity, positions and latest decision')+
 '<div class="hub-links"><a href="#radar">Radar · signals & second looks</a><a href="#trades">Trades · position replays</a><a href="#research">Research · strategy results</a><a href="#more">More · logs & system health</a></div>'+
 note('Strategy Desk · Last published '+(data.asof||'unknown')+' · Mac revision '+(sha||'unknown')+(age>300?' · stale snapshot':''))+'</details>');
 if(page==='radar')add(document.querySelector('#mission-desk'),'hub-watch','<details open><summary>Entry watchlist</summary>'+
 ((data.desk_five?.watch||[]).map(w=>row(w.sym,w.strategy||'Entry confirmation')).join('')||note('No candidates awaiting entry confirmation.'))+
 ((h?.watch||[]).map(w=>row(w.symbol,w.reason+' · retry '+new Date(w.due*1000).toLocaleTimeString())).join('')||note(ok?'No second looks queued.':'Waiting for the strategy release report.'))+'</details>',true);
 if(page==='research'&&section==='strategies'){
 const el=document.getElementById('sleek-research-body');if(!el)return;
 el.innerHTML='<h3>Strategy scoreboard</h3>'+note('Main v3 paper desk · completed openings in the last 7 days · partial sales grouped with their final exit. Drawdown uses realized results.')+
 (ok?Object.entries(h.score).map(([k,v])=>row(k,v.closed+' closed · '+cash(v.net)+' net · '+cash(v.dd)+' drawdown')).join(''):note('Waiting for the Mac to publish strategy results.'))+
 '<h3>Near-entry blockers</h3>'+(h?.blocked?.map(b=>row(b[0]+' · '+b[1],b[2])).join('')||note('No recorded blockers in this feed.'));}
 if(page==='trades')add(document.getElementById('trades'),'hub-replay','<h3>Position replay</h3>'+(h?.replays?.map(replay).join('')||note('Waiting for completed paper openings in the seven-day window.')));
};
})();
