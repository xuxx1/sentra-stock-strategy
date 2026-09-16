# -*- coding: utf-8 -*-
"""临时脚本：以独立进程方式启动前端（Node 22 + vinext dev）。"""
import os
import subprocess
import sys

ROOT = r"G:\xu\demo\舆情驱动的股票短线交易策略生成系统"
LOG = os.path.join(ROOT, ".temp")
NODE = r"C:\Users\Administrator\.local\share\TeleAgent\runtimes\node22\node-v22.17.0-win-x64\node.exe"

env = os.environ.copy()
env["WRANGLER_LOG_PATH"] = os.path.join(ROOT, ".wrangler", "wrangler.log")
# 禁用代理，避免 proxy 环境变量干扰本地 fetch
for key in list(env):
    if key.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        del env[key]

vinext_bin = os.path.join(
    ROOT,
    r"node_modules\.pnpm\vinext@1.0.0-beta.2_@vitejs_da3cfe910abc970e3c191cc73e58297e"
    r"\node_modules\vinext\dist\cli.js",
)

proc = subprocess.Popen(
    [NODE, vinext_bin, "dev"],
    cwd=ROOT,
    env=env,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True,
)
print(f"STARTED PID={proc.pid}")