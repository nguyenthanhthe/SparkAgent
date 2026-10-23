"""Local web dashboard (aiohttp).

Serves a single-page dashboard and a JSON API:

    GET  /                     dashboard page
    GET  /api/status           daemon status (uptime, brain tiers, GPU, tasks)
    GET  /api/tasks            task list          POST /api/tasks  submit
    POST /api/tasks/{id}/cancel|pause|resume
    GET  /api/episodes         recent episodes
    GET  /api/memories?q=...   vector recall
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
<h1>&#9889; SparkAgent <span id="uptime">—</span></h1>
<div class="grid">
  <div class="card"><h2>Brain</h2><div id="brain"></div></div>
  <div class="card"><h2>GPU / System</h2><div id="system"></div></div>
  <div class="card"><h2>Scheduler</h2><div id="sched"></div></div>
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
<div class="card"><h2>Tasks</h2><div style="max-height:240px;overflow:auto"><table id="tasks"></table></div></div>
<div class="card"><h2>Skills</h2><div style="max-height:240px;overflow:auto"><table id="skills"></table></div></div>
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
    +kv('tools',s.tools?s.tools.length:0)
    +kv('skills pending',(s.skills_pending||[]).length);
}catch(e){$('uptime').textContent='· offline'}}
async function refreshTasks(){try{const payload=await api('/api/tasks');
  const tasks=payload.items||[];
  $('tasks').innerHTML='<tr><th>#</th><th>goal</th><th>status</th><th></th></tr>'+
   tasks.map(t=>`<tr><td>${t.id}</td><td>${t.goal.slice(0,80)}</td>
    <td>${t.enabled?t.status:badge('b-dim',t.status)}</td>
    <td>${t.enabled?`<button class="small" onclick="cancelTask(${t.id})">cancel</button>`:''}</td></tr>`).join('');
}catch(e){}}
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
async function refreshQuarantine(){try{const data=await api('/api/quarantine');
  const items=data.items||[];
  $('quarantine').innerHTML='<tr><th>id</th><th>reason</th><th>size</th><th></th></tr>'+
   (items.length?items.map(q=>`<tr><td>${q.id.slice(0,8)}</td><td>${q.reason.slice(0,50)}</td>
     <td>${q.size_bytes}B</td>
     <td><button class="small" onclick="quar('${q.id}','release')">release</button>
         <button class="small" onclick="quar('${q.id}','delete')">delete</button></td></tr>`).join('')
    :'<tr><td colspan="4" style="color:var(--dim)">empty</td></tr>');
}catch(e){}}
async function quar(id,action){try{const r=await api(`/api/quarantine/${id}/${action}`,{method:'POST'});
  toast(action+'d');refreshQuarantine()}catch(e){toast(e.message)}}

const log=$('log');const lines=[];
const es=new EventSource('/api/stream');
es.onmessage=ev=>{try{const d=JSON.parse(ev.data);
  if(d.log){lines.push(d.log);if(lines.length>400)lines.shift();
    log.textContent=lines.join('\\n');log.scrollTop=log.scrollHeight}}catch(e){}};
refreshStatus();refreshTasks();refreshSkills();refreshApprovals();refreshQuarantine();
setInterval(refreshStatus,5000);setInterval(refreshTasks,5000);
setInterval(refreshSkills,15000);setInterval(refreshApprovals,5000);
setInterval(refreshQuarantine,15000);
</script></body></html>"""


