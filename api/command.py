import asyncio
from helpers.api import ApiHandler, Request
from usr.plugins.code_intelligence.helpers import access, service, setup


class Command(ApiHandler):
    async def process(self, input: dict, request: Request):
        agent = None
        try:
            context_id = input.get("context_id")
            if not isinstance(context_id, str) or not context_id:
                raise ValueError("Select a chat in the intended project")
            context = self.use_context(context_id, create_if_not_exists=False)
            if context is None:
                raise ValueError("Unknown chat context")
            agent = context.agent0
            operation = input.get("operation", "status")
            if operation in ("status", "grant", "setup", "close"):
                tool = "debug_launch" if input.get("kind") == "debug" else "code_inspect"
                scope = access.resolve(agent, tool, require_trust=False)
                if operation == "grant":
                    access.grant(scope, input.get("kind"), input.get("fingerprint"), input.get("enabled") is True)
                    await asyncio.to_thread(service.shutdown)
                elif operation == "setup":
                    if input.get("confirm") is not True:
                        raise ValueError("Explicit setup confirmation is required")
                    await asyncio.to_thread(service.shutdown)
                    await asyncio.to_thread(setup.setup_tools)
                    scope = access.resolve(agent, tool, require_trust=False)
                elif operation == "close":
                    await asyncio.to_thread(service.shutdown)
                result = {"scope": access.public(scope), "tools": setup.status()}
                if access.trusted(scope, "semantic"):
                    result["workspace"] = await service.dispatch(agent, "code_inspect", {"action": "status"})
                return {"ok": True, **access.masked(agent, result)}
            if operation != "tool" or input.get("tool") not in access.TOOLS:
                raise ValueError("Unknown operation")
            args = input.get("args", {})
            if not isinstance(args, dict):
                raise ValueError("Tool arguments must be an object")
            return {"ok": True, "result": await service.dispatch(agent, input["tool"], args)}
        except Exception as exc:
            error = str(exc)[:500]
            return {"ok": False, "error": access.masked(agent, error) if agent else error}
