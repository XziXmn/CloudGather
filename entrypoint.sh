#!/bin/bash
set -e

# 显示版本信息
echo "=========================================="
echo "  CloudGather (云集) v${APP_VERSION:-0.3.8}"
echo "  媒体文件同步工具"
echo "=========================================="
echo ""

# 显示时区信息（通过环境变量 TZ 设置）
echo "⏰ 时区: ${TZ:-UTC}"
echo "   当前时间: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# 获取 PUID 和 PGID（默认值：1000）
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "👤 用户权限信息:"
echo "   容器当前用户: $(id -u):$(id -g)"
echo "   配置 PUID: ${PUID}"
echo "   配置 PGID: ${PGID}"
echo ""

# 创建运行用户组和用户（如果不存在）
if ! getent group ${PGID} > /dev/null 2>&1; then
    groupadd -g ${PGID} cloudgather
fi

if ! getent passwd ${PUID} > /dev/null 2>&1; then
    useradd -u ${PUID} -g ${PGID} -d /app -s /bin/bash cloudgather
fi

# 设置配置目录权限
chown -R ${PUID}:${PGID} /app/config 2>/dev/null || true

echo "   实际运行用户: ${PUID}:${PGID}"
echo ""

# 显示配置信息
echo "⚙️  配置信息:"
echo "   配置路径: /app/config"
echo "   监听端口: 8080"
echo "   Docker 模式: 已启用"
echo ""
echo "=========================================="
echo "  启动应用..."
echo "=========================================="
echo ""

# 使用 gosu 以指定用户身份运行应用
exec gosu ${PUID}:${PGID} "$@"
