"""
一键启动脚本
使用方法:
    python run.py                    # 默认端口 8000
    python run.py --port 80          # 指定端口
    python run.py --reload           # 开发模式（自动 reload）
    ROOT_PATH=/resume python run.py  # Nginx 反向代理模式
"""
import sys
import os
import argparse
import uvicorn

from app.config import settings


def main():
    parser = argparse.ArgumentParser(description="简历 AI Agent 启动器")
    parser.add_argument("--host", default=settings.HOST, help="监听地址")
    parser.add_argument("--port", type=int, default=settings.PORT, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开启自动重载（开发模式）")
    parser.add_argument("--root-path", default=os.environ.get("ROOT_PATH", ""), help="反向代理根路径")
    args = parser.parse_args()

    if args.root_path:
        os.environ["ROOT_PATH"] = args.root_path

    print(f"🚀 正在启动 简历 AI Agent -> http://{args.host}:{args.port}{args.root_path}/")
    print(f"   根路径:    {args.root_path or '/'}")
    print(f"   前台页面:  http://{args.host}:{args.port}{args.root_path}/")
    print(f"   管理后台:  http://{args.host}:{args.port}{args.root_path}/admin")
    print(f"   API 文档:  http://{args.host}:{args.port}{args.root_path}/docs")
    print("=" * 60)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 再见，服务已停止。")
        sys.exit(0)
