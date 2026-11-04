from pathlib import Path
import runpy

from usr.plugins.code_intelligence.helpers.service import shutdown
from usr.plugins.code_intelligence.helpers.setup import DATA


def preserve_recovery():
    if any((DATA / "recovery").glob("*/*.json")):
        raise RuntimeError("Resolve Code Intelligence recovery journals before updating or uninstalling; original files are preserved under " + str(DATA / "recovery"))


def install(force=False, **kwargs):
    shutdown()
    # Updates can retain imported helpers until after installation. Load setup
    # from the newly installed source, including its current pins and checks.
    setup = runpy.run_path(str(Path(__file__).parent / "helpers/setup.py"))
    return setup["setup_tools"](force=force)


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
