#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载离线 wheel 包 — 用于无网络环境部署

用法：
  python download_wheels.py                    # 默认下载 ddddocr
  python download_wheels.py paddleocr          # 下载 PaddleOCR
  python download_wheels.py ddddocr paddleocr  # 下载多个

下载后的 .whl 文件保存在 wheels/ 目录，部署时随项目一起复制即可。
启动时 check_deps.py 会自动优先从 wheels/ 安装。
"""
import importlib
import os
import subprocess
import sys

WHEELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wheels')
os.makedirs(WHEELS_DIR, exist_ok=True)

# 预定义包列表
PACKAGES = {
    'ddddocr': {
        'pip': 'ddddocr',
        'desc': '轻量级中文OCR（~30MB，推荐）',
    },
    'paddleocr': {
        'pip': 'paddleocr',
        'desc': '重量级中文OCR（~800MB，含 PyTorch）',
    },
}


def download_wheels(package_specs: list, index_url: str = None):
    """下载指定包的 wheel 到 WHEELS_DIR"""
    cmd = [
        sys.executable, '-m', 'pip', 'download',
        '--dest', WHEELS_DIR,
        '--no-cache-dir',
    ]
    if index_url:
        cmd.extend(['-i', index_url])
        trusted = os.getenv('PIP_TRUSTED_HOST', '')
        if trusted:
            cmd.extend(['--trusted-host', trusted])

    cmd.extend(package_specs)

    print(f"📦 正在下载 wheel 到: {WHEELS_DIR}")
    print(f"   包: {', '.join(package_specs)}")
    print()

    result = subprocess.run(cmd)

    if result.returncode == 0:
        # 统计下载的文件
        whl_files = [f for f in os.listdir(WHEELS_DIR) if f.endswith('.whl')]
        print(f"✅ 下载完成！共 {len(whl_files)} 个 wheel 文件:")
        for f in sorted(whl_files):
            size = os.path.getsize(os.path.join(WHEELS_DIR, f))
            size_str = f"{size / 1024 / 1024:.1f} MB" if size > 1024 * 1024 else f"{size / 1024:.0f} KB"
            print(f"   {f}  ({size_str})")
    else:
        print(f"❌ 下载失败:")
        print(result.stderr[-500:])
        sys.exit(1)


def main():
    # 检查是否已有 wheels
    existing = [f for f in os.listdir(WHEELS_DIR) if f.endswith('.whl')]

    args = sys.argv[1:] if len(sys.argv) > 1 else ['ddddocr']

    # 解析要下载的包
    specs = []
    for arg in args:
        if arg in PACKAGES:
            specs.append(PACKAGES[arg]['pip'])
        else:
            specs.append(arg)  # 允许直接传 pip 包名

    # 镜像源：优先使用环境变量，默认阿里云镜像（国内加速）
    index_url = os.getenv('PIP_INDEX_URL', 'https://mirrors.aliyun.com/pypi/simple/')

    download_wheels(specs, index_url or None)

    # 写入 .gitkeep（如果目录为空）
    gitkeep = os.path.join(WHEELS_DIR, '.gitkeep')
    if not os.path.exists(gitkeep):
        with open(gitkeep, 'w') as f:
            f.write('# Wheel 包目录 - 运行 python download_wheels.py 下载\n')


if __name__ == '__main__':
    main()
