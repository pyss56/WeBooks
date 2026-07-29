#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动依赖检查 — 确保必要依赖已安装，可选依赖给出提示"""
import importlib
import logging
import os
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# 从 requirements.txt 读取必需依赖
def _load_requirements() -> dict:
    """解析 requirements.txt，返回 {导入名: pip包名} 映射"""
    import re as _re
    req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'requirements.txt')
    mapping = {}
    if not os.path.exists(req_file):
        logger.error(f"requirements.txt 不存在: {req_file}")
        return mapping

    with open(req_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('--'):
                continue
            # 去掉注释
            line = _re.sub(r'#.*$', '', line).strip()
            if not line:
                continue
            # 处理 pip 包名 → 推测 Python 导入名
            pip_name = _re.sub(r'[><=~!].*$', '', line).strip()
            if not pip_name:
                continue
            # 已知的映射关系（处理特殊情况）
            known_map = {
                'python-dotenv': 'dotenv',
                'pycryptodome': 'Crypto',
                'APScheduler': 'apscheduler',
                'Flask': 'flask',
            }
            if pip_name in known_map:
                import_name = known_map[pip_name]
            else:
                # 默认直接用 pip 包名
                import_name = pip_name
            mapping[import_name] = pip_name
    return mapping

REQUIRED = _load_requirements()

# 可选自动安装 — 通过环境变量 PIP_AUTO_INSTALL 指定额外包
# 用途：pip install ddddocr, opencv-python-headless 等不阻塞启动流程
# 示例：PIP_AUTO_INSTALL=ddddocr 或 PIP_AUTO_INSTALL=paddleocr
_AUTO_INSTALL_PACKAGES = [
    p.strip() for p in os.getenv('PIP_AUTO_INSTALL', '').split(',')
    if p.strip()
]


def _get_wheels_dir() -> str:
    """获取 wheels 离线包目录路径"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wheels')


def _find_offline_wheel(package_spec: str) -> Optional[str]:
    """在 wheels/ 目录查找匹配的 wheel 文件

    支持模糊匹配：包名忽略版本号、Python 标签等差异
    例如: ddddocr → ddddocr-1.6.1-py3-none-any.whl
    """
    wheels_dir = _get_wheels_dir()
    if not os.path.isdir(wheels_dir):
        return None

    # 提取纯包名（去掉版本号等）
    import re as _re
    pkg_name = _re.sub(r'[><=~!].*$', '', package_spec).strip().lower()
    pkg_name = _re.sub(r'[-_.]+', '-', pkg_name)

    for f in os.listdir(wheels_dir):
        if not f.endswith('.whl'):
            continue
        # wheel 文件名格式: {package}-{version}-{pyver}-{abi}-{plat}.whl
        whl_name = f.split('-')[0].lower()
        whl_name = _re.sub(r'[-_.]+', '-', whl_name)
        if whl_name == pkg_name:
            return os.path.join(wheels_dir, f)

    return None


def _pip_install(package_spec: str) -> bool:
    """调用 pip 安装包（离线优先），返回是否成功

    安装顺序：
    1. 先在 wheels/ 目录查找离线 wheel 包
    2. 没找到则从网络下载 wheel 到本地，再从本地安装
    """
    # 尝试离线安装
    offline_wheel = _find_offline_wheel(package_spec)
    if offline_wheel:
        logger.info(f"📦 找到离线 wheel: {os.path.basename(offline_wheel)}，正在安装...")
        cmd = [sys.executable, '-m', 'pip', 'install', '--no-index', offline_wheel]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                logger.info(f"✅ 离线安装成功: {package_spec}")
                return True
            else:
                logger.warning(f"⚠️ 离线安装失败，尝试在线下载: {result.stderr[-200:]}")
        except Exception as e:
            logger.warning(f"⚠️ 离线安装异常，尝试在线下载: {e}")

    # 在线下载 wheel 到本地，再安装（方便 Docker 重建时使用本地依赖）
    index_url = os.getenv('PIP_INDEX_URL', 'https://mirrors.aliyun.com/pypi/simple/')
    trusted_host = os.getenv('PIP_TRUSTED_HOST', 'mirrors.aliyun.com')
    wheels_dir = _get_wheels_dir()
    os.makedirs(wheels_dir, exist_ok=True)

    # 1. 先下载 wheel 到本地 wheels/ 目录
    download_cmd = [
        sys.executable, '-m', 'pip', 'download',
        '--dest', wheels_dir,
        '--no-cache-dir',
    ]
    if index_url:
        download_cmd.extend(['-i', index_url])
    if trusted_host:
        download_cmd.extend(['--trusted-host', trusted_host])
    download_cmd.append(package_spec)

    try:
        logger.info(f"📥 正在下载依赖 wheel: {package_spec} ...")
        result = subprocess.run(download_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.warning(f"❌ 依赖下载失败: {package_spec}\n{result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"⏰ 依赖下载超时: {package_spec}")
        return False
    except Exception as e:
        logger.warning(f"⚠️ 依赖下载异常: {package_spec} - {e}")
        return False

    # 2. 从本地 wheels 目录安装
    offline_wheel = _find_offline_wheel(package_spec)
    if offline_wheel:
        logger.info(f"📦 从本地 wheel 安装: {os.path.basename(offline_wheel)}")
        install_cmd = [sys.executable, '-m', 'pip', 'install', '--no-index', offline_wheel]
        try:
            result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                logger.info(f"✅ 依赖安装成功: {package_spec}")
                return True
            else:
                logger.warning(f"❌ 本地安装失败: {package_spec}\n{result.stderr[-500:]}")
                return False
        except Exception as e:
            logger.warning(f"⚠️ 本地安装异常: {package_spec} - {e}")
            return False
    else:
        logger.warning(f"⚠️ 下载后未找到 wheel 文件: {package_spec}")
        return False


def _try_import(mod_name: str) -> bool:
    """尝试导入模块，自动回退小写尝试"""
    try:
        importlib.import_module(mod_name)
        return True
    except ImportError:
        pass
    # 包名首字母大写但模块全小写的情况（如 Flask → flask）
    lower = mod_name.lower()
    if lower != mod_name:
        try:
            importlib.import_module(lower)
            return True
        except ImportError:
            pass
    return False


def check_required() -> bool:
    """检查必需依赖，缺失则自动安装"""
    all_ok = True
    for mod_name, pip_name in REQUIRED.items():
        if _try_import(mod_name):
            continue
        logger.warning(f"📦 必需依赖缺失: {pip_name}，正在自动安装...")
        ok = _pip_install(pip_name)
        if ok:
            importlib.invalidate_caches()
            logger.info(f"✅ 必需依赖安装成功: {pip_name}")
        else:
            logger.error(f"❌ 必需依赖安装失败: {pip_name}")
            all_ok = False
    return all_ok


def check_optional():
    """检查环境变量 PIP_AUTO_INSTALL 中指定的包，缺失则自动安装"""
    if not _AUTO_INSTALL_PACKAGES:
        return

    for pkg in _AUTO_INSTALL_PACKAGES:
        try:
            importlib.import_module(pkg)
            logger.info(f"✅ 额外依赖已安装: {pkg}")
        except ImportError:
            logger.info(f"📦 额外依赖 {pkg} 未安装，正在自动安装...")
            ok = _pip_install(pkg)
            if ok:
                importlib.invalidate_caches()
                try:
                    importlib.import_module(pkg)
                except ImportError:
                    pass
                logger.info(f"✅ 额外依赖安装成功: {pkg}")
            else:
                logger.warning(f"⚠️ 额外依赖安装失败: {pkg}（不影响核心功能）")


def run_all():
    """执行全部依赖检查"""
    print("")
    print("=" * 50)
    print("📦 依赖检查")
    print("=" * 50)

    # 必需依赖
    if not check_required():
        sys.exit(1)
    print("  必需依赖: ✅ 全部就绪")

    # 额外依赖（PIP_AUTO_INSTALL）
    check_optional()

    print("=" * 50)
    print("")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    run_all()
