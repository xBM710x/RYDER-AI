/* RYDER reference Overview. Live snapshot only; never invent metrics or activity. */
(()=>{
const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=x=>Number.isFinite(x)?'$'+x.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
const val=x=>Number.isFinite(x)?x.toLocaleString('en-US'):'—';
const age=d=>{let t=Date.parse(d.updated_at||'');return Number.isFinite(t)?Date.now()-t:Infinity};
const panel=(title,body,cls='')=>'<section class="rv-panel '+cls+'"><h2>'+title+'</h2>'+body+'</section>';
function chart(d){
 let p=(d.curve||[]).filter(x=>Number.isFinite(x.v));
 if(p.length<2)return '<p class="rv-empty">Waiting for recorded equity history</p>';
 let lo=Math.min(...p.map(x=>x.v)),hi=Math.max(...p.map(x=>x.v)),range=Math.max(hi-lo,1);
 let pts=p.map((x,i)=>[i*600/(p.length-1),195-(x.v-lo)/range*175]);
 let line=pts.map((q,i)=>(i?'L':'M')+q.join(',')).join(' ');
 return '<svg viewBox="0 0 600 220" preserveAspectRatio="none" role="img" aria-label="Recorded paper equity chart"><defs><linearGradient id="rvFill" x1="0" x2="0" y1="0" y2="1"><stop stop-color="#f52a4b" stop-opacity=".45"/><stop offset="1" stop-color="#f52a4b" stop-opacity=".02"/></linearGradient></defs>'+[0,1,2,3,4].map(i=>'<line x1="0" x2="600" y1="'+(i*50+5)+'" y2="'+(i*50+5)+'" stroke="#722332" stroke-opacity=".45"/>').join('')+'<path d="'+line+' L600 220 L0 220Z" fill="url(#rvFill)"/><path d="'+line+'" stroke="#ff3556" stroke-width="3" fill="none"/></svg><div class="rv-axis"><span>'+esc(p[0].t)+'</span><span>RECORDED PAPER EQUITY</span><span>'+esc(p.at(-1).t)+'</span></div>';
}
function draw(){
 const d=typeof data==='undefined'?null:data, host=document.getElementById('dashboard');
 if(!d||!host)return;
 const active=!location.hash||location.hash==='#overview'||location.hash==='#balance';
 document.body.classList.toggle('rv-reference-active',active);
 let root=document.getElementById('rv-reference');
 if(!active){if(root)root.hidden=true;return;}
 if(!root){root=document.createElement('div');root.id='rv-reference';root.dataset.deskPage='overview';host.prepend(root);}
 root.hidden=false;
 const fresh=age(d)<300000;
 const opens=Array.isArray(d.opens)?d.opens:[];
 const agents=Array.isArray(d.agents)?d.agents:[];
 const events=Array.isArray(d.tail)?d.tail:[];
 const decisions=Array.isArray(d.dual_intelligence?.decisions)?d.dual_intelligence.decisions:[];
 const fomo=d.fomo_intelligence&&d.fomo_intelligence.source_verified===true?d.fomo_intelligence:null;
 const kpi=(name,value)=>'<div class="rv-kpi"><span>'+name+'</span><strong>'+esc(value)+'</strong></div>';
 const equity=fmt(d.equity),pnl=Number.isFinite(d.realized)?(d.realized>=0?'+':'−')+fmt(Math.abs(d.realized)):'—';
 const total=(Number(d.wins)||0)+(Number(d.losses)||0);
 const status=fresh?'● FEED FRESH':'● SNAPSHOT STALE';
 const fomoRows=fomo?['finds_24h','trending_tokens','tracked_wallet_buys','agent_discoveries'].map((k,i)=>'<div class="rv-line"><span>'+['FOMO Finds (24h)','Trending Tokens','Tracked Wallet Buys','Agent Discoveries'][i]+'</span><b>'+esc(val(fomo[k]))+'</b></div>').join(''):'<p class="rv-empty">FOMO wallet feed not connected. Awaiting verified provider data.</p>';
 const positions=opens.length?opens.slice(0,6).map(p=>'<div class="rv-position"><b>'+esc(p.sym)+'</b><span>'+esc(fmt(p.entry))+'</span><span>'+esc(fmt(p.now))+'</span><b class="'+(p.pnl>=0?'rv-green':'rv-red')+'">'+esc((p.pnl>=0?'+':'')+fmt(p.pnl))+'</b></div>').join(''):'<p class="rv-empty">No open paper positions</p>';
 const roster=agents.length?agents.slice(0,8).map(a=>'<div class="rv-agent"><span class="rv-dot"></span><b>'+esc(a.name)+'</b><span>'+esc(a.text||a.stat||'No recent report')+'</span><small>'+esc(fresh?'REPORTED':'STALE')+'</small></div>').join(''):'<p class="rv-empty">No agent reports in snapshot</p>';
 const activity=events.length?events.slice(-8).reverse().map(e=>'<div class="rv-log"><b>'+esc(e.ag||'BOT')+'</b><span>'+esc(e.text||'Event recorded')+'</span></div>').join(''):'<p class="rv-empty">No recorded agent events</p>';
 const decisionRows=decisions.length?decisions.slice(-7).reverse().map(e=>'<div class="rv-decision"><span>'+esc(e.mint?.slice(0,12)||'—')+'</span><b>'+esc(e.decision)+'</b><span>'+esc(e.reason||'—')+'</span></div>').join(''):'<p class="rv-empty">Dual-intelligence decisions not published yet</p>';
 const kills=Array.isArray(d.kills)?d.kills.slice(0,5):[];
 const logs=kills.length?kills.map(k=>'<div class="rv-log"><b>SKIP</b><span>'+esc(k[0])+': '+esc(val(k[1]))+' filtered</span></div>').join(''):'<p class="rv-empty">No skip summary available</p>';
 root.innerHTML='<div class="rv-top"><div><h1>⊕ Overview</h1><p>Market Intelligence · FOMO · Agents · Paper Trading</p></div><span class="'+(fresh?'rv-fresh':'rv-stale')+'">'+status+'</span></div>'+
 '<div class="rv-kpis">'+kpi('PAPER EQUITY',equity)+kpi('REALIZED P&L',pnl)+kpi('WIN RATE',total?(100*d.wins/total).toFixed(1)+'%':'—')+kpi('TOTAL PAPER TRADES',val(d.trades))+'</div>'+
 '<div class="rv-main"><div class="rv-left">'+panel('Equity Curve (Paper)','<div class="rv-equity">'+equity+'</div>'+chart(d),'rv-chart')+
 '<div class="rv-market">'+panel('◉ Market & FOMO Overview',fomoRows)+panel('♨ Top FOMO Opportunities',fomo&&Array.isArray(fomo.opportunities)&&fomo.opportunities.length?fomo.opportunities.slice(0,4).map(x=>'<div class="rv-line"><b>'+esc(x.symbol||x.mint)+'</b><span>'+esc(x.signal||'WATCH')+'</span></div>').join(''):'<p class="rv-empty">No verified FOMO opportunities</p>')+'</div></div>'+
 '<div class="rv-right">'+panel('▱ Open Positions ('+opens.length+')','<div class="rv-position rv-muted"><span>Token</span><span>Entry</span><span>Current</span><span>P&L</span></div>'+positions)+panel('♟ Major Agents',roster,'rv-agents')+'</div></div>'+
 '<div class="rv-bottom">'+panel('⌁ Agent Activity Feed',activity)+panel('◎ Latest Decisions',decisionRows)+panel('≡ System Logger',logs)+'</div>'+
 '<div class="rv-footer"><span>● '+(fresh?'Snapshot fresh':'Snapshot stale')+' · '+esc(d.asof||'Unknown time')+'</span><span>FOMO: '+(fomo?'Verified feed':'Not connected')+' · Paper only · No real orders</span></div>';
}
const original=window.ryderNightDeskDraw;
window.ryderNightDeskDraw=function(){if(typeof original==='function')original();draw();};
document.addEventListener('DOMContentLoaded',()=>{draw();const dash=document.getElementById('dashboard');if(dash){let pending=false;new MutationObserver(()=>{if(pending)return;pending=true;queueMicrotask(()=>{pending=false;const r=document.getElementById('rv-reference');if(!r||!r.isConnected)draw()})}).observe(dash,{childList:true});}window.addEventListener('hashchange',draw);});
if(document.readyState!=='loading')draw();
})();
