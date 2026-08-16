"""
CrashInjector — deliberately kills the process after a named saga step completes.

Used in demo_1 and demo_2 to prove saga state survives a hard crash.
"""
import os
import signal
import sys


class CrashInjector:
    def __init__(self, crash_after_step: str | None):
        """
        crash_after_step — saga step name after which to kill the process.
                           e.g. "hold" kills after the hold step completes.
                           None disables the injector.
        """
        self.crash_after_step = crash_after_step

    def maybe_crash(self, completed_step: str) -> None:
        if self.crash_after_step and completed_step == self.crash_after_step:
            print(
                f"\n[CHAOS] Injecting crash after step '{completed_step}' — "
                "sending SIGTERM to self...\n"
            )
            sys.stdout.flush()
            os.kill(os.getpid(), signal.SIGTERM)
