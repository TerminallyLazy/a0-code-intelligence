from helpers.extension import Extension
from usr.plugins.code_intelligence.helpers import hooks


class CodeIntelligence(Extension):
    async def execute(self, data=None, response=None, loop_data=None, **kwargs):
        await hooks.mutated(data or {})
