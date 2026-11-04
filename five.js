/* Desk views share one mint-keyed history dialog and one publisher snapshot. */
(() => {
  const escape = value => String(value ?? 'Unknown').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const when = ts => new Date(ts * 1000).toLocaleString();
  const empty = text => '<p class="sub">' + escape(text) + '</p>';
  const button = (name, value, text, active=false) => '<button type="button" data-' + name + '="' + escape(value) + '" aria-pressed="' + active + '">' + escape(text) + '</button>';
  let stage = -1, source = 'All', range = '24H';
  function voteSplit(votes){
    const scores=Object.entries(votes||{}).map(([agent,v])=>[agent,parseFloat(String(v).replace(/^\[/,''))]);
    const objections=scores.filter(([,score])=>score<0.5);
    return objections.length && scores.some(([,score])=>score>=0.5)?empty('Split decision · objections: '+objections.map(([agent])=>agent).join(', ')):'';
  }
  function timeline(mint) {
    const feed = data.desk_five || {};
    const token = feed.tokens?.[mint] || {};
    const radar = data.mission_control?.tokens?.find(t=>t.mint===mint);
    const events = [...(token.events || [])];
    if (!events.length) for (const event of radar?.events || []) events.push({ts:0,displayTime:event.t,kind:event.kind,why:event.reason});
    if (radar?.first_ts) events.push({ts:radar.first_ts,kind:'First observed',why:radar.source});
    for (const fill of feed.fills || []) {
      if (fill.mint !== mint) continue;
      for (const [key,label] of [['opened','paper_buy'],['closed','paper_exit']]) {
        const ts=fill[key];
        if(ts && !events.some(e=>e.kind===label && Math.abs(e.ts-ts)<2))
          events.push({ts,kind:label,why:key==='closed'?fill.reason:fill.version});
      }
    }
    const dialog = document.querySelector('#five-timeline') || document.body.appendChild(document.createElement('dialog'));
    dialog.id='five-timeline';
    dialog.innerHTML='<h2>'+escape(token.symbol || radar?.symbol || mint.slice(0,8))+' timeline</h2><p class="sub">'+escape(mint)+'</p>'+events.sort((a,b)=>a.ts-b.ts).map(e=>'<p><b>'+escape(e.kind)+'</b> · '+escape(e.displayTime || when(e.ts))+'<br>'+escape(e.why || '')+'</p>'+voteSplit(e.votes)+Object.entries(e.votes||{}).map(([agent,vote])=>empty(agent+' · '+vote)).join('')).join('')+(events.length?'':empty('No decision history in this snapshot.'))+'<button>Close</button>';
    dialog.querySelector('button').onclick=()=>dialog.close();
    if(!dialog.open) dialog.showModal();
  }
  function mount(parent,id,html,first=false) {
    if (!parent) return;
    let node=document.getElementById(id);
    if (!node) {node=document.createElement('section');node.id=id;node.className='card';if(first)parent.prepend(node);else parent.append(node);}
    node.innerHTML=html;
    return node;
  }
  function draw(page,research) {
    const feed=data.desk_five || {}, ready=Array.isArray(feed.stages);
    const wait=empty('Waiting for the upgraded Mac publisher.');
    const pulse=document.querySelector('#sleek-pulse'), review=document.querySelector('#sleek-research-body');
    const session=data.session_research;
    const usable=session && !session.error;
    if(page==='overview' && pulse){
      const metrics=usable?[['New tokens',session.new],['Rescued',session.rescued],['Paper entries',session.orders],['Net realized','$'+session.pnl],['Top blocker',session.blockers[0]?.[0]||'None recorded']]:[];
      mount(pulse,'six-recap','<details><summary>Session recap · since 6 PM Pacific</summary>'+
        (usable? metrics.map(([key,val])=>'<details><summary>'+escape(key)+' · '+escape(val)+'</summary>'+empty((session.evidence[key]||[]).join(' · ')||'No matching records.')+'</details>').join(''):wait)+'</details>',true);
    }
    if(page==='research' && research==='session' && review){
      const rows=(values,fmt)=>values.length?values.map(x=>empty(fmt(x))).join(''):empty('Waiting for qualifying observations.');
      review.innerHTML=!usable?empty(session?.error?'Session collector unavailable.':'Waiting for the updated Mac publisher.'):
        '<h3>Skipped-token paper fills</h3>'+empty(session.measured+' of '+session.sample+' sampled skipped tokens (at least 45 minutes old) had two usable quotes on the same pool. $25 simulated entry within 30 minutes of skip; exit 5–15 minutes later. Includes modeled pool impact and 0.3% fees each way.')+
        rows(session.replays,r=>r.symbol+' · $'+r.net+' net · '+when(r.entry)+' → '+when(r.exit))+
        '<h3>Lower-volume full-rule replay</h3>'+empty('Candidates between 75% and 100% of the normal volume bar. A recorded failing gate blocks the entry. Missing downstream evidence stays unknown.')+
        rows(session.rules,r=>r[0]+' · '+r[1]+' decisions')+
        '<h3>Launch to first usable quote</h3>'+empty('Median seconds from pool creation to the first observed fresh price with positive liquidity. Timing starts with this collector.')+
        rows(session.timing,r=>r.venue+' · '+(r.median_s??'unknown')+' seconds · '+r.n+' timed · '+r.unknown+' missing launch times')+
        '<h3>Exit-depth test</h3>'+empty('Pre-entry estimate for the planned paper position. Compares normal with half the quoted liquidity, using a balanced constant-product pool model.')+
        rows(session.depths,r=>r.symbol+' · estimated proceeds $'+r.expected+' · half depth $'+r.half)+
        '<h3>Agent disagreement review</h3>'+empty('An objection is a vote below 0.50 while another vote is at least 0.50. Counts are observed outcomes, including modeled skipped trades.')+
        rows(Object.entries(session.agents),([agent,r])=>agent+' · completed: '+(r.loss||0)+' losses / '+(r.gain||0)+' gains / '+(r.flat||0)+' flat · skipped replays: '+(r.skipped_gain||0)+' gains / '+(r.skipped_nonpositive||0)+' flat or losses');
    }
    if(page==='overview' && pulse) {
      const books=data.volume_research?.books || [];
      const recent=(data.tail||[]).slice(-3).reverse();
      const bookHtml=books.map(book=>'<details><summary>'+escape(book.book)+' lab · '+escape(book.open)+' open / '+escape(book.closed)+' closed</summary>'+
        ((book.activity||[]).map(fill=>empty(when(fill.ts)+' · '+fill.side+' '+fill.symbol+' · $'+fill.cost+' allocated'+(fill.pnl==null?'':' · net $'+fill.pnl))).join('')||empty('Waiting for published fill details.'))+'</details>').join('');
      mount(pulse,'work-feed','<h2>RYDER at work</h2>'+empty('Snapshot: '+(data.asof||'unknown'))+
        '<p>Main desk · '+escape(data.trades)+' reported trades</p>'+recent.map(r=>empty(r.t+' · '+r.ag+' · '+r.text)).join('')+
        '<h3>Volume lab · separate paper accounts</h3>'+ (bookHtml||empty('Waiting for lab activity.')),true);
      const stages=feed.stages || [];
      mount(pulse,'five-funnel','<h2>Trade funnel</h2>'+empty('Unique tokens first seen in the last 24 hours. Select a stage for up to 20 examples.')+(ready?'<div class="sleek-subnav">'+stages.map((s,i)=>button('stage',i,s.label+' · '+s.count,stage===i)).join('')+'</div>':wait)+(stages[stage]?.mints.map(m=>button('five-token',m,(feed.tokens[m]?.symbol || m.slice(0,8))+' · '+(feed.tokens[m]?.events?.at(-1)?.why || feed.tokens[m]?.events?.at(-1)?.kind || 'discovered'))).join('')||''),true);
      const points=feed.ranges?.[range] || [];
      const balance=document.querySelector('#balance'), svg=balance?.querySelector('svg.chart');
      if(svg && points.length) {
        const first=points[0][0],last=points.at(-1)[0],values=points.map(p=>p[1]),lo=Math.min(...values)-2,hi=Math.max(...values)+2;
        const x=t=>400*(t-first)/Math.max(1,last-first),y=v=>112-(v-lo)/(hi-lo)*104;
        const path=points.map(([t,v],i)=>(i?'L':'M')+x(t)+','+y(v)).join(' ');
        const paths=svg.querySelectorAll('path');paths[0].setAttribute('d',path+' L400,120 L0,120 Z');paths[1].setAttribute('d',path);
        svg.setAttribute('aria-label',range+' paper equity, '+values[0]+' to '+values.at(-1)+' dollars');
        svg.querySelectorAll('.fill-dot').forEach(n=>n.remove());
        const markers=new Set();
        for(const fill of feed.fills || []) for(const [key,label] of [['opened','Buy'],['closed','Sell']]){
          const t=fill[key],id=[fill.mint,key,t].join(':');if(!t||t<first||t>last||markers.has(id))continue;
          markers.add(id);
          svg.insertAdjacentHTML('beforeend','<circle class="fill-dot" tabindex="0" role="button" aria-label="'+escape(label+' '+fill.symbol)+'" data-five-token="'+escape(fill.mint)+'" cx="'+Math.max(5,Math.min(395,x(t)))+'" cy="'+(label==='Buy'?102:88)+'" r="5" fill="'+(label==='Buy'?'#7fffc3':'#ff8399')+'"><title>'+escape(label+' '+fill.symbol+' · '+when(t))+'</title></circle>');
        }
        const labels=balance.querySelectorAll('.times span');if(labels.length>=3){labels[0].textContent=when(first);labels[2].textContent=when(last);}
      }
      if(balance)mount(balance,'five-range','<div class="sleek-subnav">'+['24H','7D','All'].map(k=>button('range',k,k,k===range)).join('')+'</div>'+(!ready?wait:empty('Recorded history · trade markers show up to 200 recent position records.')));
    }
    if(page==='radar'){
      const desk=document.querySelector('#mission-desk');if(!desk)return;
      const watch=feed.watch || [], radar=data.mission_control?.tokens || [];
      const rows=watch.map(w=>({...radar.find(t=>t.mint===w.mint),...w})).filter(w=>source==='All'||(String(w.dex)+' '+String(w.source)).toLowerCase().replace(/[^a-z0-9]/g,'').includes(source.toLowerCase()));
      mount(desk,'five-watch','<h2>Fast-mover watchlist</h2>'+empty('Automatically pinned while awaiting entry confirmation.')+'<div class="sleek-subnav">'+['All','PumpFun','StonkFun','Meteora'].map(k=>button('source',k,k,source===k)).join('')+'</div>'+(rows.map(w=>'<p>'+button('five-token',w.mint,w.sym)+' · '+escape(w.wait_left)+'s to recheck · '+(w.previous>0 && w.latest>0?((w.latest/w.previous-1)*100).toFixed(2)+'% since prior quote':'Waiting for two quotes')+'</p>').join('')||(ready?empty('No pending tokens for this source.'):wait))+'<details><summary>Browse token timelines</summary>'+radar.map(t=>button('five-token',t.mint,t.symbol)).join('')+'</details>',true);
    }
    if(page==='research' && research==='volume' && review){
      const lab=data.volume_research;
      if(!lab||lab.error){review.innerHTML=empty(lab?.error?'Volume collector unavailable.':'Waiting for Mac volume collector.');return;}
      const attempts=lab.attempts||{}, queue=lab.followups||{};
      review.innerHTML='<h3>Volume coverage by venue</h3>'+empty('Volume-first rejections among the latest 4,000 skip checks over 24 hours. Counts are decisions, including repeat checks.')+
        (Object.entries(lab.venues||{}).map(([venue,v])=>empty(venue+' · '+(v.missing||0)+' missing · '+(v.low||0)+' below threshold · '+(v.unclassified||0)+' unclassified')).join('')||empty('No volume-first rejection records in sample.'))+
        '<h3>Second looks</h3>'+empty((queue.pending??'Unknown')+' waiting · '+(attempts.checked||0)+' rechecks in 24h · '+(attempts.observed||0)+' with volume data · '+(attempts.passed||0)+' passed all filter checks.')+
        '<h3>Volume threshold race</h3>'+empty('Separate $300 paper accounts. Standard uses the current volume bar. Lower uses 75% of it. Both use identical simulated costs, sizing and exit rules on priced candidates with liquidity. This isolates the volume screen; the main strategy has additional gates.')+
        ((lab.books||[]).map(b=>empty(b.book+' · '+(b.open+b.closed)+' entries · '+b.closed+' closed · $'+b.realized+' realized net · $'+b.realized_drawdown+' worst realized drawdown')).join('')||empty('Waiting for the first worker snapshot.'));
    }
    if(page==='research' && research==='diagnostics' && review){
      const checks=data.decision_review?.diagnostics;
      if(!checks){review.innerHTML=wait;return;}
      const row=(left,right)=>'<div class="reason"><span>'+escape(left)+'</span><b>'+escape(right)+'</b></div>';
      const reasons=checks.reasons.map(([label,count])=>row(label,count+' tokens')+
        '<meter aria-label="'+escape(label)+'" min="0" max="'+checks.skip_count+'" value="'+count+'"></meter>').join('');
      review.innerHTML='<h3>Why tokens were skipped</h3>'+empty('Latest skip per token in the last 24 hours, sampled from up to 4,000 logged decisions. '+checks.skip_count+' unique tokens.')+
        (reasons||empty('No skip decisions recorded in this window.'))+
        '<h3>Peak to final exit</h3>'+empty('Largest declines from a positive recorded peak to the last fill, in percentage points. '+checks.measured+' measurable openings out of '+checks.completed+' completed in the seven-day sample.')+
        (checks.giveback.map(r=>row(r.symbol+' · '+r.book,r.giveback_pp+' pp')).join('')||empty('No measurable positive peak and final exit yet.'))+
        '<h3>Confidence vs. outcomes</h3>'+empty('Average predicted win probability versus the share of openings that closed with a net gain. '+checks.scored+' of '+checks.completed+' openings had a recorded prediction.')+
        (checks.calibration.map(r=>row((r.band*20)+'–'+((r.band+1)*20)+'% band · '+r.count+' trades',r.predicted+'% predicted / '+r.actual+'% won')).join('')||empty('Waiting for completed paper trades with recorded predictions.'));
    }
    if(page==='research' && research==='race' && review){
      const books=data.opportunity_lab?.capacity?.books || [];
      review.innerHTML='<h3>Strategy race</h3>'+empty('Same qualified signals and modeled costs. Control allows 4 entries per hour and challenger allows 8. Each starts with $300 paper.')+(books.map(b=>'<div class="details"><b>'+escape(b.book)+'</b> · '+escape(b.open+b.closed)+' entries · '+escape(b.open)+' open<br>Realized net $'+escape(b.realized)+' · worst realized drawdown $'+escape(b.realized_drawdown??'pending')+'</div>').join('')||empty('Waiting for qualified candidates.'))+empty('Drawdown tracks closed results. Open losses are excluded.');
    }
    if(page==='trades'){
      const host=document.querySelector('#trades');if(host){
        const fills=new Map((feed.fills||[]).map(f=>[f.mint,f.symbol]));
        mount(host,'five-trades','<details><summary>Trade timelines</summary>'+([...fills].map(([m,s])=>button('five-token',m,s)).join('')||empty('No published trade timelines yet.'))+'</details>');
      }
    }
  }
  document.addEventListener('click',ev=>{
    const el=ev.target.closest('[data-stage],[data-five-token],[data-range],[data-source]');if(!el)return;
    if(el.hasAttribute('data-five-token')){timeline(el.dataset.fiveToken);return;}
    if(el.hasAttribute('data-stage'))stage=stage===+el.dataset.stage?-1:+el.dataset.stage;
    if(el.dataset.range)range=el.dataset.range;
    if(el.dataset.source)source=el.dataset.source;
    window.ryderFiveRefresh?.();
  });
  document.addEventListener('keydown',ev=>{if(ev.target.matches('.fill-dot') && ['Enter',' '].includes(ev.key)){ev.preventDefault();timeline(ev.target.dataset.fiveToken);}});
  window.ryderFiveDraw=draw;
})();
