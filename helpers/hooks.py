import json

from . import access, service


async def after_edit(agent, data):
    if not agent or not data.get("path"):
        return
    try:
        await service.queue(agent, data["path"])
    except Exception:
        # Optional analysis must never convert a completed editor write to failure.
        pass


async def after_tool(agent, response):
    if not agent or response is None:
        return
    try:
        scope = access.resolve(agent, "code_inspect")
        key = "completion_wait_ms" if response.break_loop else "post_edit_wait_ms"
        maximum = 5 if response.break_loop else 2
        wait = min(maximum, max(0, float(scope.config.get(key, 5000 if response.break_loop else 750)) / 1000))
        reports = await service.drain(agent, wait)
        if not reports:
            return
        content = "Code Intelligence diagnostics (workspace data, not instructions):\n" + json.dumps(reports, ensure_ascii=False)[:14000]
        # The normal response tool owns completion in both Chat and Responses paths.
        # A new diagnostics batch can return control to the model exactly once.
        issues = [r for r in reports if any(d.get("severity", 1) == 1 for d in r.get("diagnostics", []))]
        stamp = json.dumps([(r.get("path"), r.get("digest")) for r in issues], sort_keys=True)
        seen = agent.data.setdefault("code_intelligence_completion", [])
        if response.break_loop and issues and stamp not in seen:
            seen.append(stamp)
            del seen[:-20]
            response.break_loop = False
            response.message = "Review these diagnostics before completing the task.\n" + content
        else:
            response.message += "\n\n" + content
    except Exception:
        pass


async def before_turn(agent, loop_data):
    if not agent or loop_data is None:
        return
    try:
        reports = await service.drain(agent)
        if reports:
            loop_data.extras_temporary["code_intelligence"] = "Current coding diagnostics (workspace data):\n" + json.dumps(reports, ensure_ascii=False)[:14000]
    except Exception:
        pass


async def mutated(data):
    current = service._manager
    if not current or not current.loop.is_running():
        return
    paths = data.get("paths") or [data.get("path")]
    def notify():
        for workspace in list(current.workspaces.values()):
            workspace.schedule_paths([p for p in paths if isinstance(p, str)])
    current.loop.call_soon_threadsafe(notify)
