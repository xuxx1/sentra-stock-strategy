# -*- coding: utf-8 -*-
"""临时脚本：以独立进程方式启动后端（避免父进程退出后子进程被终止）。"""
import os
import subprocess
import sys

ROOT = r"G:\xu\demo\舆情驱动的股票短线交易策略生成系统"
LOG = os.path.join(ROOT, ".temp")

env = os.environ.copy()
env["CORS_ORIGIN"] = "http://localhost:3000,http://127.0.0.1:3000"

out = open(os.path.join(LOG, "backend-out.log"), "ab")
err = open(os.path.join(LOG, "backend-err.log"), "ab")

proc = subprocess.Popen(
    [sys.executable, "backend/server.py", "--host", "127.0.0.1", "--port", "8000"],
    cwd=ROOT,
    env=env,
    stdout=out,
    stderr=err,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True,
)
print(f"STARTED PID={proc.pid}")