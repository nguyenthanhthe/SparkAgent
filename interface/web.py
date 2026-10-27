"""Local web dashboard (aiohttp).

Serves a single-page dashboard and a JSON API:

    GET  /                     dashboard page
    GET  /api/status           daemon status (uptime, brain tiers, GPU, tasks)
    GET  /api/tasks            task list          POST /api/tasks  submit
    GET  /api/tasks/{id}       single task detail
    POST /api/tasks/{id}/cancel|pause|resume
    GET  /api/episodes         recent episodes
    GET  /api/memories?q=...   vector recall
    GET  /api/adapters         brain tier router status + adapter catalog
    GET  /api/skills           skills (active+pending)
    POST /api/skills           create (operator source)  {name,description,parameters,code}
    POST /api/skills/{name}/approve
    GET  /api/stream           SSE: logs + status events

Security: binds 127.0.0.1 by default; if the SPARKAGENT_WEB_TOKEN secret is
set (env/vault) every /api request must carry it as a Bearer token.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import aiohttp
from aiohttp import web
from kernel.logging import get_logger
from security.auth_limiter import AuthRateLimiter

logger = get_logger("web")


# --------------------------------------------------------------------- page
_DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SparkAgent</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#c9d1d9;--dim:#8b949e;
--accent:#58a6ff;--ok:#3fb950;--warn:#d29922;--err:#f85149;--mono:ui-monospace,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.5 system-ui,sans-serif;padding:16px}
h1{font-size:18px;margin:0 0 12px}h1 span{color:var(--dim);font-weight:400}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin-bottom:12px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px}
.card h2{font-size:12px;margin:0 0 8px;color:var(--dim);text-transform:uppercase;letter-spacing:.08em}
.kv{display:flex;justify-content:space-between;font-family:var(--mono);font-size:13px;padding:2px 0}
.kv b{color:var(--accent);font-weight:600}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-family:var(--mono)}
.b-ok{background:#1b3a25;color:var(--ok)}.b-err{background:#3d1a1a;color:var(--err)}
.b-warn{background:#3a2f14;color:var(--warn)}.b-dim{background:#22272e;color:var(--dim)}
textarea,input,select{width:100%;background:var(--bg);color:var(--text);
border:1px solid var(--border);border-radius:6px;padding:6px 8px;font:13px var(--mono)}
textarea{min-height:64px;resize:vertical}textarea.code{min-height:140px}
button{background:#21262d;color:var(--text);border:1px solid var(--border);
border-radius:6px;padding:6px 14px;cursor:pointer;font-size:13px}
button:hover{border-color:var(--accent);color:var(--accent)}
button.small{padding:2px 8px;font-size:11px}
.row{display:flex;gap:8px;margin-top:8px}.row>*{flex:1}
table{width:100%;border-collapse:collapse;font-size:12.5px;font-family:var(--mono)}
td,th{padding:4px 6px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:500}
#log{background:#010409;border:1px solid var(--border);border-radius:8px;
padding:8px;height:280px;overflow-y:auto;font:12px var(--mono);white-space:pre-wrap}
.toast{position:fixed;right:16px;bottom:16px;background:var(--panel);
border:1px solid var(--accent);border-radius:8px;padding:8px 14px;display:none}
details{margin-bottom:8px}summary{cursor:pointer;color:var(--dim)}
</style></head><body>
<h1>&#9889; SparkAgent <span id="uptime">—</span>
  <span id="quarbadge" class="badge b-warn" style="display:none"></span></h1>
<div class="grid">
  <div class="card"><h2>Brain</h2><div id="brain"></div></div>
  <div class="card"><h2>GPU / System</h2><div id="system"></div></div>
  <div class="card"><h2>Scheduler</h2><div id="sched"></div></div>
  <div class="card"><h2>Adapters</h2><div id="adapters"></div></div>
</div>
<div class="card" style="margin-bottom:12px"><h2>Spend today</h2>
  <div id="cost"><span style="color:var(--dim)">loading…</span></div>
</div>
<div class="card" style="margin-bottom:12px"><h2>Backups
  <a href="/api/docs/runbook-backups" style="font-size:11px;font-weight:normal">runbook</a></h2>
  <div id="backups"><span style="color:var(--dim)">loading…</span></div>
</div>
<div class="card" style="margin-bottom:12px"><h2>New task</h2>
  <textarea id="goal" placeholder="Describe a goal for the agent…"></textarea>
  <div class="row">
    <select id="schedule"><option value="">once</option>
      <option value="300">every 5 min</option><option value="3600">hourly</option>
      <option value="86400">daily</option></select>
    <button onclick="submitTask()">Submit</button>
  </div>
</div>
<div class="grid">
<div class="card"><h2>Tasks</h2><div id="taskdetail" style="display:none;margin-bottom:8px;font:12px var(--mono)"></div><div style="max-height:240px;overflow:auto"><table id="tasks"></table></div></div>
<div class="card"><h2>Skills</h2><div style="max-height:240px;overflow:auto"><table id="skills"></table></div></div>
</div>
<div class="card" style="margin-bottom:12px"><h2>Episodes</h2>
  <div style="max-height:220px;overflow:auto"><table id="episodes"></table></div>
</div>
<div class="card" id="epdetail" style="margin-bottom:12px;display:none">
  <h2>Episode detail <button class="small" style="float:right"
    onclick="$('epdetail').style.display='none'">close</button></h2>
  <div id="ephead"></div>
  <div id="epsteps" style="max-height:320px;overflow:auto;margin-top:8px"></div>
</div>
<div class="card" style="margin-bottom:12px"><h2>Operator approvals <span id="apcount" class="badge b-warn" style="display:none"></span></h2>
  <div style="max-height:180px;overflow:auto"><table id="approvals"></table></div>
</div>
<div class="card" style="margin-bottom:12px"><h2>Quarantine</h2>
  <div style="max-height:160px;overflow:auto"><table id="quarantine"></table></div>
</div>
<div class="card" style="margin-bottom:12px"><h2>Memory recall</h2>
  <div class="row" style="margin:0 0 8px"><input id="memq" placeholder="search long-term memory…"
    onkeydown="if(event.key==='Enter')memSearch()"><button onclick="memSearch()">Recall</button></div>
  <div id="mem"><span style="color:var(--dim)">semantic search over episodes &amp; notes</span></div>
</div>
<details class="card"><summary>Create a skill manually (operator)</summary>
  <div class="row"><input id="sk-name" placeholder="skill_name"></div>
  <div class="row" style="margin-top:8px"><input id="sk-desc" placeholder="description (min 10 chars)"></div>
  <div class="row" style="margin-top:8px"><input id="sk-params" placeholder='{"x": {"type": "string", "required": true}}'></div>
  <textarea class="code" id="sk-code" style="margin-top:8px"
    placeholder="def run(**params): …  (no imports; helpers: fetch, read_file, write_file, list_dir, run_command, log)"></textarea>
  <div class="row"><span></span><button onclick="createSkill()">Create skill</button></div>
</details>
<div class="card" style="margin-bottom:12px"><h2>Swarm activity</h2>
  <div id="swarm" style="max-height:160px;overflow:auto;font:12px var(--mono)">
    <span style="color:var(--dim)">multi-agent progress appears here</span></div>
</div>
<div class="card" style="margin-bottom:12px"><h2>Swarm topologies</h2>
  <div id="topologies" style="max-height:260px;overflow:auto;font:12px var(--mono)">
    <span style="color:var(--dim)">loading…</span></div>
</div>
<div class="card" style="margin-bottom:12px"><h2>Live log</h2><div id="log"></div></div>
<div class="toast" id="toast"></div>
<script>
const $=id=>document.getElementById(id);
function toast(msg){const t=$('toast');t.textContent=msg;t.style.display='block';
  setTimeout(()=>t.style.display='none',2500)}
async function api(path,opts){const r=await fetch(path,opts);
  if(!r.ok)throw new Error((await r.text())||r.status);return r.json()}
function kv(k,v){return `<div class="kv"><span>${k}</span><b>${v==null?'—':v}</b></div>`}
function badge(cls,text){return `<span class="badge ${cls}">${text}</span>`}

async function refreshStatus(){try{const s=await api('/api/status');
  $('uptime').textContent=`· up ${Math.floor(s.uptime_s/60)} min · ${s.agent}`;
  const qb=$('quarbadge');
  if(s.quarantine&&s.quarantine.items>0){
    qb.style.display='inline';
    qb.textContent=`quarantine ${s.quarantine.items} · ${(s.quarantine.bytes/1024).toFixed(0)} KB`;
  } else qb.style.display='none';
  const b=s.brain||{};let h='';
  if(b.local)h+=kv('tier 1 · local',`${b.local.model} ${b.local.ok?badge('b-ok','ok'):badge('b-err',b.local.detail||'down')}`);
  if(b.remote)h+=kv('tier 2 · remote',`${b.remote.model} ${b.remote.ok?badge('b-ok','ok'):badge('b-warn',b.remote.detail)}`);
  if(b.stats)for(const[t,st]of Object.entries(b.stats))h+=kv(`${t} calls`,`${st.requests} ok / ${st.failures} fail`);
  $('brain').innerHTML=h;
  const sys=s.system||{};let g='';if(sys.gpu&&sys.gpu.available)
    for(const gpu of sys.gpu.gpus)g+=kv(gpu.name,`${gpu.utilization_pct}% · ${gpu.vram_used_mb}/${gpu.vram_total_mb} MB · ${gpu.temperature_c}°C`);
  else g=kv('gpu','not available');
  if(sys.ram)g+=kv('ram',`${sys.ram.used_pct}% of ${sys.ram.total_gb} GB`);
  if(sys.disk)g+=kv('disk free',`${sys.disk.free_gb} / ${sys.disk.total_gb} GB`);
  $('system').innerHTML=g;
  $('sched').innerHTML=kv('episodes done',s.scheduler.episodes_done)
    +kv('episodes failed',s.scheduler.episodes_failed)
    +kv('blocked tasks',s.scheduler.blocked_tasks??0)
    +kv('tools',s.tools?s.tools.length:0)
    +kv('skills pending',(s.skills_pending||[]).length);
}catch(e){$('uptime').textContent='· offline'}}
async function refreshTasks(){try{const payload=await api('/api/tasks');
  const tasks=payload.items||[];
  $('tasks').innerHTML='<tr><th>#</th><th>goal</th><th>status</th><th></th></tr>'+
   tasks.map(t=>{const blk=(t.blocked_by||[]).length
     ?badge('b-warn','blocked by '+(t.blocked_by||[]).map(b=>'#'+b).join(',')):'';
     return `<tr onclick="showTask(${t.id})" style="cursor:pointer">
    <td>${t.id}</td><td>${esc(t.goal.slice(0,80))} ${blk}</td>
    <td>${t.enabled?t.status:badge('b-dim',t.status)}</td>
    <td>${t.enabled?`<button class="small" onclick="event.stopPropagation();cancelTask(${t.id})">cancel</button>`:''}</td></tr>`;}).join('');
}catch(e){}}
async function showTask(id){try{const t=await api('/api/tasks/'+id);
  const blocked=(t.blocked_by||[]).map(b=>`#${b}`).join(', ');
  $('taskdetail').innerHTML=`<b>#${t.id}</b> ${esc(t.goal)}<br>
    <span class="badge ${t.status==='done'?'b-ok':'b-warn'}">${t.status}</span>
    priority ${t.priority??5} · runs ${t.last_run_at?new Date(t.last_run_at*1000).toLocaleTimeString():'never'}
    ${t.depends_on?`· depends on ${(t.depends_on||[]).map(b=>'#'+b).join(', ')} (${blocked?'blocked by '+blocked:'satisfied'})`:''}`;
  $('taskdetail').style.display='block';
}catch(e){toast(e.message)}}
async function refreshSkills(){try{const sk=await api('/api/skills');
  $('skills').innerHTML='<tr><th>name</th><th>status</th><th></th></tr>'+
   sk.map(s=>`<tr><td>${s.name}</td><td>${s.status==='active'?badge('b-ok','active'):badge('b-warn','pending')}</td>
    <td>${s.status!=='active'?`<button class="small" onclick="approveSkill('${s.name}')">approve</button>`:''}</td></tr>`).join('');
}catch(e){}}
async function submitTask(){const goal=$('goal').value.trim();if(!goal)return toast('goal is empty');
  const interval=$('schedule').value?Number($('schedule').value):undefined;
  try{const r=await api('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({goal,interval_seconds:interval})});toast('submitted #'+r.id);$('goal').value='';refreshTasks()}
  catch(e){toast('failed: '+e.message)}}
async function cancelTask(id){try{await api(`/api/tasks/${id}/cancel`,{method:'POST'});refreshTasks()}catch(e){toast(e.message)}}
async function approveSkill(name){try{await api(`/api/skills/${name}/approve`,{method:'POST'});refreshSkills();toast('approved')}catch(e){toast(e.message)}}
async function memSearch(){const q=$('memq').value.trim();if(!q)return;
  try{const hits=await api('/api/memories?q='+encodeURIComponent(q));
   $('mem').innerHTML=hits.length?hits.map(h=>`<div style="margin-bottom:6px">
     <span class="badge b-dim">${h.kind} · ${h.score.toFixed(2)}</span>
     <div>${h.text.slice(0,220)}</div></div>`).join(''):'(no memories)'}catch(e){toast(e.message)}}
async function createSkill(){try{const r=await api('/api/skills',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({
   name:$('sk-name').value,description:$('sk-desc').value,
   parameters:JSON.parse($('sk-params').value||'{}'),code:$('sk-code').value})});
  toast('skill '+r.status);refreshSkills()}catch(e){toast('failed: '+e.message)}}

async function refreshApprovals(){try{const data=await api('/api/approvals');
  const pend=data.pending||[];
  $('apcount').style.display=pend.length?'inline-block':'none';
  $('apcount').textContent=pend.length;
  $('approvals').innerHTML='<tr><th>id</th><th>kind</th><th>summary</th><th></th></tr>'+
   (pend.length?pend.map(a=>`<tr><td>${a.id.slice(0,8)}</td><td>${a.kind}</td>
     <td>${a.summary.slice(0,70)}</td>
     <td><button class="small" onclick="decide('${a.id}','approve')">approve</button>
         <button class="small" onclick="decide('${a.id}','deny')">deny</button></td></tr>`).join('')
    :'<tr><td colspan="4" style="color:var(--dim)">nothing pending</td></tr>');
}catch(e){}}
async function decide(id,decision){try{await api(`/api/approvals/${id}/${decision}`,{method:'POST'});
  toast('approval '+decision+'d');refreshApprovals()}catch(e){toast(e.message)}}
let quarFilter='';
function setQuarFilter(reason){
  const word=String(reason||'').split(' ')[0];
  quarFilter=(quarFilter===word)?'':word;   // click again to clear
  refreshQuarantine();
}
async function refreshQuarantine(){try{
  const qs=quarFilter?`?reason=${encodeURIComponent(quarFilter)}`:'';
  const data=await api('/api/quarantine'+qs);
  const items=data.items||[];
  $('quarantine').innerHTML='<tr><th>id</th><th>reason</th><th>size</th><th></th></tr>'+
   (items.length?items.map(q=>`<tr><td>${q.id.slice(0,8)}</td>
     <td><a href="#" style="color:var(--fg)" onclick="setQuarFilter('${esc(String(q.reason))}')">${esc(String(q.reason).slice(0,50))}</a></td>
     <td>${q.size_bytes}B</td>
     <td><button class="small" onclick="quar('${q.id}','release')">release</button>
         <button class="small" onclick="quar('${q.id}','delete')">delete</button></td></tr>`).join('')
    :'<tr><td colspan="4" style="color:var(--dim)">empty'+(quarFilter?' (filter: '+esc(quarFilter)+')':'')+'</td></tr>');
}catch(e){}}
async function quar(id,action){try{const r=await api(`/api/quarantine/${id}/${action}`,{method:'POST'});
  toast(action+'d');refreshQuarantine()}catch(e){toast(e.message)}}

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function epBadge(st){return st==='success'?badge('b-ok',st):
  st==='failed'?badge('b-err',st):badge('b-warn',st)}
async function refreshEpisodes(){try{const payload=await api('/api/episodes?limit=15');
  const eps=payload.items||payload||[];
  $('episodes').innerHTML='<tr><th>#</th><th>goal</th><th>status</th><th>tags</th><th></th></tr>'+
   (eps.length?eps.map(e=>`<tr><td>${e.id}</td><td>${esc(e.goal.slice(0,80))}</td>
    <td>${epBadge(e.status)}</td>
    <td>${(e.tags||[]).map(t=>badge('b-dim',esc(t))).join(' ')||'<span style="color:var(--dim)">—</span>'}</td>
    <td><button class="small" onclick="showEpisode(${e.id})">view</button></td></tr>`).join('')
    :'<tr><td colspan="5" style="color:var(--dim)">no episodes yet</td></tr>');
}catch(e){}}
async function showEpisode(id){try{const d=await api('/api/episodes/'+id);
  $('epdetail').style.display='block';
  $('ephead').innerHTML=kv('goal',esc(d.goal))+kv('status',epBadge(d.status))
    +kv('source',esc(d.source))+kv('tier',esc(d.model_tier||'—'))
    +((d.tags||[]).length?kv('tags',(d.tags||[]).map(t=>badge('b-dim',esc(t))).join(' ')):'')
    +(d.final_answer?`<div style="margin-top:6px;font-size:13px">${esc(d.final_answer.slice(0,600))}</div>`
      :'<div style="margin-top:6px;color:var(--dim)">no final answer yet</div>');
  $('epsteps').innerHTML='<table><tr><th>#</th><th>kind</th><th>content</th></tr>'+
   ((d.step_log||[]).length?d.step_log.map(s=>`<tr><td>${s.idx}</td>
     <td>${esc(s.kind)}</td><td style="white-space:pre-wrap">${esc(String(s.content).slice(0,500))}</td></tr>`).join('')
    :'<tr><td colspan="3" style="color:var(--dim)">no steps recorded</td></tr>')+'</table>';
  $('epdetail').scrollIntoView({behavior:'smooth',block:'start'});
}catch(e){toast('failed: '+e.message)}}

async function refreshCost(){try{const b=await api('/api/brain');
  const today=b.budget.today_usd;
  const cache=b.cache||{};
  const days=Object.values(b.costs_last_7_days||{});
  const avg=days.length?days.reduce((a,v)=>a+v,0)/days.length:0;
  const arrow=today>avg*1.1?' ▲':(avg>0&&today<avg*0.5?' ▼':'');
  const byModel=Object.entries(b.costs.by_model||{})
    .filter(([m,r])=>r.cost_usd>0)
    .map(([m,r])=>`${m}: $${r.cost_usd.toFixed(4)} (${r.calls})`).join('<br>');
  $('cost').innerHTML=
    kv('today','$'+today.toFixed(4))+kv('7-day avg','$'+avg.toFixed(4))+arrow+
    kv('total','$'+b.costs.total_usd.toFixed(4))+
    kv('cache hits',`${cache.hits||0} of ${(cache.hits||0)+(cache.misses||0)} · ${Math.round((cache.hit_rate||0)*100)}%`)+
    (byModel?'<div style="margin-top:6px;font-size:12px;color:var(--dim)">'+
      byModel+'</div>':'<div style="color:var(--dim);font-size:12px">'+
      'no spend recorded yet (local tier is free)</div>');
}catch(e){}}

async function refreshAdapters(){try{const a=await api('/api/adapters');
  const ping=a.ping||{};let h='';
  let checked='';
  if(ping.checked_at){
    const age=Math.max(0,(Date.now()-new Date(ping.checked_at).getTime())/1000);
    checked=` · probed ${age<60?Math.round(age)+'s':Math.round(age/60)+'m'} ago`;
  }
  for(const[name,p]of Object.entries(ping)){
    if(name==='checked_at')continue;
    const lat=p.latency_ms==null?'n/a':p.latency_ms+' ms';
    h+=kv(name,(p.ok===false?badge('b-err','down'):p.ok?badge('b-ok','ok'):badge('b-dim','skip'))+' '+lat);
  }
  const stats=a.stats||{};
  for(const[tier,st]of Object.entries(stats)){
    if(st.cooldown_active)h+=kv(tier+' breaker',
      badge('b-warn','cooldown '+st.cooldown_remaining_s+'s')+
      ' <span style="color:var(--dim);font-size:11px">'+
      esc(String(st.last_error||'').slice(0,60))+'</span>');
  }
  h+=`<div style="margin-top:4px;font-size:11px;color:var(--dim)">${esc(checked.trim())}</div>`;
  $('adapters').innerHTML=h||'<div style="color:var(--dim);font-size:12px">no adapters</div>';
}catch(e){}}

async function refreshBackup(){try{const b=await api('/api/backup');
  const items=b.archives||[];
  if(!items.length){$('backups').innerHTML=
    '<div style="color:var(--dim);font-size:12px">no backups found in '+
    esc(b.dir)+' — run python -m ops.backup create</div>';return}
  const newest=items[0];
  const age=newest.age_s<3600?Math.round(newest.age_s/60)+' min'
    :Math.round(newest.age_s/3600)+' h';
  const rows=items.slice(0,5).map(a=>
    `${esc(a.name)} · ${(a.bytes/1024).toFixed(0)} KB`+
    (a.tag?` · ${esc(a.tag)}`:'')).join('<br>');
  $('backups').innerHTML=
    kv('newest',`${esc(newest.name)} (${age} old)`)+
    (newest.tag?kv('tag',esc(newest.tag)):'')+
    '<div style="margin-top:6px;font-size:12px;color:var(--dim)">'+rows+'</div>';
}catch(e){}}

const log=$('log');const lines=[];
const swarmFeed=$('swarm');const swarmEvents=[];
const es=new EventSource('/api/stream');
es.onmessage=ev=>{try{const d=JSON.parse(ev.data);
  if(d.log){lines.push(d.log);if(lines.length>400)lines.shift();
    log.textContent=lines.join('\\n');log.scrollTop=log.scrollHeight}
  if(d.swarm){const e=d.swarm;
    swarmEvents.push(e);if(swarmEvents.length>60)swarmEvents.shift();
    swarmFeed.innerHTML=swarmEvents.map(x=>`<div style="padding:2px 0;border-bottom:1px solid var(--border)">
      ${badge('b-dim',esc(x.stage))} ${esc(x.detail||'')}
      ${x.round!=null?badge('b-warn',`round ${x.round}/${x.rounds??'?'}`):''}
      ${x.voter!=null?badge('b-warn',`voter ${x.voter}/${x.voters??'?'}`):''}</div>`).join('');
    swarmFeed.scrollTop=swarmFeed.scrollHeight}}catch(e){}};
async function refreshTopologies(){try{const data=await api('/api/swarm');
  $('topologies').innerHTML=data.topologies.map(t=>`<details style="margin:4px 0">
    <summary>${esc(t.name)}</summary>
    <p style="margin:6px 0;color:var(--dim)">${esc(t.description)}</p>
    <pre style="white-space:pre-wrap;margin:0">${esc(t.mermaid)}</pre></details>`).join('');
}catch(e){$('topologies').innerHTML=`<span style="color:var(--dim)">${esc(e.message)}</span>`}};
refreshStatus();refreshTasks();refreshSkills();refreshApprovals();
refreshQuarantine();refreshCost();refreshEpisodes();refreshTopologies();refreshBackup();refreshAdapters();
setInterval(refreshStatus,5000);setInterval(refreshTasks,5000);
setInterval(refreshSkills,15000);setInterval(refreshApprovals,5000);
setInterval(refreshQuarantine,15000);setInterval(refreshCost,10000);
setInterval(refreshBackup,60000);setInterval(refreshAdapters,15000);
setInterval(refreshEpisodes,10000);
</script></body></html>"""


