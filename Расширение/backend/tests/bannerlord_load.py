"""
bannerlord_load.py — concurrent streamers load test.

Sprint 5.33 LOAD-1 (2026-05-28): friend feedback —
"Надо бы потестить что будет если 10-100 стримеров будут дёргать запросы и
апдейты". Симулирует N "virtual streamers" каждый со своими viewers, дёргает
realistic action mix на backend.

Запуск:
    cd Расширение/backend
    python tests/bannerlord_load.py --streamers 10 --duration 30 --host http://localhost:8000
    python tests/bannerlord_load.py --streamers 100 --duration 60   # stress test

Workload mix per streamer (per second average):
    - 3× GET state queries (frontend polls — heroes, workshops, fiefs)
    - 1× POST event (mod sync event — workshop_profit, fief_tribute, etc.)
    - 0.5× GET module/actions long-poll (mod polling)
  Note: real campaign имеет более sporadic actions; этот mix больше "worst case
  steady polling" чем typical usage. Если backend handles это на N=100 — OK.

Output (per test run):
    - Total requests, errors, error rate
    - Per-endpoint counts + p50/p95/p99 latency
    - Throughput (req/sec)
    - Wall time

DOES NOT require module_token — uses GET endpoints без auth (auth-failure path
тоже a valid load — backend проверяет JWT и быстро отказывает). Это тестирует
backend's hot path: request parsing + auth check + ранний return.

Для полного load (с реальными writes): set --module-token TOKEN env, script
запушит POST events. Без token POST'ы пропускаются.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
import uuid
from collections import defaultdict
from urllib import request as urlreq, error as urlerr

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Workload definitions
# ─────────────────────────────────────────────────────────────────────────────
# (path, method, weight). Weight = relative frequency.
# Without module_token POSTs return 401 — still valid latency measurement.
WORKLOAD = [
    ("GET",  "/api/bannerlord/my-hero",         3.0),
    ("GET",  "/api/bannerlord/my-workshops",    1.5),
    ("GET",  "/api/bannerlord/my-fiefs",        1.5),
    ("GET",  "/api/bannerlord/my-caravans",     1.0),
    ("GET",  "/api/bannerlord/party-orders",    0.8),
    ("GET",  "/api/bannerlord/kingdom-state",   0.8),
    ("GET",  "/api/bannerlord/ransom-pool",     0.5),
    ("GET",  "/api/bannerlord/caravan-rescues", 0.5),
    ("GET",  "/api/bannerlord/inheritance-log", 0.3),
    ("GET",  "/api/bannerlord/ping",            0.5),
    # POST event push (если token доступен)
    ("POST", "/v1/module/bannerlord/events",    1.5),
    # GET long-poll actions
    ("GET",  "/v1/module/bannerlord/actions",   0.5),
]

# Per-request payload templates for POST.
EVENT_PAYLOAD_VARIANTS = [
    lambda owner: {
        "type": "hero.workshop_profit_sync",
        "data": {"owner": owner, "settlement_id": "town_V1",
                 "workshop_type": "smithy", "net_dinars": 300},
    },
    lambda owner: {
        "type": "hero.fief_tribute_sync",
        "data": {"owner": owner, "fief_id": "town_V2",
                 "fief_name": "Sargot", "fief_type": "town",
                 "net_dinars": 500},
    },
    lambda owner: {
        "type": "player.state_update",
        "data": {"username": owner, "hero_id": f"mock_h_{owner}",
                 "gold": random.randint(1000, 50000),
                 "level": random.randint(1, 30)},
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Stats collection
# ─────────────────────────────────────────────────────────────────────────────
class Stats:
    def __init__(self):
        self.requests = 0
        self.errors = 0
        self.per_endpoint: dict[str, list[float]] = defaultdict(list)
        self.per_endpoint_errors: dict[str, int] = defaultdict(int)
        self.status_codes: dict[int, int] = defaultdict(int)

    def add(self, endpoint: str, latency_ms: float, status: int, error: bool):
        self.requests += 1
        if error:
            self.errors += 1
            self.per_endpoint_errors[endpoint] += 1
        else:
            self.per_endpoint[endpoint].append(latency_ms)
        self.status_codes[status] += 1


# ─────────────────────────────────────────────────────────────────────────────
# HTTP request (blocking, wrapped in to_thread)
# ─────────────────────────────────────────────────────────────────────────────
def _http_request_sync(url: str, method: str, body: bytes | None,
                        headers: dict, timeout: float) -> tuple[int, float, bool]:
    """Returns (status, latency_ms, errored). Errored=True если timeout/network."""
    t0 = time.perf_counter()
    req = urlreq.Request(url, data=body, method=method, headers=headers)
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            _ = resp.read(8192)
            lat_ms = (time.perf_counter() - t0) * 1000.0
            return resp.status, lat_ms, False
    except urlerr.HTTPError as he:
        lat_ms = (time.perf_counter() - t0) * 1000.0
        return he.code, lat_ms, False  # not a transport error, valid measurement
    except Exception:
        lat_ms = (time.perf_counter() - t0) * 1000.0
        return 0, lat_ms, True


async def http_request(url: str, method: str, body: bytes | None,
                        headers: dict, timeout: float) -> tuple[int, float, bool]:
    return await asyncio.to_thread(_http_request_sync, url, method, body, headers, timeout)


# ─────────────────────────────────────────────────────────────────────────────
# Worker — emulates 1 streamer's traffic
# ─────────────────────────────────────────────────────────────────────────────
async def streamer_worker(streamer_idx: int, host: str, module_token: str | None,
                          stats: Stats, stop_at: float, rng: random.Random):
    """Simulates 1 virtual streamer pushing events + frontend polling."""
    channel_id = streamer_idx + 1   # virtual ID — backend will reject (no real channel)
    viewer_name = f"load_viewer_{streamer_idx}"

    # Weight-table for random workload sampling.
    total_weight = sum(w for _, _, w in WORKLOAD)

    while time.time() < stop_at:
        # Sample workload entry.
        r = rng.uniform(0, total_weight)
        cum = 0.0
        chosen = WORKLOAD[0]
        for entry in WORKLOAD:
            cum += entry[2]
            if r <= cum:
                chosen = entry
                break
        method, path, _ = chosen
        url = f"{host}{path}"
        headers = {"User-Agent": "bannerlord-load/1.0"}
        body: bytes | None = None

        if method == "POST" and path.endswith("/events"):
            if not module_token:
                # Skip if no token — would just return 401 over and over.
                await asyncio.sleep(0.5)
                continue
            payload_fn = rng.choice(EVENT_PAYLOAD_VARIANTS)
            evt = payload_fn(viewer_name)
            envelope = {
                "channel_id": channel_id,
                "envelopes": [{
                    "id":   uuid.uuid4().hex,
                    "kind": "event",
                    "type": evt["type"],
                    "ts":   int(time.time() * 1000),
                    "data": evt["data"],
                }],
            }
            body = json.dumps(envelope).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Authorization"] = f"Bearer {module_token}"
        elif method == "GET" and "/module/" in path and "actions" in path:
            # Long-poll — лимит short timeout чтобы не блокировать worker
            if module_token:
                headers["Authorization"] = f"Bearer {module_token}"
            # Add since=0 query param.
            url += "?since=0"
        else:
            # GET state — no auth → backend returns auth-required (200 + success:false).
            # Still exercises route handler + JWT validation hot path.
            pass

        status, lat_ms, errored = await http_request(url, method, body, headers,
                                                       timeout=30.0)
        # Identify endpoint key — strip query string + path params.
        endpoint = f"{method} {path}"
        stats.add(endpoint, lat_ms, status, errored)

        # Throttle: typical streamer не насилует backend каждые 0.01s.
        # ~1-2 req/sec per worker = realistic.
        await asyncio.sleep(rng.uniform(0.3, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────
def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100.0)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def print_report(stats: Stats, duration_s: float, streamers: int):
    print(f"\n{'='*72}")
    print(f"LOAD TEST RESULTS")
    print(f"{'='*72}")
    print(f"Streamers:    {streamers}")
    print(f"Duration:     {duration_s:.1f}s")
    print(f"Requests:     {stats.requests}")
    print(f"Errors:       {stats.errors}  ({100 * stats.errors / max(1, stats.requests):.1f}%)")
    print(f"Throughput:   {stats.requests / duration_s:.1f} req/sec total, "
          f"{stats.requests / duration_s / streamers:.2f} req/sec/streamer")

    print(f"\nStatus codes:")
    for code in sorted(stats.status_codes.keys()):
        print(f"  {code}: {stats.status_codes[code]}")

    print(f"\nPer-endpoint latency (ms) — only successful requests:")
    print(f"  {'endpoint':<50}{'count':>7}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>9}")
    for endpoint in sorted(stats.per_endpoint.keys()):
        lats = stats.per_endpoint[endpoint]
        if not lats:
            continue
        p50 = percentile(lats, 50)
        p95 = percentile(lats, 95)
        p99 = percentile(lats, 99)
        mx = max(lats)
        err_count = stats.per_endpoint_errors.get(endpoint, 0)
        suffix = f" (+{err_count} err)" if err_count else ""
        print(f"  {endpoint:<50}{len(lats):>7}{p50:>8.1f}{p95:>8.1f}{p99:>8.1f}{mx:>9.1f}{suffix}")

    # Sanity check thresholds.
    print(f"\n{'='*72}")
    p95_all: list[float] = []
    for lats in stats.per_endpoint.values():
        p95_all.append(percentile(lats, 95))
    if p95_all:
        avg_p95 = statistics.mean(p95_all)
        if avg_p95 > 500:
            print(f"⚠ WARNING: avg p95 latency = {avg_p95:.0f}ms — backend struggling")
        elif avg_p95 > 200:
            print(f"⚠ avg p95 latency = {avg_p95:.0f}ms — acceptable но close к ceiling")
        else:
            print(f"✅ avg p95 latency = {avg_p95:.0f}ms — healthy")
    err_rate = 100 * stats.errors / max(1, stats.requests)
    if err_rate > 5:
        print(f"❌ ERROR rate {err_rate:.1f}% — backend dropping requests")
    elif err_rate > 1:
        print(f"⚠ ERROR rate {err_rate:.1f}% — investigate")
    else:
        print(f"✅ ERROR rate {err_rate:.2f}% — within tolerance")
    print(f"{'='*72}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def main_async(host: str, streamers: int, duration: float,
                      module_token: str | None):
    print(f"\n{'='*72}")
    print(f"Starting load test")
    print(f"  Host:       {host}")
    print(f"  Streamers:  {streamers}")
    print(f"  Duration:   {duration}s")
    print(f"  Token:      {'set' if module_token else 'NOT SET (POSTs skipped)'}")
    print(f"{'='*72}\n")

    # Verify backend reachable.
    print("Pinging backend...")
    s, lat, err = await http_request(f"{host}/api/bannerlord/ping", "GET",
                                        None, {}, timeout=10.0)
    if err or s == 0:
        print(f"❌ Backend unreachable: status={s}, error flag={err}")
        sys.exit(2)
    print(f"  ✅ Backend responds в {lat:.1f}ms\n")

    stats = Stats()
    rng = random.Random(42)   # determined for reproducibility
    stop_at = time.time() + duration

    print(f"Spawning {streamers} virtual streamers...")
    workers = [
        asyncio.create_task(
            streamer_worker(i, host, module_token, stats, stop_at,
                             random.Random(rng.random()))
        )
        for i in range(streamers)
    ]
    t_start = time.time()
    await asyncio.gather(*workers, return_exceptions=True)
    elapsed = time.time() - t_start

    print_report(stats, elapsed, streamers)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://localhost:8000",
                        help="Backend base URL")
    parser.add_argument("--streamers", type=int, default=10,
                        help="Number of virtual streamers (default 10)")
    parser.add_argument("--duration", type=float, default=30.0,
                        help="Test duration в seconds (default 30)")
    parser.add_argument("--module-token", default=None,
                        help="Module bearer token для POST events (optional)")
    args = parser.parse_args()

    if args.streamers < 1 or args.streamers > 1000:
        print("--streamers должно быть 1-1000")
        sys.exit(2)
    if args.duration < 5:
        print("--duration минимум 5 секунд")
        sys.exit(2)

    asyncio.run(main_async(args.host, args.streamers, args.duration,
                            args.module_token))


if __name__ == "__main__":
    main()
