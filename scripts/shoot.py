#!/usr/bin/env python3
"""Capture authenticated SOLA dashboard HTML for headless-Chrome screenshots.
Logs in via the running app, fetches key pages, rewrites /static/ -> absolute file://
so a local file render includes css + logo, saves under D:/Sola/_shots/."""
import os, re, sys
import urllib.request, urllib.parse
from http.cookiejar import CookieJar

BASE = "http://127.0.0.1:5000"
OUT = os.path.join(r"D:/Sola", "_shots")
STATIC = r"D:/Sola/app/static"
os.makedirs(OUT, exist_ok=True)

USER, PWD = "admin", "sola123"
pages = ["/", "/master-data/", "/login"]

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def get(path):
    req = urllib.request.Request(BASE + path)
    return opener.open(req, timeout=20).read().decode("utf-8", "replace")

# login
data = urllib.parse.urlencode({"username": USER, "password": PWD}).encode()
try:
    opener.open(urllib.request.Request(BASE + "/login", data=data), timeout=20)
    print("login POST ok; cookies:", [c.name for c in jar])
except Exception as e:
    print("login error:", e)

def rewrite(html):
    html = html.replace('href="/static/', f'href="file:///{STATIC}/')
    html = html.replace('src="/static/', f'src="file:///{STATIC}/')
    return html

for p in pages:
    try:
        html = get(p)
        fn = os.path.join(OUT, p.strip("/").replace("/", "_") or "root") + ".html"
        with open(fn, "w", encoding="utf-8") as f:
            f.write(rewrite(html))
        print(f"saved {fn}  ({len(html)} bytes)")
    except Exception as e:
        print(f"ERR {p}: {e}")