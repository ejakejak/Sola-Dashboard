#!/usr/bin/env python3
# coding: utf-8
# EVA live verification of Phase 7 /track (public, anti-leak).
import urllib.request, urllib.parse

BASE="http://127.0.0.1:5000"
def get(path, data=None):
    r=urllib.request.Request(BASE+path, data=data)
    try:
        resp=urllib.request.urlopen(r, timeout=10)
        return resp.status, resp.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode("utf-8","replace")[:200] if e.code!=429 else b"429-body")

# 1 anonymous GET /track
st,b=get("/track"); print("GET /track(anon) ->",st,"len",len(b))
low=b.lower()
print("  leaks: hpp=%s margin=%s internal=%s vendor_price=%s production_id=%s"%(("hpp" in low),("margin" in low),("internal" in low),("vendor_price" in low),("production_id" in low)))

# 2 POST valid code
d=urllib.parse.urlencode({"code":"PRD-260922-001"}).encode()
st,b=get("/track",d)
print("POST /track valid ->",st,"len",len(b))
low=b.lower()
print("  leaks: hpp=%s margin=%s internal=%s vendor_price=%s production_id=%s"%(("hpp" in low),("margin" in low),("internal" in low),("vendor_price" in low),("production_id" in low)))
print("  has PRD code:", "PRD-260922-001" in b, "| has Product/timeline:", ("product" in low and "timeline" in low))

# 3 wrong code -> generic
d=urllib.parse.urlencode({"code":"PRD-000000-999"}).encode()
st,b=get("/track",d)
print("POST /track wrong ->",st,"| generic not found:", ("not found" in b.lower() or "tidak ditemukan" in b.lower()))

# 4 rate-limit: 6 rapid wrong guesses
codes=0; seen_429=False
for _ in range(6):
    st,_=get("/track", urllib.parse.urlencode({"code":"PRD-000000-99%d"%_}).encode())
    if st==429: seen_429=True
print("rate-limit 429 after rapid wrong:", seen_429)