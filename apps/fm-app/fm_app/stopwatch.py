import time


class Stopwatch:
    def __init__(self):
        self._last = time.perf_counter()

    def lap(self) -> float:
        """
        Return elapsed time in ms since the last lap() or reset().
        """
        now = time.perf_counter()
        delta_ms = (now - self._last) * 1000.0
        self._last = now
        return delta_ms

    def reset(self):
        """
        Reset the stopwatch so the next lap() starts fresh.
        """
        self._last = time.perf_counter()

# create ONE global stopwatch for the whole app
stopwatch = Stopwatch()