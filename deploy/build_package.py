# -*- coding: utf-8 -*-
"""打部署包：feichuan_app.tar.gz（backend/frontend/deploy/docs/demo/tests/scripts/tools + README）。"""
import io
import os
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = r"C:/Users/maxl/WorkBuddy/Claw/Temp/feichuan_app.tar.gz"
INCLUDE = ["backend", "frontend", "deploy", "docs", "demo", "tests", "scripts", "tools",
           "README.md", "pytest.ini", ".gitignore"]
SKIP_DIRS = {"data", "__pycache__", ".pytest_cache", "screenshots", "node_modules", ".git"}
SKIP_EXT = {".pyc", ".db", ".db-wal", ".db-shm", ".log"}
SKIP_FILES = {"测试中文.md"}


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    n = 0
    with tarfile.open(OUT, "w:gz") as tf:
        for item in INCLUDE:
            p = os.path.join(ROOT, item)
            if not os.path.exists(p):
                print("skip missing", item)
                continue
            if os.path.isfile(p):
                tf.add(p, arcname=item)
                n += 1
                continue
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                rel = os.path.relpath(dirpath, ROOT).replace("\\", "/")
                for f in filenames:
                    if os.path.splitext(f)[1] in SKIP_EXT or f in SKIP_FILES:
                        continue
                    tf.add(os.path.join(dirpath, f), arcname=rel + "/" + f)
                    n += 1
    print("打包完成：%s（%.1f KB，%d 个文件）" % (OUT, os.path.getsize(OUT) / 1024.0, n))


if __name__ == "__main__":
    main()
