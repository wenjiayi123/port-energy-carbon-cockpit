from __future__ import annotations

from collections import defaultdict
import json
import logging
import threading
import time
from typing import Any


access_logger = logging.getLogger("energy_carbon.access")
if not access_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False


class RequestMetrics:
    def __init__(self) -> None:
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, int], int] = defaultdict(int)
        self._duration_sum: dict[str, float] = defaultdict(float)
        self._duration_count: dict[str, int] = defaultdict(int)
        self._auth_denied = 0

    def observe(self, method: str, status_code: int, duration_seconds: float) -> None:
        with self._lock:
            self._requests[(method, status_code)] += 1
            self._duration_sum[method] += duration_seconds
            self._duration_count[method] += 1

    def observe_auth_denied(self) -> None:
        with self._lock:
            self._auth_denied += 1

    def render_prometheus(self) -> str:
        with self._lock:
            request_items = sorted(self._requests.items())
            duration_sum = dict(self._duration_sum)
            duration_count = dict(self._duration_count)
            auth_denied = self._auth_denied
        lines = [
            "# HELP energy_carbon_api_info API build information.",
            "# TYPE energy_carbon_api_info gauge",
            'energy_carbon_api_info{version="0.2.0"} 1',
            "# HELP energy_carbon_api_uptime_seconds Process uptime.",
            "# TYPE energy_carbon_api_uptime_seconds gauge",
            f"energy_carbon_api_uptime_seconds {time.time() - self.started_at:.6f}",
            "# HELP energy_carbon_http_requests_total HTTP requests by method and status.",
            "# TYPE energy_carbon_http_requests_total counter",
        ]
        lines.extend(
            f'energy_carbon_http_requests_total{{method="{method}",status="{status}"}} {count}'
            for (method, status), count in request_items
        )
        lines.extend([
            "# HELP energy_carbon_http_request_duration_seconds Request duration totals.",
            "# TYPE energy_carbon_http_request_duration_seconds summary",
        ])
        for method in sorted(duration_count):
            lines.append(
                f'energy_carbon_http_request_duration_seconds_sum{{method="{method}"}} '
                f"{duration_sum[method]:.6f}"
            )
            lines.append(
                f'energy_carbon_http_request_duration_seconds_count{{method="{method}"}} '
                f"{duration_count[method]}"
            )
        lines.extend([
            "# HELP energy_carbon_auth_denied_total Rejected authenticated operations.",
            "# TYPE energy_carbon_auth_denied_total counter",
            f"energy_carbon_auth_denied_total {auth_denied}",
        ])
        return "\n".join(lines) + "\n"


request_metrics = RequestMetrics()


def log_access(event: dict[str, Any]) -> None:
    access_logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
