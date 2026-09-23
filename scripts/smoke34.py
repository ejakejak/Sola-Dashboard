#!/usr/bin/env python3
# coding: utf-8
# Clean ASCII live-smoke for Phase 3-4 pages (EVA gate). Uses only stdlib.

import urllib.request, urllib.parse
from http.cookiejar import CookieJar


BASE = "http://127.0.0.1:5000"
jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def req(path, data=None):
    r = urllib.request.Request(BASE + path, data=data)
    try:
        resp = opener.open(r, timeout=20)
        return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return "ERR", str(e)


d = urllib.parse.urlencode({"username": "admin", "password": "sola123"}).encode()
st, _ = req("/login", d)
print("login:", st, "cookies:", [c.name for c in jar])

for p in ["/quotations/", "/quotations/new", "/orders/", "/invoices/"]:
    st, b = req(p)
    if st == 200:
        sig = " ".join(b.split())[:100]
        print(p, "->", st, "|", sig)
    else:
        print(p, "->", st, "|", b[:140])