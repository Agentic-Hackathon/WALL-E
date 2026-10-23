/* Original charts: actual Wallex data / recorded roles; no FinRL policy claims. */
pages.backtest=['Backtest','Backtest'];
const btSection=document.createElement('section');btSection.id='backtest';btSection.hidden=true;
btSection.innerHTML=`<div class="toolbar"><select id="bt-market" aria-label="Market"><option>BTCTMN</option><option>ETHTMN</option></select><input id="bt-start" type="datetime-local" aria-label="Start UTC"><input id="bt-end" type="datetime-local" aria-label="End UTC"><button id="bt-go">↻</button></div><div id="bt-charts"></div>`;
document.querySelector('main footer').before(btSection);
const beforeBacktestOpen=open;
open=async function(page){await beforeBacktestOpen(page);$('notice').hidden=page==='backtest';document.querySelector('main footer').hidden=page==='backtest';if(page==='backtest')await backtestCharts()};
const btDate=x=>new Date(x*1000).toISOString().slice(0,16);
let btSerial=0;
function btCanvas(id,title){return `<article class="card"><h2>${esc(title)}</h2><canvas id="${id}" aria-label="${esc(title)}"></canvas></article>`}
function btContext(id,height=290){const cv=$(id),w=Math.max(330,cv.parentElement.clientWidth-44),r=devicePixelRatio||1;cv.width=w*r;cv.height=height*r;cv.style.height=height+'px';const c=cv.getContext('2d');c.scale(r,r);c.font='11px Tahoma';c.textAlign='left';c.direction='ltr';return {c,w,h:height}}
function btLines(id,series,markers=[]){
 const {c,w,h}=btContext(id),all=series.flatMap(s=>s.rows);
 if(!all.length){c.fillStyle='#a0afc4';c.fillText('N/A',30,120);return}
 const cols=Math.max(1,Math.floor((w-85)/190)),top=30+Math.ceil(series.length/cols)*17;
 const ts=all.map(p=>p.timestamp),vs=all.map(p=>p.value),start=Math.min(...ts),end=Math.max(...ts),lo=Math.min(...vs),hi=Math.max(...vs),x=t=>85+(t-start)/(end-start||1)*(w-110),y=v=>top+(hi-v)/(hi-lo||1)*(h-top-55);
 for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3;c.fillStyle='#a0afc4';c.fillText(num(v),2,y(v));c.strokeStyle='#29374d';c.beginPath();c.moveTo(82,y(v));c.lineTo(w-20,y(v));c.stroke()}
 series.forEach((s,i)=>{c.strokeStyle=c.fillStyle=s.color;c.lineWidth=2;c.beginPath();s.rows.forEach((p,j)=>j?c.lineTo(x(p.timestamp),y(p.value)):c.moveTo(x(p.timestamp),y(p.value)));c.stroke();c.fillText(s.name,85+(i%cols)*190,18+Math.floor(i/cols)*17)});
 markers.forEach(m=>{c.fillStyle=m.side==='BUY'?'#53d8b7':'#ef8585';c.beginPath();c.arc(x(m.timestamp),y(m.price),4,0,7);c.fill()});
 c.fillStyle='#a0afc4';c.fillText(btDate(start).replace('T',' '),85,h-16);c.textAlign='right';c.fillText(btDate(end).replace('T',' ')+' UTC',w-20,h-16);
}
async function backtestCharts(){
 const serial=++btSerial;const query={symbol:$('bt-market').value};
 for(const key of ['start','end'])if($('bt-'+key).value)query[key]=Date.parse($('bt-'+key).value+'Z')/1000;
 $('bt-charts').innerHTML=btCanvas('bt-loading','Backtest · UTC');
 try{const r=await get('/api/backtest-charts?'+new URLSearchParams(query));if(serial!==btSerial||current!=='backtest')return;
 if(r.requested_start){$('bt-start').value=btDate(r.requested_start);$('bt-end').value=btDate(r.requested_end)}
 const rules=Object.entries(r.rules||{}),colors=['#53d8b7','#8aaeff','#ffc56b'];
 const pnl=rules.map(([name,s])=>`${name}: ${num(s.net_pnl_tmn)} TMN`).join(' · ');
 $('bt-charts').innerHTML=btCanvas('bt-price',r.symbol+' · SMA BUY / SELL · فرضی')+
 btCanvas('bt-equity','Equity · قواعد ثابت فرضی · fee 0.30% / slip 0.05% هر سمت')+
 btCanvas('bt-pnl','PnL فرضی · '+(pnl||'N/A — '+r.status))+
 btCanvas('bt-dd','Drawdown % · فرضی')+
 btCanvas('bt-roles','Agent timeline · تصمیم‌های ثبت‌شده · بدون بازده مستقل')+
 btCanvas('bt-shadow','Shadow NAV · رسیدهای واقعی حساب فرضی');
 btLines('bt-price',[{name:r.symbol,color:'#8aaeff',rows:(r.bars||[]).map(b=>({timestamp:b.timestamp,value:b.close}))}],rules[0]?.[1].events||[]);
 const equities=rules.map(([name,s],i)=>({name,color:colors[i],rows:s.curve.map(p=>({timestamp:p.timestamp,value:p.nav_tmn}))}));
 Object.entries(r.baselines||{}).forEach(([name,s],i)=>equities.push({name,color:['#da98ee','#a0afc4'][i],rows:s.curve.map(p=>({timestamp:p.timestamp,value:p.nav_tmn}))}));
 btLines('bt-equity',equities);btLines('bt-pnl',equities.map(s=>({...s,rows:s.rows.map(p=>({...p,value:p.value-5000000}))})));
 btLines('bt-dd',rules.map(([name,s],i)=>({name,color:colors[i],rows:s.curve.map(p=>({timestamp:p.timestamp,value:p.drawdown_pct}))})));
 const decisions=r.agent_decisions||[],sessions=[...new Set(decisions.map(d=>d.session))];
 btLines('bt-shadow',sessions.map((name,i)=>({name:name.replace('financial_',''),color:colors[i%3],rows:decisions.filter(d=>d.session===name).map(d=>({timestamp:d.timestamp,value:d.nav_tmn}))})));
 const roles=[...new Set(decisions.flatMap(d=>d.agents.map(a=>a.role)))],{c,w,h}=btContext('bt-roles',Math.max(270,roles.length*30+65));
 if(!roles.length){c.fillStyle='#a0afc4';c.fillText('N/A',25,120)}else{
 const first=decisions[0].timestamp,last=decisions.at(-1).timestamp;
 roles.forEach((role,i)=>{c.fillStyle='#a0afc4';c.fillText(role,5,30+i*30);decisions.forEach(d=>{const a=d.agents.find(a=>a.role===role);if(!a)return;const vote=a.recommendation||'';c.fillStyle=/BUY|EVALUATE/.test(vote)?'#53d8b7':/SELL|VETO/.test(vote)?'#ef8585':'#8aaeff';c.fillRect(250+(d.timestamp-first)/(last-first||1)*(w-275),18+i*30,4,16)})});
 c.fillStyle='#a0afc4';c.fillText(btDate(first).replace('T',' '),250,h-20);c.fillText('BUY/EVALUATE ●    SELL/VETO ●    ABSTAIN/RESEARCH ●',250,h-40);
 }
 }catch(e){$('bt-charts').innerHTML=btCanvas('bt-error','Backtest · N/A');const {c}=btContext('bt-error');c.fillStyle='#a0afc4';c.fillText('N/A',25,100)}
}
$('bt-go').onclick=backtestCharts;
$('bt-market').onchange=()=>{$('bt-start').value='';$('bt-end').value='';backtestCharts()};
locale();
