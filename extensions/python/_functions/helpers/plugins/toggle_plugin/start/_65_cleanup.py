from helpers.extension import Extension
from usr.plugins.code_intelligence.helpers.service import shutdown


class Cleanup(Extension):
    def execute(self, data=None, **kwargs):
        payload = data or {}
        args = payload.get("args", ())
        kw = payload.get("kwargs", {})
        name = kw.get("plugin_name", kw.get("plugin_names", args[0] if args else None))
        if name is None or name == "code_intelligence" or (isinstance(name, list) and "code_intelligence" in name):
            shutdown()
