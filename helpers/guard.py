"""Child-process custody. EOF on a private lease pipe also handles parent death."""
import os
import select
import signal
import subprocess
import sys
import time


def main():
    lease = int(sys.argv[1])
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    child = subprocess.Popen(sys.argv[2:], start_new_session=True, close_fds=True)
    try:
        while not stopping and child.poll() is None:
            readable, _, _ = select.select([lease], [], [], 0.25)
            if readable and not os.read(lease, 1):
                break
    finally:
        # Only this newly created process group is owned by this guard.
        for sig, delay in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 0)):
            try:
                os.killpg(child.pid, sig)
            except ProcessLookupError:
                break
            if delay:
                time.sleep(delay)
        child.wait()
        os.close(lease)
    return child.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