def build_web_app(daemon) -> web.Application:
    app = web.Application(client_max_size=256 * 1024)
    app["daemon"] = daemon
    app.middlewares.append(_auth_middleware)

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=_DASHBOARD_HTML, content_type="text/html")

    async def api_status(request: web.Request) -> web.Response:
        payload = daemon.status()
        limiter = request.app.get("auth_limiter")
        if limiter is not None:
            # aggregate lockout state only — never per-client detail
            payload["auth"] = limiter.snapshot()
        return web.json_response(payload)

    async def api_backup(_request: web.Request) -> web.Response:
        """Backup window listing: newest archive, age, tag. Listing only —
        hash verification stays in `python -m ops.backup verify-all`."""
        from ops.backup import list_backups
        backup_dir = daemon.cfg.root / daemon.cfg.get(
            "ops.backup_dir", "backups")
        return web.json_response(list_backups(backup_dir))

    async def api_doc(request: web.Request) -> web.Response:
        """Read-only runbook/docs serving — allowlisted names only, so
        the dashboard can link the runbooks it references."""
        name = request.match_info["name"]
        allowed = {"runbook-backups", "runbook-dependencies",
                   "runbook-failover", "runbook-quarantine"}
        if name not in allowed:
            raise web.HTTPNotFound(text="unknown document")
        path = daemon.cfg.root / "docs" / f"{name}.md"
        if not path.is_file():
            raise web.HTTPNotFound(text=f"{name}.md not deployed")
        return web.Response(text=path.read_text(encoding="utf-8"),
                            content_type="text/plain")

    async def api_tasks(request: web.Request) -> web.Response:
        from kernel.pagination import paginate, parse_paging_params
        try:
            offset, limit = parse_paging_params(dict(request.query))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        status = request.query.get("status")
        if status is not None and status not in ("pending", "running",
                                                 "done", "failed",
                                                 "cancelled"):
            raise web.HTTPBadRequest(
                text="status must be one of pending, running, done, "
                     "failed, cancelled")
        tasks = await daemon.memory.list_tasks(limit=offset + limit + 1,
                                               status=status)
        blocked = {t["id"]: t["blocked_by"] for t in
                   await daemon.memory.blocked_pending_tasks(limit=100)}
        for row in tasks:
            if row["id"] in blocked:
                row["blocked_by"] = blocked[row["id"]]
        return web.json_response(paginate(tasks, offset, limit).envelope())

    async def api_task_detail(request: web.Request) -> web.Response:
        try:
            task_id = int(request.match_info["id"])
        except ValueError as exc:
            raise web.HTTPBadRequest(text="task id must be an integer") \
                from exc
        rows = await daemon.memory.list_tasks(task_id=task_id)
        if not rows:
            raise web.HTTPNotFound(text=f"no task {task_id}")
        detail = rows[0]
        detail["blocked_by"] = await daemon.memory.blocked_by(task_id)
        return web.json_response(detail)

    async def api_tasks_create(request: web.Request) -> web.Response:
        body = await request.json()
        goal = str(body.get("goal", "")).strip()
        if not goal:
            raise web.HTTPBadRequest(text="goal is required")
        interval = body.get("interval_seconds")
        depends_on = body.get("depends_on")
        if depends_on is not None:
            if (not isinstance(depends_on, list)
                    or not all(isinstance(d, int) and d > 0
                               for d in depends_on)):
                raise web.HTTPBadRequest(
                    text="depends_on must be a list of positive task ids")
        try:
            if interval is not None:
                interval = int(interval)
                if interval < 60:
                    raise web.HTTPBadRequest(
                        text="interval_seconds must be >= 60")
                task_id = await daemon.submit_task(goal, source="operator",
                                                   interval_seconds=interval,
                                                   depends_on=depends_on)
            else:
                task_id = await daemon.submit_task(goal, source="operator",
                                                   depends_on=depends_on)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response({"id": task_id}, status=201)

    async def api_task_action(request: web.Request) -> web.Response:
        task_id = int(request.match_info["id"])
        action = request.match_info["action"]
        if action == "cancel":
            ok = await daemon.memory.cancel_task(task_id)
        elif action == "pause":
            ok = await daemon.memory.pause_resume(task_id, enabled=False)
        elif action == "resume":
            ok = await daemon.memory.pause_resume(task_id, enabled=True)
        else:
            raise web.HTTPNotFound
        if not ok:
            raise web.HTTPBadRequest(text=f"could not {action} task {task_id}")
        if action in ("pause", "resume"):
            daemon.bus.publish("scheduler", {
                "event": {"pause": "task_paused",
                          "resume": "task_resumed"}[action],
                "task_id": task_id})
        return web.json_response({"ok": True})

    async def api_episodes(request: web.Request) -> web.Response:
        from kernel.pagination import paginate, parse_paging_params
        try:
            offset, limit = parse_paging_params(dict(request.query))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        episodes = await daemon.memory.recent_episodes(
            limit=offset + limit + 1,
            tag=request.query.get("tag"))
        return web.json_response(paginate(episodes, offset, limit).envelope())

    async def api_episode_detail(request: web.Request) -> web.Response:
        try:
            episode_id = int(request.match_info["id"])
        except ValueError:
            raise web.HTTPBadRequest(text="episode id must be an integer")
        detail = await daemon.memory.episode_detail(episode_id)
        if detail is None:
            raise web.HTTPNotFound(text=f"no episode {episode_id}")
        detail["final_answer"] = daemon.vault.redact(
            detail.get("final_answer") or "")
        detail["goal"] = daemon.vault.redact(detail.get("goal") or "")
        return web.json_response(detail)

    async def api_memories(request: web.Request) -> web.Response:
        query = request.query.get("q", "").strip()
        if not query:
            raise web.HTTPBadRequest(text="q is required")
        kinds = [k for k in request.query.get("kind", "").split(",")
                 if k] or None
        tag = request.query.get("tag") or None
        if tag:
            episodes = await daemon.memory.recent_episodes(limit=500,
                                                           tag=tag)
            keys = {f"episode:{e['id']}" for e in episodes}
            if not keys:
                return web.json_response([])
            hits = await daemon.memory.recall(query, k=8, kinds=kinds)
            hits = [h for h in hits if h.key in keys]
        else:
            hits = await daemon.memory.recall(query, k=8, kinds=kinds)
        return web.json_response([{"kind": h.kind, "key": h.key,
                                   "text": h.text, "score": round(h.score, 3),
                                   "created_at": h.created_at,
                                   "tags": h.tags or []} for h in hits])

    async def api_memory_forget(request: web.Request) -> web.Response:
        key = request.match_info["key"]
        removed = await daemon.memory.forget(key)
        await daemon.memory.audit("operator", "memory.forget",
                                  f"key={key[:100]} removed={removed}")
        if not removed:
            raise web.HTTPNotFound(text=f"no memory with key {key!r}")
        return web.json_response({"ok": True, "key": key})

    async def api_skills(_request: web.Request) -> web.Response:
        return web.json_response(daemon.forge.list_skills())

    async def api_skills_create(request: web.Request) -> web.Response:
        body = await request.json()
        try:
            result = daemon.forge.propose(
                str(body.get("name", "")), str(body.get("description", "")),
                body.get("parameters") or {}, str(body.get("code", "")),
                source="operator")
        except Exception as exc:  # noqa: BLE001 — surface validation errors
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response(result, status=201)

    async def api_skills_approve(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        try:
            result = daemon.forge.approve(name, source="operator")
        except Exception as exc:  # noqa: BLE001
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response(result)

    async def api_stream(request: web.Request) -> web.Response:
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"})
        await response.prepare(request)
        log_queue = daemon.bus.subscribe("logs")
        swarm_queue = daemon.bus.subscribe("swarm")
        sched_queue = daemon.bus.subscribe("scheduler")

        def _send(payload: dict) -> bytes:
            return (f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    ).encode("utf-8")

        log_t = asyncio.create_task(log_queue.get())
        swarm_t = asyncio.create_task(swarm_queue.get())
        sched_t = asyncio.create_task(sched_queue.get())
        try:
            while True:
                done, _ = await asyncio.wait({log_t, swarm_t, sched_t},
                                             timeout=15.0,
                                             return_when=asyncio.
                                             FIRST_COMPLETED)
                if not done:
                    await response.write(b": ping\n\n")
                    continue
                if log_t in done:
                    line = log_t.result()
                    await response.write(_send(
                        {"log": daemon.vault.redact(str(line))}))
                    log_t = asyncio.create_task(log_queue.get())
                if swarm_t in done:
                    event = swarm_t.result()
                    if isinstance(event, dict):
                        event = {key: daemon.vault.redact(str(value))
                                 if isinstance(value, str) else value
                                 for key, value in event.items()}
                    await response.write(_send({"swarm": event}))
                    swarm_t = asyncio.create_task(swarm_queue.get())
                if sched_t in done:
                    event = sched_t.result()
                    if isinstance(event, dict):
                        event = {key: daemon.vault.redact(str(value))
                                 if isinstance(value, str) else value
                                 for key, value in event.items()}
                    await response.write(_send({"scheduler": event}))
                    sched_t = asyncio.create_task(sched_queue.get())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            log_t.cancel()
            swarm_t.cancel()
            sched_t.cancel()
            daemon.bus.unsubscribe("logs", log_queue)
            daemon.bus.unsubscribe("swarm", swarm_queue)
            daemon.bus.unsubscribe("scheduler", sched_queue)
        return response

    app.router.add_get("/", index)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/backup", api_backup)
    app.router.add_get("/api/docs/{name}", api_doc)
    app.router.add_get("/api/tasks", api_tasks)
    app.router.add_get("/api/tasks/{id}", api_task_detail)
    app.router.add_post("/api/tasks", api_tasks_create)
    app.router.add_post("/api/tasks/{id}/{action}", api_task_action)
    app.router.add_get("/api/episodes", api_episodes)
    app.router.add_get("/api/episodes/{id}", api_episode_detail)
    app.router.add_get("/api/memories", api_memories)
    app.router.add_delete("/api/memories/{key}", api_memory_forget)
    app.router.add_get("/api/skills", api_skills)
    app.router.add_post("/api/skills", api_skills_create)
    app.router.add_post("/api/skills/{name}/approve", api_skills_approve)
    # --------------------------------------------------------------- v2 api
    async def api_health(_request: web.Request) -> web.Response:
        return web.json_response(await daemon.health.check_all())

    async def api_openapi(_request: web.Request) -> web.Response:
        from interface.openapi import build_spec
        return web.json_response(build_spec())

    async def api_metrics(_request: web.Request) -> web.Response:
        from interface.prom import render_text
        from kernel.metrics import REGISTRY
        return web.Response(text=render_text(REGISTRY),
                            content_type="text/plain")

    async def api_metrics_json(_request: web.Request) -> web.Response:
        from kernel.metrics import REGISTRY
        payload = REGISTRY.snapshot()
        payload["uptime_s"] = int(time.time() - daemon.started_at)
        return web.json_response(payload)

    async def api_swarm(_request: web.Request) -> web.Response:
        from swarm.render import topology_catalog
        return web.json_response({"topologies": topology_catalog()})

    async def api_db(request: web.Request) -> web.Response:
        """Read-only database lookups — same guard path as the
        sqlite_query tool (fixed statements, Python-side filtering)."""
        from tools.sqlite_query import lookup
        from kernel.errors import ToolFailure
        table = request.match_info["table"]
        where = {}
        for pair in request.query.getall("where", []):
            column, _, value = pair.partition("=")
            if not _:
                raise web.HTTPBadRequest(
                    text="where terms look like col=value")
            where[column] = value
        columns = [c for c in request.query.get("columns", "").split(",")
                   if c] or None
        order_by = request.query.get("order_by") or None
        descending = request.query.get("descending", "") in ("1", "true")
        try:
            limit = int(request.query.get("limit", 20))
            return web.json_response(await lookup(
                daemon.cfg.db_path, table, columns=columns, where=where,
                order_by=order_by, descending=descending, limit=limit))
        except (ValueError, ToolFailure) as exc:
            raise web.HTTPBadRequest(text=str(exc))

    async def api_approvals(_request: web.Request) -> web.Response:
        from security.approval import request_to_dict
        return web.json_response(
            {"pending": [request_to_dict(r)
                         for r in daemon.approvals.pending()],
             "recent": [request_to_dict(r)
                        for r in daemon.approvals.recent(limit=30)]})

    async def api_approval_decide(request: web.Request) -> web.Response:
        approval_id = request.match_info["id"]
        decision = request.match_info["decision"]
        if decision not in ("approve", "deny"):
            raise web.HTTPNotFound
        try:
            if decision == "approve":
                request_obj = daemon.approvals.approve(approval_id)
            else:
                request_obj = daemon.approvals.deny(approval_id)
        except (KeyError, ValueError) as exc:
            raise web.HTTPBadRequest(text=str(exc))
        await daemon.memory.audit("operator", f"approval.{decision}",
                                  f"{approval_id} {request_obj.kind}: "
                                  f"{request_obj.summary[:120]}")
        return web.json_response({"id": approval_id,
                                  "status": request_obj.status})

    async def api_quarantine(request: web.Request) -> web.Response:
        reason = request.query.get("reason") or None
        return web.json_response({"items": daemon.quarantine.list(
            limit=100, reason_contains=reason)})

    async def api_quarantine_item(request: web.Request) -> web.Response:
        try:
            item = daemon.quarantine.get(request.match_info["id"])
        except KeyError as exc:
            raise web.HTTPNotFound(text=str(exc))
        return web.json_response(item)

    async def api_quarantine_action(request: web.Request) -> web.Response:
        item_id = request.match_info["id"]
        action = request.match_info["action"]
        if action == "release":
            try:
                content = daemon.quarantine.release(item_id)
            except KeyError as exc:
                raise web.HTTPNotFound(text=str(exc))
            await daemon.memory.audit("operator", "quarantine.release",
                                      item_id)
            return web.json_response(
                {"id": item_id, "released": content[:500]})
        if action == "restore":
            return await _quarantine_restore(item_id)
        if action == "delete":
            if not daemon.quarantine.delete(item_id):
                raise web.HTTPNotFound(text=f"no item {item_id}")
            await daemon.memory.audit("operator", "quarantine.delete",
                                      item_id)
            return web.json_response({"id": item_id, "deleted": True})
        raise web.HTTPNotFound

    async def _quarantine_restore(item_id: str) -> web.Response:
        """Two-step restore: submit an approval, then release once an
        operator has approved it. Direct release stays available for
        operators who have already decided."""
        from security.approval import APPROVED, PENDING
        try:
            daemon.quarantine.get(item_id)
        except KeyError as exc:
            raise web.HTTPNotFound(text=str(exc))
        existing = None
        for req in daemon.approvals.recent(limit=200):
            if (req.kind == "quarantine_restore"
                    and req.detail.get("item_id") == item_id):
                existing = req
                break
        if existing is None or existing.status not in (PENDING, APPROVED):
            req = daemon.approvals.submit(
                kind="quarantine_restore",
                summary=f"restore quarantined item {item_id}",
                detail={"item_id": item_id}, requested_by="operator")
            await daemon.memory.audit("operator", "quarantine.restore.request",
                                      item_id)
            return web.json_response({"id": item_id,
                                      "status": "pending_approval",
                                      "approval_id": req.id})
        if existing.status == PENDING:
            return web.json_response({"id": item_id,
                                      "status": "pending_approval",
                                      "approval_id": existing.id})
        content = daemon.quarantine.release(item_id)
        await daemon.memory.audit("operator", "quarantine.restore",
                                  f"{item_id} via approval "
                                  f"{existing.id} ({existing.decided_by})")
        return web.json_response({"id": item_id, "status": "restored",
                                  "released": content[:500]})

    app.router.add_get("/api/health", api_health)
    app.router.add_get("/api/openapi.json", api_openapi)
    app.router.add_get("/metrics", api_metrics)
    app.router.add_get("/api/metrics", api_metrics_json)
    app.router.add_get("/api/swarm", api_swarm)
    app.router.add_get("/api/db/{table}", api_db)
    app.router.add_get("/api/approvals", api_approvals)
    app.router.add_post("/api/approvals/{id}/{decision}",
                        api_approval_decide)
    app.router.add_get("/api/quarantine", api_quarantine)
    app.router.add_get("/api/quarantine/{id}", api_quarantine_item)
    app.router.add_post("/api/quarantine/{id}/{action}",
                        api_quarantine_action)
    async def api_audit(request: web.Request) -> web.Response:
        from kernel.pagination import paginate, parse_paging_params
        try:
            offset, limit = parse_paging_params(dict(request.query))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        rows = await daemon.memory.recent_audit(limit=offset + limit + 1)
        for row in rows:
            if row.get("detail"):
                row["detail"] = daemon.vault.redact(row["detail"])[:300]
        return web.json_response(paginate(rows, offset, limit).envelope())

    async def api_version(_request: web.Request) -> web.Response:
        import kernel
        return web.json_response({"version": kernel.__version__,
                                  "api": "v2",
                                  "python": __import__("platform")
                                  .python_version()})

    async def api_brain(_request: web.Request) -> web.Response:
        from kernel.metrics import REGISTRY
        health = await daemon.brain.health()
        return web.json_response({
            "health": health,
            "tier_stats": daemon.brain.stats(),
            "lifecycle": {"shutdown_drained_tasks": int(
                REGISTRY.counter("shutdown_drained_tasks")),
                "started_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.localtime(daemon.started_at))},
            "cache": daemon.brain.cache_stats(),
            "cache_top_hits": daemon.brain.cache.top_hits(limit=5),
            "costs": daemon.costs.report(),
            "costs_last_7_days": daemon.costs.recent_days(7),
            "budget": {"today_usd": daemon.costs.today_total()},

        })

    async def api_adapters(_request: web.Request) -> web.Response:
        from brain.adapters import adapter_registry
        health = await daemon.brain.health()
        # one latency sample per builtin adapter (mock + whatever the
        # config sections can construct); probes never raise. A probe
        # can be opted out per adapter via interface.ping_skip
        skip = set(daemon.cfg.get("interface.ping_skip", []) or [])
        sections = {"mock": {},
                    "ollama": dict(daemon.cfg.section("brain.local")),
                    "openai_compat": dict(daemon.cfg.section("brain.remote"))}
        pings = {}
        for name, section in sections.items():
            if name in skip:
                pings[name] = {"ok": None, "detail": "skipped by config",
                               "latency_ms": None}
                continue
            try:
                pings[name] = await adapter_registry.ping(name, section,
                                                          daemon.vault)
            except Exception as exc:   # noqa: BLE001 — probes never raise
                pings[name] = {"ok": False,
                               "detail": f"{type(exc).__name__}: {exc}",
                               "latency_ms": None}
        return web.json_response({
            "tiers": health,
            "stats": daemon.brain.tier_details(),
            "cache": daemon.brain.cache_stats(),
            "ping": {**pings, "checked_at": time.strftime(
                "%Y-%m-%dT%H:%M:%S")},
            "catalog": {"available": adapter_registry.available()},
        })

    async def api_tools(_request: web.Request) -> web.Response:
        specs = daemon.registry.specs()
        return web.json_response({
            "count": len(specs),
            "tools": [{"name": s["name"], "description": s["description"],
                       "parameters": s["parameters"],
                       "dangerous": s["dangerous"],
                       "source": s["source"]} for s in specs]})

    app.router.add_get("/api/tools", api_tools)
    app.router.add_get("/api/audit", api_audit)
    app.router.add_get("/api/version", api_version)
    app.router.add_get("/api/brain", api_brain)
    app.router.add_get("/api/adapters", api_adapters)
    async def api_websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=15)
        await ws.prepare(request)
        log_queue = daemon.bus.subscribe("logs")
        swarm_queue = daemon.bus.subscribe("swarm")
        sched_queue = daemon.bus.subscribe("scheduler")

        async def forward_logs() -> None:
            while True:
                line = await log_queue.get()
                await ws.send_json({"log": daemon.vault.redact(str(line))})

        async def forward_swarm() -> None:
            while True:
                event = await swarm_queue.get()
                if isinstance(event, dict):
                    event = {key: daemon.vault.redact(str(value))
                             if isinstance(value, str) else value
                             for key, value in event.items()}
                await ws.send_json({"swarm": event})

        async def forward_scheduler() -> None:
            while True:
                event = await sched_queue.get()
                if isinstance(event, dict):
                    event = {key: daemon.vault.redact(str(value))
                             if isinstance(value, str) else value
                             for key, value in event.items()}
                await ws.send_json({"scheduler": event})

        sender = asyncio.create_task(forward_logs())
        swarm_sender = asyncio.create_task(forward_swarm())
        sched_sender = asyncio.create_task(forward_scheduler())
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == "ping":
                        await ws.send_json({"type": "pong"})
                    elif msg.data == "snapshot":
                        await ws.send_json({"type": "status",
                                            "data": daemon.status()})
                elif msg.type in (aiohttp.WSMsgType.ERROR,
                                  aiohttp.WSMsgType.CLOSE):
                    break
        finally:
            sender.cancel()
            swarm_sender.cancel()
            sched_sender.cancel()
            daemon.bus.unsubscribe("logs", log_queue)
            daemon.bus.unsubscribe("swarm", swarm_queue)
            daemon.bus.unsubscribe("scheduler", sched_queue)
            if not ws.closed:
                await ws.close()
        return ws

    app.router.add_get("/api/stream", api_stream)
    import aiohttp as _aiohttp_mod  # noqa: F401 — aiohttp imported above
    app.router.add_get("/ws", api_websocket)
    return app


@web.middleware
async def _auth_middleware(request: web.Request, handler):
    daemon = request.app["daemon"]
    expected = daemon.vault.get("SPARKAGENT_WEB_TOKEN")
    if expected and request.path.startswith("/api"):
        limiter = request.app.setdefault(
            "auth_limiter", AuthRateLimiter())
        client = request.remote or "unknown"
        if not limiter.allowed(client):
            return web.json_response(
                {"error": "too many failed auth attempts"},
                status=429, headers={
                    "Retry-After": str(int(limiter.retry_after(client)) + 1)})
        provided = request.headers.get("Authorization", "")
        token = provided[7:] if provided.startswith("Bearer ") else \
            request.query.get("token", "")
        if token != expected:
            limiter.record_failure(client)
            return web.json_response({"error": "unauthorized"}, status=401)
        limiter.record_success(client)
    return await handler(request)
