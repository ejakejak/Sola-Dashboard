#!/usr/bin/env python3
# Fresh authenticated capture of the SOLA dashboard.
import os, urllib.request, urllib.parse
from http.cookiejar import CookieJar

BASE = "http://127.0.0.1:5000"
OUT = r"D:/Sola/_shots/current"
STATIC = r"D:/Sola/app/static"
os.makedirs(OUT, exist_ok=True)

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def req(path, data=None):
    r = urllib.request.Request(BASE + path, data=data)
    try:
        resp = opener.open(r, timeout=25)
        return resp.status, resp.read().decode("utf-8", "replace")
    except Exception as e:
        return "ERR", str(e)

st, _ = req("/login", urllib.parse.urlencode(
    {"username": "admin", "password": "sola123"}).encode())
print("login POST ->", st, "cookies:", [c.name for c in jar])

for name, path in {"dashboard": "/"}.items():
    st, h = req(path)
    h = h.replace('href="/static/', 'href="file:///' + STATIC + '/')\
         .replace('src="/static/', 'src="file:///' + STATIC + '/')
    open(os.path.join(OUT, name) + ".html", "w", encoding="utf-8").write(h)
    print(name, "->", st, "bytes", len(h))