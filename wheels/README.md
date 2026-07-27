# 离线 Wheel 包目录

将预下载的 `.whl` 文件放入此目录，可实现无网络环境部署。

## 下载离线包

```bash
# 下载 ddddocr（轻量版 OCR，推荐）
python download_wheels.py ddddocr

# 下载 PaddleOCR（重量版）
python download_wheels.py paddleocr

# 指定镜像源加速
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ python download_wheels.py ddddocr
```

## 部署方式

将 `wheels/` 目录与项目一起复制到目标机器：

- **本地启动**：`check_deps.py` 自动优先从 `wheels/` 安装
- **Docker 构建**：`Dockerfile` 自动复制并安装 `wheels/*.whl`

> 提示：`wheels/` 目录下的 `.whl` 文件默认被 `.gitignore` 忽略，
> 如需纳入版本管理，请编辑 `.gitignore` 注释掉对应行。
