import json

files = [
    r'C:\ceshi\练习3\硬件分页 12万条 50并发.html',
    r'C:\ceshi\练习3\硬件分页 6万条 50-150并发.html',
    r'C:\ceshi\练习3\硬件分页 2万数据查询100-200压测.html',
]

for path in files:
    print("\n" + "="*80)
    print(f"FILE: {path}")
    print("="*80)

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    idx = content.find('window.templateArgs = {')
    prefix = 'window.templateArgs = '
    start = idx + len(prefix)

    brace_count = 0
    in_string = False
    escape_next = False
    json_end = -1
    for i in range(start, len(content)):
        c = content[i]
        if escape_next:
            escape_next = False
            continue
        if c == '\\':
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if not in_string:
            if c == '{':
                brace_count += 1
            elif c == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i
                    break

    json_str = content[start:json_end+1]
    data = json.loads(json_str)

    print(f"host: {data.get('host')}")
    print(f"locustfile: {data.get('locustfile')}")
    print(f"duration: {data.get('duration')}")
    print(f"start_time: {data.get('start_time')}")
    print(f"end_time: {data.get('end_time')}")

    tasks = data.get('tasks', {})
    print(f"tasks: {json.dumps(tasks, ensure_ascii=False)[:600]}")

    req_stats = data.get('requests_statistics', [])
    print(f"\n--- requests_statistics [{len(req_stats)}] ---")
    for i, s in enumerate(req_stats):
        name = s.get('name', 'N/A')
        print(f"\n  [{i}] {name}")
        print(f"    num_requests: {s.get('num_requests')}")
        print(f"    num_failures: {s.get('num_failures')}")
        print(f"    avg_response_time: {s.get('avg_response_time')} ms")
        print(f"    median_response_time: {s.get('median_response_time')} ms")
        print(f"    min_response_time: {s.get('min_response_time')} ms")
        print(f"    max_response_time: {s.get('max_response_time')} ms")
        print(f"    P95: {s.get('response_time_percentile_0.95', 'N/A')} ms")
        print(f"    P99: {s.get('response_time_percentile_0.99', 'N/A')} ms")
        print(f"    current_rps: {s.get('current_rps')}")
        print(f"    current_fail_per_sec: {s.get('current_fail_per_sec')}")
        print(f"    avg_content_length: {s.get('avg_content_length')} bytes")

    resp_stats = data.get('response_time_statistics', [])
    print(f"\n--- response_time_statistics [{len(resp_stats)}] ---")
    for i, s in enumerate(resp_stats):
        name = s.get('name', 'N/A')
        print(f"\n  [{i}] {name}")
        for k in sorted(s.keys()):
            if k not in ('name', 'method'):
                print(f"    {k}: {s[k]} ms")

    history = data.get('history', [])
    print(f"\n--- history [{len(history)} entries] ---")
    if history:
        first = history[0]
        last = history[-1]

        def get_val(h, key):
            v = h.get(key, [None, 0])
            if isinstance(v, list) and len(v) == 2:
                return v[1]
            return 0
        def get_time(h, key):
            v = h.get(key, [None, 0])
            if isinstance(v, list) and len(v) == 2:
                return v[0]
            return ''

        print(f"  START: RPS={get_val(first,'current_rps')}, Users={get_val(first,'user_count')}, AvgRT={get_val(first,'total_avg_response_time')}")
        print(f"  END:   RPS={get_val(last,'current_rps')}, Users={get_val(last,'user_count')}, AvgRT={get_val(last,'total_avg_response_time')}")

        peak_rps = 0; peak_rps_time = ""
        peak_users = 0; peak_users_time = ""
        peak_rt = 0; peak_rt_time = ""
        peak_fail = 0; peak_fail_time = ""

        for h in history:
            for key, val in h.items():
                if isinstance(val, list) and len(val) == 2:
                    v = val[1]
                    t = val[0]
                    if key == 'current_rps' and v > peak_rps:
                        peak_rps = v; peak_rps_time = t
                    elif key == 'user_count' and v > peak_users:
                        peak_users = v; peak_users_time = t
                    elif key == 'total_avg_response_time' and v > peak_rt:
                        peak_rt = v; peak_rt_time = t
                    elif key == 'current_fail_per_sec' and v > peak_fail:
                        peak_fail = v; peak_fail_time = t

        print(f"  PEAK RPS: {peak_rps} at {peak_rps_time}")
        print(f"  PEAK Users: {peak_users} at {peak_users_time}")
        print(f"  PEAK Avg RT: {peak_rt} ms at {peak_rt_time}")
        print(f"  PEAK Fail/s: {peak_fail} at {peak_fail_time}")

    fail_stats = data.get('failures_statistics', [])
    print(f"\n--- failures_statistics [{len(fail_stats)}] ---")
    for f in fail_stats:
        print(f"  {f.get('name')}: {f.get('error')} (occurrences: {f.get('occurrences')})")

    exc_stats = data.get('exceptions_statistics', [])
    print(f"\n--- exceptions_statistics [{len(exc_stats)}] ---")
    for e in exc_stats:
        print(f"  {e.get('name')}: {e.get('error')} (occurrences: {e.get('occurrences')})")
