# 离线 Wheel 包缓存目录

此目录用于缓存 OCR 依赖（如 ddddocr）的 wheel 包。

## 工作原理

- **首次启动**：`check_deps.py` 自动从网络下载 .whl 文件到此目录并安装
- **Docker 场景**：建议在 `docker-compose.yml` 中挂载此目录，避免每次重建重复下载
- **本地开发**：下载后容器/本地都可复用，无需重复下载

## 手动预下载（可选）

```bash
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
