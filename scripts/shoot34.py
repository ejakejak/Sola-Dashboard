#!/usr/bin/env python3
# coding: utf-8
# Authenticated capture of Phase 3-4 pages for headless-chrome screenshots. stdlib only.
import os
import urllib.request, urllib.parse
from http.cookiejar import CookieJar

BASE = "http://127.0.0.1:5000"
OUT = os.path.join(r"D:/Sola", "_shots", "phase34")
STATIC = r"D:/Sola/app/static"
os.makedirs(OUT, exist_ok=True)

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def req(path, data=None):
    r = urllib.request.Request(BASE + path, data=data)
    try:
        resp = opener.open(r, timeout=20)
        return resp.status, resp.read().decode("utf-8", "replace")
    except Exception as e:
        return "ERR", str(e)


d = urllib.parse.urlencode({"username": "admin", "password": "sola123"}).encode()
req("/login", d)


def rewrite(html):
    html = html.replace('href="/static/', 'href="file:///' + STATIC + '/')
    html = html.replace('src="/static/', 'src="file:///' + STATIC + '/')
    return html


pages = {
    "quotations": "/quotations/",
    "orders": "/orders/",
    "invoices": "/invoices/",
    "invoice1": "/invoices/1",
    "quotation1": "/quotations/1",
}
for name, path in pages.items():
    st, html = req(path)
    fn = os.path.join(OUT, name) + ".html"
    with open(fn, "w", encoding="utf-8") as f:
        f.write(rewrite(html) if st == 200 else html)
    print(name, "->", st, "bytes", len(html))