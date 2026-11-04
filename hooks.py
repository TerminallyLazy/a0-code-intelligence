from usr.plugins.code_intelligence.helpers.service import shutdown
from usr.plugins.code_intelligence.helpers.setup import DATA


def preserve_recovery():
    if any((DATA / "recovery").glob("*/*.json")):
        raise RuntimeError("Resolve Code Intelligence recovery journals before updating or uninstalling; original files are preserved under " + str(DATA / "recovery"))


def install(**kwargs):
    # Setup is an explicit action in Code Intelligence; activation is side-effect free.
    return True


def pre_update(**kwargs):
    shutdown()
    preserve_recovery()
    return True


def uninstall(**kwargs):
    shutdown()
    preserve_recovery()
    return True
