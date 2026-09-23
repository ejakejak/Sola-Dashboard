#!/usr/bin/env python3
# coding: utf-8
# Capture Phase 8 (Dashboard + Production Board) for headless-chrome screenshots.
import os, urllib.request, urllib.parse
from http.cookiejar import CookieJar
BASE="http://127.0.0.1:5000"
OUT=os.path.join(r"D:/Sola","_shots","phase8"); STATIC=r"D:/Sola/app/static"
os.makedirs(OUT, exist_ok=True)
jar=CookieJar(); opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def req(path,data=None):
    r=urllib.request.Request(BASE+path,data=data)
    try:
        resp=opener.open(r,timeout=25); return resp.status, resp.read().decode("utf-8","replace")
    except Exception as e: return "ERR", str(e)
req("/login", urllib.parse.urlencode({"username":"admin","password":"sola123"}).encode())
def rewrite(h): return h.replace('href="/static/','href="file:///'+STATIC+'/').replace('src="/static/','src="file:///'+STATIC+'/')
for name,path in {"dashboard":"/","board":"/production/board"}.items():
    st,h=req(path); open(os.path.join(OUT,name)+".html","w",encoding="utf-8").write(rewrite(h) if st==200 else h)
    print(name,"->",st,"bytes",len(h))