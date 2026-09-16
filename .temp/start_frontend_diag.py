# -*- coding: utf-8 -*-
"""临时脚本：启动前端并记录日志到文件（诊断 SSR fetch failed 用）。"""
import os
import subprocess

ROOT = r"G:\xu\demo\舆情驱动的股票短线交易策略生成系统"
LOG = os.path.join(ROOT, ".temp")
NODE = r"C:\Users\Administrator\.local\share\TeleAgent\runtimes\node22\node-v22.17.0-win-x64\node.exe"

env = os.environ.copy()
env["WRANGLER_LOG_PATH"] = os.path.join(ROOT, ".wrangler", "wrangler.log")
env["NODE_OPTIONS"] = "--trace-warnings"
# 禁用代理，避免 proxy 环境变量干扰本地 fetch
for key in list(env):
    if key.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        del env[key]

vinext_bin = os.path.join(
    ROOT,
    r"node_modules\.pnpm\vinext@1.0.0-beta.2_@vitejs_da3cfe910abc970e3c191cc73e58297e"
    r"\node_modules\vinext\dist\cli.js",
)

out = open(os.path.join(LOG, "vinext-diag-out.log"), "ab")
err = open(os.path.join(LOG, "vinext-diag-err.log"), "ab")

proc = subprocess.Popen(
    [NODE, vinext_bin, "dev"],
    cwd=ROOT,
    env=env,
    stdin=subprocess.DEVNULL,
    stdout=out,
    stderr=err,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True,
)
print(f"STARTED PID={proc.pid}")