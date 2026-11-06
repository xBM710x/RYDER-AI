/* RYDER Night Desk: evidence-only advisory agents. No orders, wallets, or fabricated market data. */
(()=>{
'use strict';
const esc=x=>String(x??'Unknown').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
function report(d){
 const tokens=Array.isArray(d?.mission_control?.tokens)?d.mission_control.tokens:[];
 const viable=tokens.filter(t=>num(t.score)!==null&&num(t.liquidity)!==null&&num(t.price)!==null&&!(t.events||[]).some(x=>x.kind==='kill'));
 viable.sort((a,b)=>b.score-a.score);
 const lead=viable[0];
 const hunter=lead?{stat:viable.length+' scored candidates',text:'Top: '+String(lead.symbol||lead.mint?.slice(0,7)||'Unknown')+' · score '+lead.score+' · requires Filter/Risk approval'}:{stat:'0 verified candidates',text:'Waiting for scored tokens with price, liquidity and no recorded kill'};
 const closed=Array.isArray(d.closed)?d.closed:[];
 const strategist=closed.length<5?{stat:closed.length+' closed paper trades',text:'Insufficient sample for entry/exit optimization (minimum 5)'}:{stat:closed.length+' closed paper trades',text:'Trade review ready · recommendations only; no parameter changes'};
 const killed=tokens.filter(t=>(t.events||[]).some(x=>x.kind==='kill')).length;
 const unknown=tokens.filter(t=>num(t.liquidity)===null||num(t.price)===null).length;
 const sentinel={stat:killed+' flagged · '+unknown+' unpriced',text:unknown?'Missing price/liquidity: block recommendation until verified':'No missing quotes in observed radar sample; other risks remain unverified'};
 return [{name:'Hunter',...hunter},{name:'Strategist',...strategist},{name:'Sentinel',...sentinel}];
}
function draw(){
 if(typeof data==='undefined'||!data)return;
 const rail=document.getElementById('night-agent-rail')||document.getElementById('agents');
 if(!rail)return;
 let panel=document.getElementById('ryder-advisory-agents');
 if(!panel){panel=document.createElement('div');panel.id='ryder-advisory-agents';panel.style.cssText='border-top:1px solid #ffffff20;margin-top:12px;padding-top:10px';rail.appendChild(panel)}
 const stamp=data.updated_at?Date.parse(data.updated_at):NaN;
 const age=Date.now()-stamp;
 const stale=!Number.isFinite(stamp)||age<0||age>300000;
 const published=Array.isArray(data.advisory_agents)?data.advisory_agents.filter(a=>a&&typeof a.name==='string'&&typeof a.text==='string'&&typeof a.stat==='string'):[];
 const hasPublished=published.length===3&&['Hunter','Strategist','Sentinel'].every(n=>published.some(a=>a.name===n));
 // Older snapshots still work, but never describe browser estimates as Mac agents.
 const agents=hasPublished?published:report(data);
 const source=hasPublished?'MAC PUBLISHER':'BROWSER ESTIMATE · NOT MAC-VERIFIED';
 const freshness=stale?'STALE SNAPSHOT':hasPublished?'PAPER ONLY':'AWAITING MAC AGENT DATA';
 panel.innerHTML='<div style="font-size:11px;letter-spacing:.08em;color:#ff7892;margin-bottom:8px">ADVISORY AGENTS · '+source+' · '+freshness+'</div>'+agents.map(a=>'<div style="padding:7px 0;border-bottom:1px solid #ffffff12"><strong style="color:#fff">'+esc(a.name)+'</strong> <small style="color:#ff7892">'+esc(a.stat)+'</small><div style="font-size:12px;color:#bbb">'+esc(a.text)+'</div></div>').join('');
 const count=document.getElementById('agent-count');
 if(count)count.title=hasPublished?'Three read-only advisory agents evaluated by the Mac publisher; not independent workers.':'Advisory estimates use browser snapshot analysis until Mac publisher data is available.';
}

const previous=render;
render=function(){previous.apply(this,arguments);draw()};
if(typeof data!=='undefined'&&data)draw();
})();