def build_web_app(daemon) -> web.Application:
    app = web.Application(client_max_size=256 * 1024)
    app["daemon"] = daemon
    app.middlewares.append(_auth_middleware)

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=_DASHBOARD_HTML, content_type="text/html")

    async def api_status(_request: web.Request) -> web.Response:
        return web.json_response(daemon.status())

    async def api_tasks(request: web.Request) -> web.Response:
        from kernel.pagination import paginate, parse_paging_params
        try:
            offset, limit = parse_paging_params(dict(request.query))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        tasks = await daemon.memory.list_tasks(limit=offset + limit + 1)
        return web.json_response(paginate(tasks, offset, limit).envelope())

    async def api_tasks_create(request: web.Request) -> web.Response:
        body = await request.json()
        goal = str(body.get("goal", "")).strip()
        if not goal:
            raise web.HTTPBadRequest(text="goal is required")
        interval = body.get("interval_seconds")
        if interval is not None:
            interval = int(interval)
            if interval < 60:
                raise web.HTTPBadRequest(text="interval_seconds must be >= 60")
            task_id = await daemon.submit_task(goal, source="operator",
                                               interval_seconds=interval)
        else:
            task_id = await daemon.submit_task(goal, source="operator")
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
        return web.json_response({"ok": True})

    async def api_episodes(request: web.Request) -> web.Response:
        from kernel.pagination import paginate, parse_paging_params
        try:
            offset, limit = parse_paging_params(dict(request.query))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        episodes = await daemon.memory.recent_episodes(
            limit=offset + limit + 1)
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
        hits = await daemon.memory.recall(query, k=8)
        return web.json_response([{"kind": h.kind, "key": h.key,
                                   "text": h.text, "score": round(h.score, 3),
                                   "created_at": h.created_at} for h in hits])

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
        queue = daemon.bus.subscribe("logs")
        try:
            while True:
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=15.0)
                    payload = json.dumps({"log": daemon.vault.redact(str(line))},
                                         ensure_ascii=False)
                    await response.write(f"data: {payload}\n\n".encode("utf-8"))
                except asyncio.TimeoutError:
                    await response.write(b": ping\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            daemon.bus.unsubscribe("logs", queue)
        return response

    app.router.add_get("/", index)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/tasks", api_tasks)
    app.router.add_post("/api/tasks", api_tasks_create)
    app.router.add_post("/api/tasks/{id}/{action}", api_task_action)
    app.router.add_get("/api/episodes", api_episodes)
    app.router.add_get("/api/episodes/{id}", api_episode_detail)
    app.router.add_get("/api/memories", api_memories)
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
        from kernel.metrics import REGISTRY
        return web.Response(text=REGISTRY.render_text(),
                            content_type="text/plain")

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

    async def api_quarantine(_request: web.Request) -> web.Response:
        return web.json_response({"items": daemon.quarantine.list(limit=100)})

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
        if action == "delete":
            if not daemon.quarantine.delete(item_id):
                raise web.HTTPNotFound(text=f"no item {item_id}")
            await daemon.memory.audit("operator", "quarantine.delete",
                                      item_id)
            return web.json_response({"id": item_id, "deleted": True})
        raise web.HTTPNotFound

    app.router.add_get("/api/health", api_health)
    app.router.add_get("/api/openapi.json", api_openapi)
    app.router.add_get("/metrics", api_metrics)
    app.router.add_get("/api/approvals", api_approvals)
    app.router.add_post("/api/approvals/{id}/{decision}",
                        api_approval_decide)
    app.router.add_get("/api/quarantine", api_quarantine)
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
        health = await daemon.brain.health()
        return web.json_response({
            "health": health,
            "tier_stats": daemon.brain.stats(),
            "costs": daemon.costs.report(),
            "budget": {"today_usd": daemon.costs.today_total()},

        })

    app.router.add_get("/api/audit", api_audit)
    app.router.add_get("/api/version", api_version)
    app.router.add_get("/api/brain", api_brain)
    async def api_websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=15)
        await ws.prepare(request)
        queue = daemon.bus.subscribe("logs")

        async def forward_logs() -> None:
            while True:
                line = await queue.get()
                await ws.send_json({"log": daemon.vault.redact(str(line))})

        sender = asyncio.create_task(forward_logs())
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
            daemon.bus.unsubscribe("logs", queue)
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
        provided = request.headers.get("Authorization", "")
        token = provided[7:] if provided.startswith("Bearer ") else \
            request.query.get("token", "")
        if token != expected:
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)
