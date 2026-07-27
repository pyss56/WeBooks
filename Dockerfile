FROM python:3.11-slim

WORKDIR /app

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ARG VERSION=unknown
ARG BUILD_TIME=
ARG COMMIT_SHA=

# 写入构建信息
RUN echo "VERSION=${VERSION}" > /app/build_info && \
    echo "BUILD_TIME=${BUILD_TIME}" >> /app/build_info && \
    echo "COMMIT_SHA=${COMMIT_SHA}" >> /app/build_info

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i ${PIP_INDEX_URL} \
    --trusted-host ${PIP_TRUSTED_HOST} \
    -r requirements.txt

# 离线 wheel 包（可选 — 有则安装）
COPY wheels/ /app/wheels/
RUN if ls /app/wheels/*.whl 2>/dev/null; then \
        pip install --no-cache-dir --find-links /app/wheels --no-index /app/wheels/*.whl 2>&1 || \
        echo "⚠️ 部分离线 wheel 安装失败（不影响核心功能）"; \
    fi

# 复制源码
COPY . .

# 入口脚本添加可执行权限
RUN chmod +x entrypoint.sh

EXPOSE 5001

ENTRYPOINT ["./entrypoint.sh"]
