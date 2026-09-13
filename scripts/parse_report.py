import json, sys, os

path = r'C:\Users\86139\Downloads\新增硬件压测.html'
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

print("="*65)
print("  新增硬件(Hardware Create)压测报告")
print("="*65)

# Basic info
print(f"\n{'[Basic Info]':=^50}")
print(f"  Target Host:     {data.get('host', 'N/A')}")
print(f"  Locust File:     {data.get('locustfile', 'N/A')}")
print(f"  Start Time:      {data.get('start_time', 'N/A')}")
print(f"  End Time:        {data.get('end_time', 'N/A')}")
print(f"  Duration:        {data.get('duration', 'N/A')}")

# Tasks info
tasks = data.get('tasks', {})
total_tasks = tasks.get('total', {})
print(f"  User Class:      {list(total_tasks.keys())}")
for cls_name, cls_info in total_tasks.items():
    task_info = cls_info.get('tasks', {})
    print(f"  Tasks:           {json.dumps(task_info, ensure_ascii=False)}")

# Per-request statistics
print(f"\n{'[Request Statistics]':=^50}")
req_stats = data.get('requests_statistics', [])
total_all_reqs = 0
total_all_fails = 0
for i, s in enumerate(req_stats):
    name = s.get('name', f'Endpoint-{i}')
    num_req = s.get('num_requests', 0)
    num_fail = s.get('num_failures', 0)
    total_all_reqs += num_req
    total_all_fails += num_fail

    print(f"\n  --- {name} ---")
    print(f"  Requests:         {num_req}")
    print(f"  Failures:         {num_fail}")
    fail_rate = (num_fail / num_req * 100) if num_req > 0 else 0
    print(f"  Failure Rate:     {fail_rate:.2f}%")
    print(f"  Avg Response:     {s.get('avg_response_time', 'N/A')} ms")
    print(f"  Median Response:  {s.get('median_response_time', 'N/A')} ms")
    print(f"  Min Response:     {s.get('min_response_time', 'N/A')} ms")
    print(f"  Max Response:     {s.get('max_response_time', 'N/A')} ms")
    print(f"  Avg Content Len:  {s.get('avg_content_length', 'N/A')} bytes")
    print(f"  RPS:              {s.get('current_rps', 'N/A')}")
    print(f"  Fail/s:           {s.get('current_fail_per_sec', 'N/A')}")

    # Percentiles from request_statistics
    for pct_key in ['response_time_percentile_0.5', 'response_time_percentile_0.66',
                    'response_time_percentile_0.75', 'response_time_percentile_0.8',
                    'response_time_percentile_0.9', 'response_time_percentile_0.95',
                    'response_time_percentile_0.98', 'response_time_percentile_0.99',
                    'response_time_percentile_1.0']:
        if pct_key in s:
            label = pct_key.replace('response_time_percentile_', 'P')
            print(f"  {label}:             {s[pct_key]} ms")

# Response time statistics (aggregate percentiles)
print(f"\n{'[Aggregate Response Time]':=^50}")
resp_stats = data.get('response_time_statistics', [])
for s in resp_stats:
    print(f"\n  --- {s.get('name', 'N/A')} ---")
    print(f"  Total Requests:  {s.get('num_requests', 'N/A')}")
    print(f"  Avg Response:    {s.get('avg_response_time', 'N/A')} ms")
    for pct_key in ['response_time_percentile_0.5', 'response_time_percentile_0.95',
                    'response_time_percentile_0.99', 'response_time_percentile_1.0']:
        if pct_key in s:
            label = pct_key.replace('response_time_percentile_', 'P')
            print(f"  {label}:             {s[pct_key]} ms")

# History analysis
print(f"\n{'[History Trend]':=^50}")
history = data.get('history', [])
if history:
    # Find peak RPS
    peak_rps = 0
    peak_rps_time = ""
    peak_rt = 0
    peak_rt_time = ""
    peak_users = 0
    peak_users_time = ""

    for h in history:
        rps_val = h.get('current_rps', [None, 0])
        if isinstance(rps_val, list) and len(rps_val) == 2:
            rps = rps_val[1]
            if rps > peak_rps:
                peak_rps = rps
                peak_rps_time = rps_val[0]

        rt_val = h.get('total_avg_response_time', [None, 0])
        if isinstance(rt_val, list) and len(rt_val) == 2:
            rt = rt_val[1]
            if rt > peak_rt:
                peak_rt = rt
                peak_rt_time = rt_val[0]

        users_val = h.get('user_count', [None, 0])
        if isinstance(users_val, list) and len(users_val) == 2:
            users = users_val[1]
            if users > peak_users:
                peak_users = users
                peak_users_time = users_val[0]

    first = history[0]
    last = history[-1]

    def get_val(h, key):
        v = h.get(key, [None, 0])
        if isinstance(v, list) and len(v) == 2:
            return v[1]
        return 0

    print(f"  History data points: {len(history)}")
    print(f"\n  Start RPS:          {get_val(first, 'current_rps'):.1f}")
    print(f"  End RPS:            {get_val(last, 'current_rps'):.1f}")
    print(f"  Peak RPS:           {peak_rps:.1f} (at {peak_rps_time})")
    print(f"\n  Start Avg RT:       {get_val(first, 'total_avg_response_time'):.1f} ms")
    print(f"  End Avg RT:         {get_val(last, 'total_avg_response_time'):.1f} ms")
    print(f"  Peak Avg RT:        {peak_rt:.1f} ms (at {peak_rt_time})")
    print(f"\n  Start Users:        {get_val(first, 'user_count')}")
    print(f"  End Users:          {get_val(last, 'user_count')}")
    print(f"  Peak Users:         {peak_users} (at {peak_users_time})")

    # Failure analysis
    total_failures_hist = sum(get_val(h, 'current_fail_per_sec') for h in history)
    print(f"\n  Total Fail/s sum:   {total_failures_hist:.1f}")

# Summary
print(f"\n{'[Summary]':=^50}")
print(f"  Total Requests:    {total_all_reqs}")
print(f"  Total Failures:    {total_all_fails}")
print(f"  Success Rate:      {((total_all_reqs - total_all_fails) / total_all_reqs * 100) if total_all_reqs > 0 else 0:.2f}%")
print(f"  Peak VU:           {peak_users}")
print(f"  Peak RPS:          {peak_rps:.1f}")

print(f"\n{'='*65}")
