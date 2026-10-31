/* RYDER Calendar view: realized PAPER P&L per day (America/Los_Angeles), all desks. Reads data.json "calendar" field only. */
(function(){
const TZ='America/Los_Angeles',$=s=>document.querySelector(s);
let C=null,ym=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=(v,sign)=>(sign&&v>0?'+':v<0?'−':'')+'$'+Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const ld=t=>new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(t*1000));
const fmtDate=t=>new Intl.DateTimeFormat('en-US',{timeZone:TZ,month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(t*1000));
function view(){let v=$('#calview');if(!v){v=document.createElement('section');v.id='calview';v.hidden=true;$('main').insertBefore(v,$('nav'));}return v}
function spark(c,start){const pts=[{v:start},...c];if(pts.length<2)return'';const vs=pts.map(p=>p.v),mn=Math.min(...vs),mx=Math.max(...vs),r=mx-mn||1;
 const P=pts.map((p,i)=>`${(i/(pts.length-1)*100).toFixed(1)},${(28-(p.v-mn)/r*26).toFixed(1)}`).join(' ');const up=vs[vs.length-1]>=start;
 return `<svg class="cal-spark" viewBox="0 0 100 30" preserveAspectRatio="none"><polyline points="${P}" fill="none" stroke="${up?'var(--green)':'var(--red)'}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`}
function draw(){const v=view();if(!C){v.innerHTML='<div class="card cal-empty">Calendar data isn’t in this feed yet. It appears after the next bot update.</div>';return}
 const days=C.days||{},today=C.today||ld(Date.now()/1000);if(!ym)ym=today.slice(0,7);
 const [Y,M]=ym.split('-').map(Number),first=new Date(Date.UTC(Y,M-1,1)),nd=new Date(Date.UTC(Y,M,0)).getUTCDate(),lead=(first.getUTCDay()+6)%7;
 const vals=Object.values(days).map(x=>Math.abs(x.pnl)),mx=Math.max(1,...vals);
 let g='';for(let i=0;i<lead;i++)g+='<div class="cal-d blank"></div>';
 for(let d=1;d<=nd;d++){const k=`${ym}-${String(d).padStart(2,'0')}`,x=days[k];let st='',cls='cal-d',inner='';
  if(x){const a=(0.18+0.7*Math.abs(x.pnl)/mx).toFixed(2);cls+=x.pnl>0?' g':x.pnl<0?' r':' z';st=` style="--a:${a}"`;inner=`<small>${x.pnl>=0?'+':'−'}$${Math.abs(x.pnl)<100?Math.abs(x.pnl).toFixed(2):Math.round(Math.abs(x.pnl))}</small><i>${x.n} trade${x.n>1?'s':''}</i>`}
  if(k===today)cls+=' today';g+=`<div class="${cls}"${st}><b>${d}</b>${inner}</div>`}
 const ks=Object.keys(days).sort(),green=ks.filter(k=>days[k].pnl>0).length,red=ks.filter(k=>days[k].pnl<0).length;
 let best=null;ks.forEach(k=>{if(!best||days[k].pnl>days[best].pnl)best=k});
 let streak=0,maxs=0,cur=0;ks.forEach(k=>{cur=days[k].pnl>0?cur+1:0;maxs=Math.max(maxs,cur)});for(let i=ks.length-1;i>=0&&days[ks[i]].pnl>0;i--)streak++;
 const pnl=C.equity-C.start,pct=pnl/C.start*100,wr=C.trades?Math.round(C.wins/C.trades*100):0,mName=first.toLocaleString('en-US',{month:'long',year:'numeric',timeZone:'UTC'});
 const bd=best?new Date(best+'T12:00:00Z').toLocaleString('en-US',{month:'short',day:'numeric',timeZone:'UTC'}):'—';

 v.innerHTML=`<div class="card cal-head"><div class="row"><span class="label">Paper equity · all desks</span><b class="cal-sim">PAPER / SIM</b></div>
 <div class="cal-eq">${money(C.equity)}</div><div class="cal-pnl ${pnl>=0?'up':'dn'}">${money(pnl,1)} (${pct>=0?'+':''}${pct.toFixed(2)}%)</div>
 <div class="cal-sub">${C.trades} closed trade${C.trades==1?'':'s'} · ${wr}% win rate${C.open?` · ${C.open} open`:''} · start ${money(C.start)}</div>${spark(C.curve||[],C.start)}</div>
 <div class="card"><div class="cal-nav"><button data-m="-1" aria-label="Previous month">‹</button><b>${mName}</b><button data-m="1" aria-label="Next month">›</button></div>
 <div class="cal-grid cal-wk">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(w=>`<span>${w}</span>`).join('')}</div><div class="cal-grid">${g}</div>
 <p class="cal-note">Realized paper P&amp;L by day, Pacific time</p></div>
 <div class="cal-stats"><div class="card"><span>Green days</span><b class="up">${green}</b><small>of ${ks.length} day${ks.length==1?'':'s'}</small></div><div class="card"><span>Red days</span><b class="dn">${red}</b><small>of ${ks.length} day${ks.length==1?'':'s'}</small></div>
 <div class="card"><span>Best day</span><b class="${best&&days[best].pnl>0?'up':'dn'}">${best?money(days[best].pnl,1):'—'}</b><small>${bd}</small></div><div class="card"><span>Green streak</span><b>${streak}d</b><small>in a row · best ${maxs}d</small></div></div>`;
 v.querySelectorAll('.cal-nav button').forEach(b=>b.onclick=()=>{let [y,m]=ym.split('-').map(Number);m+=+b.dataset.m;if(m<1){m=12;y--}if(m>12){m=1;y++}ym=`${y}-${String(m).padStart(2,'0')}`;draw()})}
async function load(){try{const r=await fetch('data.json?cal='+Date.now(),{cache:'no-store',credentials:'omit'});if(r.ok){const d=await r.json();if(d&&d.calendar)C=d.calendar}}catch{}draw()}
function show(on){const v=view();v.hidden=!on;document.body.classList.toggle('cal-on',on);if(on){window.scrollTo(0,0);load()}}
function init(){document.querySelectorAll('nav a').forEach(a=>a.addEventListener('click',e=>{if(a.getAttribute('href')==='#calendar'){e.preventDefault();show(true);if(location.hash!=='#calendar')history.replaceState(null,'','#calendar')}else show(false)}));
 if(location.hash==='#calendar'){document.querySelectorAll('nav a').forEach(n=>n.classList.toggle('active',n.getAttribute('href')==='#calendar'));show(true)}
 setInterval(()=>{if(!view().hidden&&!document.hidden)load()},60000)}
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init();
})();
