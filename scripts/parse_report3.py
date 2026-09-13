import json

path = r'C:\Users\86139\Downloads\场景1.html'
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

print("=== TOP-LEVEL KEYS ===")
for k in sorted(data.keys()):
    v = data[k]
    if isinstance(v, list):
        print(f"  {k}: list[{len(v)}]")
        if v and isinstance(v[0], dict):
            print(f"    [0] keys: {list(v[0].keys())[:20]}")
    elif isinstance(v, dict):
        print(f"  {k}: dict keys={list(v.keys())[:15]}")
    else:
        print(f"  {k}: {v}")

print(f"\nhost: {data.get('host')}")
print(f"locustfile: {data.get('locustfile')}")
print(f"duration: {data.get('duration')}")
print(f"start_time: {data.get('start_time')}")
print(f"end_time: {data.get('end_time')}")

tasks = data.get('tasks', {})
print(f"tasks: {json.dumps(tasks, ensure_ascii=False)[:500]}")

# Request statistics
req_stats = data.get('requests_statistics', [])
print(f"\n=== requests_statistics [{len(req_stats)}] ===")
for i, s in enumerate(req_stats):
    print(f"\n--- [{i}] {s.get('name', 'N/A')} ---")
    for k in sorted(s.keys()):
        if k != 'name':
            print(f"  {k}: {s[k]}")

# Response time statistics
resp_stats = data.get('response_time_statistics', [])
print(f"\n=== response_time_statistics [{len(resp_stats)}] ===")
for i, s in enumerate(resp_stats):
    print(f"\n--- [{i}] {s.get('name', 'N/A')} ---")
    for k in sorted(s.keys()):
        if k != 'name':
            print(f"  {k}: {s[k]}")

# History
history = data.get('history', [])
print(f"\n=== history [{len(history)} entries] ===")
if history:
    first = history[0]
    last = history[-1]
    print("FIRST:")
    for k in sorted(first.keys()):
        print(f"  {k}: {first[k]}")
    print("\nLAST:")
    for k in sorted(last.keys()):
        print(f"  {k}: {last[k]}")

    # Peak analysis
    peak_rps = 0; peak_rps_time = ""
    peak_users = 0; peak_users_time = ""
    peak_rt = 0; peak_rt_time = ""
    peak_fail = 0; peak_fail_time = ""
    peak_p50 = 0; peak_p95 = 0

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
        p50 = h.get('response_time_percentile_0.5', [None, 0])
        if isinstance(p50, list) and len(p50) == 2 and p50[1] > peak_p50:
            peak_p50 = p50[1]
        p95 = h.get('response_time_percentile_0.95', [None, 0])
        if isinstance(p95, list) and len(p95) == 2 and p95[1] > peak_p95:
            peak_p95 = p95[1]

    print(f"\nPEAK RPS: {peak_rps} at {peak_rps_time}")
    print(f"PEAK Users: {peak_users} at {peak_users_time}")
    print(f"PEAK Avg RT: {peak_rt} ms at {peak_rt_time}")
    print(f"PEAK Fail/s: {peak_fail} at {peak_fail_time}")
    print(f"PEAK P50: {peak_p50} ms")
    print(f"PEAK P95: {peak_p95} ms")

    # Start/end values
    print(f"\nSTART RPS: {first.get('current_rps', [0,0])[1]}")
    print(f"END RPS: {last.get('current_rps', [0,0])[1]}")
    print(f"START Users: {first.get('user_count', [0,0])[1]}")
    print(f"END Users: {last.get('user_count', [0,0])[1]}")
    print(f"START Avg RT: {first.get('total_avg_response_time', [0,0])[1]}")
    print(f"END Avg RT: {last.get('total_avg_response_time', [0,0])[1]}")

fail_stats = data.get('failures_statistics', [])
print(f"\n=== failures_statistics [{len(fail_stats)}] ===")
for f in fail_stats:
    print(json.dumps(f, ensure_ascii=False)[:300])

exc_stats = data.get('exceptions_statistics', [])
print(f"\n=== exceptions_statistics [{len(exc_stats)}] ===")
for e in exc_stats:
    print(json.dumps(e, ensure_ascii=False)[:300])
