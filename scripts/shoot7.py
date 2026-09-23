#!/usr/bin/env python3
# coding: utf-8
# Capture Phase 7 /track pages for headless-chrome screenshots (public, no login).
import os, urllib.request, urllib.parse

BASE="http://127.0.0.1:5000"
OUT=os.path.join(r"D:/Sola","_shots","phase7"); STATIC=r"D:/Sola/app/static"
os.makedirs(OUT, exist_ok=True)

def fetch(path, data=None):
    r=urllib.request.Request(BASE+path, data=data)
    resp=urllib.request.urlopen(r, timeout=15)
    return resp.status, resp.read().decode("utf-8","replace")

def rewrite(h):
    return h.replace('href="/static/','href="file:///'+STATIC+'/').replace('src="/static/','src="file:///'+STATIC+'/')

# form page
st,b=fetch("/track"); open(os.path.join(OUT,"track_form.html"),"w",encoding="utf-8").write(rewrite(b)); print("track_form",st,len(b))
# result page (valid code)
st,b=fetch("/track", urllib.parse.urlencode({"code":"PRD-260922-001"}).encode()); open(os.path.join(OUT,"track_result.html"),"w",encoding="utf-8").write(rewrite(b)); print("track_result",st,len(b))