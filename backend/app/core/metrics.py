"""
Minimal Prometheus-format metrics, kept in process memory (Phase 16).

No client library: a counter and a histogram are a few lines each, and the text
format is simple. Each API process (and each worker) has its own numbers; a
Prometheus server scraping several processes adds them up. Labels are kept to
low-cardinality values (route TEMPLATES, never raw paths or ids).
"""
import math
import threading
from typing import Dict, List, Sequence, Tuple

LabelKey = Tuple[Tuple[str, str], ...]

DEFAULT_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)


def _key(labels: Dict[str, object]) -> LabelKey:
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _fmt_labels(key: LabelKey, extra: Sequence[Tuple[str, str]] = ()) -> str:
    pairs = list(key) + list(extra)
    if not pairs:
        return ""
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in pairs) + "}"


def _fmt_value(value: float) -> str:
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


class Counter:
    def __init__(self, name: str, help_text: str):
        self.name, self.help = name, help_text
        self._values: Dict[LabelKey, float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels) -> None:
        key = _key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **labels) -> float:
        return self._values.get(_key(labels), 0.0)

    def render(self) -> List[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            for key, value in sorted(self._values.items()):
                lines.append(f"{self.name}{_fmt_labels(key)} {_fmt_value(value)}")
        return lines

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


class Histogram:
    def __init__(self, name: str, help_text: str, buckets: Sequence[float] = DEFAULT_BUCKETS):
        self.name, self.help = name, help_text
        self.buckets = tuple(sorted(buckets))
        self._series: Dict[LabelKey, List[float]] = {}  # bucket counts..., sum, count
        self._lock = threading.Lock()

    def observe(self, value: float, **labels) -> None:
        key = _key(labels)
        with self._lock:
            series = self._series.setdefault(key, [0.0] * (len(self.buckets) + 2))
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    series[i] += 1
            series[-2] += value
            series[-1] += 1

    def count(self, **labels) -> float:
        series = self._series.get(_key(labels))
        return series[-1] if series else 0.0

    def render(self) -> List[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        with self._lock:
            for key, series in sorted(self._series.items()):
                for i, bound in enumerate(self.buckets):
                    lines.append(f"{self.name}_bucket{_fmt_labels(key, [('le', _fmt_value(bound))])} "
                                 f"{_fmt_value(series[i])}")
                lines.append(f"{self.name}_bucket{_fmt_labels(key, [('le', '+Inf')])} {_fmt_value(series[-1])}")
                lines.append(f"{self.name}_sum{_fmt_labels(key)} {_fmt_value(series[-2])}")
                lines.append(f"{self.name}_count{_fmt_labels(key)} {_fmt_value(series[-1])}")
        return lines

    def reset(self) -> None:
        with self._lock:
            self._series.clear()


def gauge_lines(name: str, help_text: str, samples: Sequence[Tuple[Dict[str, object], float]]) -> List[str]:
    """A gauge computed at scrape time (e.g. queue depth read from the database)."""
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    for labels, value in samples:
        lines.append(f"{name}{_fmt_labels(_key(labels))} {_fmt_value(value)}")
    return lines


HTTP_REQUESTS = Counter("kf_http_requests_total", "HTTP requests by method, route template and status")
HTTP_SECONDS = Histogram("kf_http_request_duration_seconds", "HTTP request latency by route template")
JOBS_FINISHED = Counter("kf_jobs_finished_total", "Background jobs finished by this process, by final status")
JOB_SECONDS = Histogram("kf_job_duration_seconds", "Background job run time")

ALL = (HTTP_REQUESTS, HTTP_SECONDS, JOBS_FINISHED, JOB_SECONDS)


def render_process_metrics() -> List[str]:
    lines: List[str] = []
    for metric in ALL:
        lines.extend(metric.render())
    return lines


def reset_all() -> None:
    for metric in ALL:
        metric.reset()
