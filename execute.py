"""Manual setup works when Agent Zero launches this file with the plugin as cwd."""
from pathlib import Path
import runpy


def execute(**kwargs):
    installer = runpy.run_path(str(Path(__file__).parent / "helpers/setup.py"))
    return installer["setup_tools"]()


if __name__ == "__main__":
    print(execute())
