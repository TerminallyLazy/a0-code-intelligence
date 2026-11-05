from pathlib import Path
import runpy

from usr.plugins.code_intelligence.helpers.service import shutdown
from usr.plugins.code_intelligence.helpers.setup import DATA


def preserve_recovery():
    if any((DATA / "recovery").glob("*/*.json")):
        raise RuntimeError("Resolve Code Intelligence recovery journals before updating or uninstalling; original files are preserved under " + str(DATA / "recovery"))


def install(force=False, refresh_modules=True, **kwargs):
    shutdown()
    # Updates can retain imported helpers until after installation. Load setup
    # from the newly installed source, including its current pins and checks.
    setup = runpy.run_path(str(Path(__file__).parent / "helpers/setup.py"))
    result = setup["setup_tools"](force=force)
    if refresh_modules:
        # The native Git updater clears caches without refreshing Python modules.
        # Release our stopped namespace so the next request imports updated code.
        from helpers import modules
        modules.purge_namespace("usr.plugins.code_intelligence")
    return result


def pre_update(**kwargs):
    shutdown()
    preserve_recovery()
    # Agent Zero otherwise reuses the hook cached before the Git update.
    from helpers import cache, plugins
    cache.remove(plugins.HOOKS_CACHE_AREA, "code_intelligence")
    return True


def uninstall(**kwargs):
    shutdown()
    preserve_recovery()
    return True
