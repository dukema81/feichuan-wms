# -*- coding: utf-8 -*-
"""把本地 git 仓库的全部受控文件推送到 GitHub（走 gh api contents 接口）。

飞传WMS：默认仓库 dukema81/feichuan-wms，分支 main。

为什么不用 git push：本机出口代理对 github.com:443 的 CONNECT 返回 502，
而 api.github.com 可用（gh 走的是 API）。此脚本逐文件 PUT，支持二进制（base64）。

用法：python tools/push_github.py [OWNER/REPO] [BRANCH]
"""
import base64
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = sys.argv[1] if len(sys.argv) > 1 else "dukema81/feichuan-wms"
BRANCH = sys.argv[2] if len(sys.argv) > 2 else "main"
MSG = "feat: 飞传WMS V1.0（三态状态机与闸口 + FEFO 分配 + 货位推荐与蛇形拣货 + 波次引擎 + 三通道集成）"


def gh(args, data=None):
    cmd = ["gh"] + args
    if data is not None:
        cmd += ["--input", "-"]
    proc = subprocess.run(cmd, cwd=ROOT, input=(json.dumps(data).encode() if data is not None else None),
                          capture_output=True)
    out = proc.stdout.decode("utf-8", "ignore")
    err = proc.stderr.decode("utf-8", "ignore")
    return proc.returncode, out, err


def remote_sha(path):
    code, out, _ = gh(["api", "repos/%s/contents/%s?ref=%s" % (REPO, path, BRANCH)])
    if code != 0:
        return None
    try:
        return json.loads(out).get("sha")
    except Exception:
        return None


def main():
    code, out, err = gh(["api", "repos/%s" % REPO])
    if code != 0:
        print("仓库不可访问：", err[:200])
        return 1
    print("仓库：", json.loads(out)["full_name"])

    raw = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "-z"],
                         cwd=ROOT, capture_output=True).stdout
    files = [x for x in raw.decode("utf-8").split("\0") if x]
    print("待推送文件：%d" % len(files))
    ok = fail = 0
    for i, rel in enumerate(files, 1):
        full = os.path.join(ROOT, rel)
        with open(full, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        body = {"message": "%s\n\n%s" % (MSG.split("\n")[0], rel), "content": content, "branch": BRANCH}
        sha = remote_sha(rel)
        if sha:
            body["sha"] = sha
        code, out, err = gh(["api", "--method", "PUT",
                             "repos/%s/contents/%s" % (REPO, rel.replace(os.sep, "/"))], data=body)
        if code == 0:
            ok += 1
            print("  [%2d/%2d] OK   %s" % (i, len(files), rel))
        else:
            fail += 1
            print("  [%2d/%2d] FAIL %s :: %s" % (i, len(files), rel, (err or out).strip()[:160]))
    print("\n成功 %d，失败 %d" % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
