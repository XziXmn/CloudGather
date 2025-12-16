FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（psutil 需要 gcc，gosu 用于权限切换）
RUN apt-get update && apt-get install -y \
    gcc \
    tzdata \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY core/ ./core/
COPY html/ ./html/
COPY static/ ./static/
COPY version.py .
COPY main.py .
COPY entrypoint.sh /entrypoint.sh

# 创建必要的目录
RUN mkdir -p /app/config

# 设置默认环境变量
ENV IS_DOCKER=true \
    TZ=Asia/Shanghai \
    PUID=1000 \
    PGID=1001 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8

# 设置 entrypoint 脚本权限
RUN chmod +x /entrypoint.sh

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3602/api/status')" || exit 1

# 使用 entrypoint 脚本
ENTRYPOINT ["/entrypoint.sh"]

# 默认命令
CMD ["python", "main.py"]
