"""Smoke: suggest -> apply flow via real API."""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def req(method, path, body=None, token=None):
    r = urllib.request.Request(BASE + path, method=method)
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, data) as resp:
        return json.loads(resp.read())


login = req("POST", "/api/auth/login", {"username": "demo", "password": "demo123456"})
t = login["token"]
s = req("POST", "/api/projections/4/suggest-goals", {"horizon_years": 3}, t)  # id 4 exists
s0 = s["suggestions"][0]
print("suggest degraded:", s["degraded"], "| first:", s0["title"][:30])
a = req("POST", "/api/projections/apply-suggestion", {
    "title": s0["title"], "description": s0.get("description"), "dimension": s0.get("dimension"), "with_tasks": True,
}, t)
print("applied:", a["goal"]["title"][:30], "| tasks_created:", a["tasks_created"], "| degraded:", a["degraded"])
tasks = req("GET", "/api/tasks", token=t)
for x in tasks[-5:]:
    print(f"  [{x['granularity']}] {x['title'][:40]} (parent={x['parent_task_id']})")
