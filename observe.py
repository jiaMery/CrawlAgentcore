"""Bedrock AgentCore Observability — 查询并展示爬虫 Agent 的 trace/span 数据.

用法:
    python observe.py              # 展示最近 1 小时的所有 spans
    python observe.py --hours 3    # 展示最近 3 小时
    python observe.py --traces     # 按 traceId 分组展示调用链
    python observe.py --live       # 持续监控新 span（每 10 秒刷新）
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone


def _ts_to_str(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _duration_ms(start_ns, end_ns) -> str:
    if start_ns and end_ns:
        ms = (end_ns - start_ns) / 1_000_000
        if ms < 1000:
            return f"{ms:.1f}ms"
        return f"{ms/1000:.2f}s"
    return "?"


def fetch_spans(logs_client, hours: float = 1.0, limit: int = 200) -> list[dict]:
    """从 CloudWatch aws/spans 拉取最近 N 小时的 span 事件."""
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(hours * 3600 * 1000)

    events = []
    try:
        # 尝试分页获取
        kwargs = dict(
            logGroupName="aws/spans",
            logStreamName="default",
            startTime=start_ms,
            endTime=now_ms,
            limit=limit,
            startFromHead=False,
        )
        resp = logs_client.get_log_events(**kwargs)
        events = resp.get("events", [])
    except logs_client.exceptions.ResourceNotFoundException:
        print("❌ 日志组 aws/spans 不存在，请先确认 X-Ray → CloudWatch 目标已开启")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 读取日志失败: {e}")
        sys.exit(1)

    spans = []
    for ev in events:
        try:
            data = json.loads(ev.get("message", "{}"))
            data["_timestamp_ms"] = ev.get("timestamp", 0)
            spans.append(data)
        except json.JSONDecodeError:
            pass
    return spans


def print_spans_table(spans: list[dict]) -> None:
    """打印 span 列表（表格格式）."""
    if not spans:
        print("📭 没有找到 span 数据")
        return

    print(f"\n{'时间':20} {'Span 名称':40} {'TraceID':18} {'耗时':10}")
    print("─" * 92)
    for sp in spans:
        ts = _ts_to_str(sp.get("_timestamp_ms", 0))
        name = sp.get("name", "unknown")[:38]
        trace_id = sp.get("traceId", "")[:16]
        dur = _duration_ms(sp.get("startTimeUnixNano"), sp.get("endTimeUnixNano"))
        print(f"{ts:20} {name:40} {trace_id:18} {dur:10}")
    print(f"\n共 {len(spans)} 条 span")


def print_traces(spans: list[dict]) -> None:
    """按 traceId 分组展示完整调用链."""
    if not spans:
        print("📭 没有找到 span 数据")
        return

    # 按 traceId 分组
    traces: dict[str, list[dict]] = {}
    for sp in spans:
        tid = sp.get("traceId", "unknown")
        traces.setdefault(tid, []).append(sp)

    # 按最早 span 时间排序
    sorted_traces = sorted(
        traces.items(),
        key=lambda kv: min(s.get("_timestamp_ms", 0) for s in kv[1]),
    )

    print(f"\n共找到 {len(sorted_traces)} 条 trace:\n")
    for trace_id, trace_spans in sorted_traces:
        # 找 root span（最长/最先开始的）
        root = sorted(trace_spans, key=lambda s: s.get("startTimeUnixNano", 0) or 0)[0]
        root_ts = _ts_to_str(root.get("_timestamp_ms", 0))
        total_dur = _duration_ms(
            min((s.get("startTimeUnixNano") or 0) for s in trace_spans),
            max((s.get("endTimeUnixNano") or 0) for s in trace_spans),
        )

        print(f"🔍 Trace: {trace_id[:32]}")
        print(f"   时间: {root_ts}  |  总耗时: {total_dur}  |  span数: {len(trace_spans)}")

        # 展示 span 树
        sorted_spans = sorted(
            trace_spans,
            key=lambda s: s.get("startTimeUnixNano") or s.get("_timestamp_ms", 0),
        )
        for sp in sorted_spans:
            name = sp.get("name", "unknown")
            dur = _duration_ms(sp.get("startTimeUnixNano"), sp.get("endTimeUnixNano"))
            attrs = sp.get("attributes", {})
            attr_str = ""
            for key in ("crawler.skill", "crawler.movies_count", "crawler.target",
                        "aws.local.service", "gen_ai.system"):
                if key in attrs:
                    attr_str += f" {key.split('.')[-1]}={attrs[key]}"
            print(f"   ├─ {name:<38} {dur:>10}  {attr_str}")
        print()


def live_monitor(logs_client, interval: int = 10) -> None:
    """持续监控新 span，每 interval 秒刷新一次."""
    print(f"📡 实时监控 aws/spans（每 {interval}s 刷新，Ctrl+C 退出）\n")
    seen_ids = set()
    while True:
        spans = fetch_spans(logs_client, hours=0.1)
        new_spans = [s for s in spans if id(s) not in seen_ids]
        for sp in new_spans:
            key = f"{sp.get('traceId')}-{sp.get('spanId')}"
            if key not in seen_ids:
                seen_ids.add(key)
                ts = _ts_to_str(sp.get("_timestamp_ms", 0))
                name = sp.get("name", "unknown")
                dur = _duration_ms(sp.get("startTimeUnixNano"), sp.get("endTimeUnixNano"))
                print(f"[{ts}] {name:<40} {dur}")
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bedrock AgentCore Observability 查看工具")
    parser.add_argument("--hours", type=float, default=1.0, help="查询最近 N 小时 (默认 1)")
    parser.add_argument("--traces", action="store_true", help="按 traceId 分组展示调用链")
    parser.add_argument("--live", action="store_true", help="实时监控新 span")
    parser.add_argument("--limit", type=int, default=200, help="最多获取 N 条 span (默认 200)")
    args = parser.parse_args()

    import boto3
    region = os.environ.get("AWS_REGION", "us-east-1")
    logs_client = boto3.client("logs", region_name=region)

    if args.live:
        live_monitor(logs_client)
        return

    print(f"🔎 查询最近 {args.hours} 小时的 span 数据（aws/spans）...")
    spans = fetch_spans(logs_client, hours=args.hours, limit=args.limit)

    if args.traces:
        print_traces(spans)
    else:
        print_spans_table(spans)


if __name__ == "__main__":
    main()
