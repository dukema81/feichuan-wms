# -*- coding: utf-8 -*-
"""飞传 WMS · pytest 公共夹具：临时库 + 独立服务进程 + HTTP 客户端"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

API_PORT = int(os.environ.get("WMS_TEST_API_PORT", "8945"))
E2E_PORT = int(os.environ.get("WMS_TEST_E2E_PORT", "8946"))


def _wait_up(base, timeout=60):
    dl = time.time() + timeout
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.time() < dl:
        try:
            op.open(base + "/api/health", timeout=2)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def _spawn(port):
    dbp = os.path.join(tempfile.mkdtemp(prefix="fc_wms_"), "test.db")
    env = dict(os.environ, FEICHUAN_DB=dbp, FEICHUAN_PORT=str(port))
    proc = subprocess.Popen([sys.executable, os.path.join(BACKEND, "server.py")],
                            env=env, cwd=BACKEND,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    assert _wait_up(base), "服务未能在端口 %d 启动" % port
    return proc, base


class Client:
    def __init__(self, base):
        self.base = base
        self.token = None
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method, path, body=None, token=None, headers=None):
        path = urllib.parse.quote(path, safe="/?=&%.:_-")
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method)
        req.add_header("Content-Type", "application/json")
        tok = token if token is not None else self.token
        if tok:
            req.add_header("Authorization", "Bearer " + tok)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with self._opener.open(req, timeout=30) as r:
                raw = r.read()
                try:
                    return r.status, json.loads(raw)
                except Exception:
                    return r.status, {"raw": raw.decode("utf-8", "ignore")}
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"raw": raw.decode("utf-8", "ignore")}

    def login(self, username, password=None):
        password = password or ("admin123" if username == "admin" else "wh@2026")
        st, r = self.call("POST", "/api/auth/login", {"username": username, "password": password})
        assert st == 200, "登录失败 %s: %s" % (username, r)
        self.token = r["data"]["token"]
        return r["data"]

    def ok(self, method, path, body=None, token=None, headers=None):
        st, r = self.call(method, path, body, token, headers)
        assert st == 200, "接口 %s %s 返回 %s: %s" % (method, path, st, r)
        return r["data"]

    def err(self, method, path, body=None, code=400, token=None):
        st, r = self.call(method, path, body, token)
        assert st == code, "期望 %s 实际 %s: %s" % (code, st, r)
        return r

    def raw(self, method, path, body=None, token=None):
        """返回 (status, headers, body_bytes)，用于 CSV 等非 JSON 场景。"""
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None, method=method)
        req.add_header("Content-Type", "application/json")
        if token or self.token:
            req.add_header("Authorization", "Bearer " + (token or self.token))
        with self._opener.open(req, timeout=30) as r:
            return r.status, r.headers, r.read()


@pytest.fixture(scope="session")
def api():
    proc, base = _spawn(API_PORT)
    c = Client(base)
    c.login("admin", "admin123")
    yield c
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()


@pytest.fixture(scope="session")
def e2e_base():
    proc, base = _spawn(E2E_PORT)
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()


@pytest.fixture(scope="session")
def boot(api):
    return api.ok("GET", "/api/bootstrap")


@pytest.fixture()
def tok_maker(api):
    def make(username):
        st, r = api.call("POST", "/api/auth/login",
                         {"username": username,
                          "password": "admin123" if username == "admin" else "wh@2026"})
        assert st == 200, r
        return r["data"]["token"]
    return make
