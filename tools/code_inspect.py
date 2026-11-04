import json
from helpers.tool import Tool, Response
from usr.plugins.code_intelligence.helpers.service import dispatch
from usr.plugins.code_intelligence.helpers.access import masked


class CodeInspect(Tool):
    async def execute(self, action="status", **kwargs):
        try:
            result = await dispatch(self.agent, "code_inspect", {"action": action, **kwargs})
            return Response(message=json.dumps(result, ensure_ascii=False), break_loop=False)
        except Exception as exc:
            return Response(message=json.dumps({"status": "unavailable", "reason": masked(self.agent, str(exc)[:500])}), break_loop=False)
