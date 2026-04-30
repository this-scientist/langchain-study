#!/usr/bin/env python3
"""
本地启动入口：在仓库根目录执行

    python run_server.py

会先从根目录加载 `.env`（与 `backend/main.py`、`db/__init__.py` 中的 load_dotenv 一致），
再读取可选环境变量 `UVICORN_HOST`、`UVICORN_PORT`、`UVICORN_RELOAD` 启动 uvicorn。

其余配置（GLM_*、DB_MODE、DB_* 等）仍放在 `.env` 中即可，无需在命令行 export。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")


def main() -> None:
    import uvicorn

    host = os.getenv("UVICORN_HOST", "0.0.0.0")
    port = int(os.getenv("UVICORN_PORT", "8000"))
    reload = os.getenv("UVICORN_RELOAD", "true").lower() in ("1", "true", "yes")

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
