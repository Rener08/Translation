"""subprocess.run replacement that respects job cancellation."""
from __future__ import annotations

import subprocess
import time

from app.services.job_cancel_context import get_cancel_event


def run_subprocess_killable(
    command: list[str],
    *,
    subprocess_timeout: float | None = None,
    check: bool = False,
    capture_output: bool = False,
    **kwargs,
) -> subprocess.CompletedProcess:
    """
    Drop-in replacement for subprocess.run that kills the child process when
    the thread-local cancel_event is set (job cancelled or stage timed out).

    subprocess_timeout mirrors subprocess.run's timeout parameter.
    capture_output and check mirror their subprocess.run counterparts.
    """
    if capture_output:
        if "stdout" in kwargs or "stderr" in kwargs:
            raise ValueError("capture_output cannot be used with stdout or stderr")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

    cancel_event = get_cancel_event()
    proc = subprocess.Popen(command, **kwargs)
    start = time.monotonic()
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                proc.wait()
                raise subprocess.SubprocessError("Job cancelled — subprocess killed.")
            if subprocess_timeout is not None and (time.monotonic() - start) >= subprocess_timeout:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(command, subprocess_timeout)
            try:
                stdout, stderr = proc.communicate(timeout=0.5)
                result = subprocess.CompletedProcess(
                    args=command,
                    returncode=proc.returncode,
                    stdout=stdout,
                    stderr=stderr,
                )
                if check and result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode, command, result.stdout, result.stderr
                    )
                return result
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        proc.kill()
        proc.wait()
        raise
