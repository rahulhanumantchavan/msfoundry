"""Hard process deadlines with bounded output, not a security sandbox.

Only the immediate process is killed. Arbitrary plugin/CLI descendants are not
contained; trusted commands must not spawn detached descendants. Reader threads
only drain pipes: subprocess.wait implements the actual execution deadline.
"""

import subprocess
import tempfile
import threading
from pathlib import Path

MAX_OUTPUT_BYTES = 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


class OutputLimitError(ValueError):
    pass


def run_process(command: list[str], payload: bytes, timeout: float,
                *, env: dict | None = None) -> bytes:
    output = bytearray()
    overflow = threading.Event()
    with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stderr:
        stdin.write(payload)
        stdin.seek(0)
        process = subprocess.Popen(
            command, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=ROOT, env=env, shell=False,
        )

        def drain(pipe, is_stdout):
            retained = 0
            try:
                while chunk := pipe.read1(65536):
                    remaining = max(0, MAX_OUTPUT_BYTES - retained)
                    if is_stdout:
                        output.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            overflow.set()
                            process.kill()
                    else:
                        stderr.write(chunk[:remaining])
                    retained += min(len(chunk), remaining)
            except (OSError, ValueError):
                pass
            finally:
                pipe.close()

        threads = [threading.Thread(target=drain, args=(process.stdout, True), daemon=True),
                   threading.Thread(target=drain, args=(process.stderr, False), daemon=True)]
        for thread in threads:
            thread.start()
        try:
            process.wait(timeout=timeout)
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            for thread in threads:
                thread.join(timeout=0.2)
        if any(thread.is_alive() for thread in threads):
            raise ValueError("Process left output handles open")
        if overflow.is_set():
            raise OutputLimitError("Process output too large")
        if process.returncode:
            raise RuntimeError("Child process failed")
        return bytes(output)