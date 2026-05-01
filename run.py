#!/usr/bin/env python3
"""
VibeRAG 启动脚本
"""
import sys
import uvicorn


def main():
    print("=" * 50)
    print("VibeRAG - 智能商业文档分析与销售助手")
    print("=" * 50)

    # 检查依赖
    try:
        import fastapi
        import sqlalchemy
        import ollama
    except ImportError as e:
        print(f"缺少依赖: {e}")
        print("请运行: pip install -r requirements.txt")
        sys.exit(1)

    print("\n正在启动服务...")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
