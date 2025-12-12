#!/bin/bash
set -e

# 显示版本信息
echo "=========================================="
echo "  CloudGather (云集) v${APP_VERSION:-0.2}"
echo "  媒体文件同步工具"
echo "=========================================="
echo ""

# 设置时区
echo "⏰ 设置时区: ${TZ}"
ln -snf /usr/share/zoneinfo/$TZ /etc/localtime
echo $TZ > /etc/timezone
echo "   当前时间: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# 获取 PUID 和 PGID（默认值：1000）
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "👤 用户权限设置:"
echo "   PUID: ${PUID}"
echo "   PGID: ${PGID}"

# 创建用户组（如果不存在）
if ! getent group cloudgather > /dev/null 2>&1; then
    groupadd -g ${PGID} cloudgather
    echo "   ✓ 创建用户组: cloudgather (GID: ${PGID})"
fi

# 创建用户（如果不存在）
if ! id cloudgather > /dev/null 2>&1; then
    useradd -u ${PUID} -g ${PGID} -M -s /bin/bash cloudgather
    echo "   ✓ 创建用户: cloudgather (UID: ${PUID})"
fi

# 设置目录权限
echo ""
echo "📁 设置目录权限..."
chown -R ${PUID}:${PGID} /app/config 2>/dev/null || true
echo "   ✓ /app/config 权限已设置"

# 显示配置信息
echo ""
echo "⚙️  配置信息:"
echo "   配置路径: /app/config"
echo "   监听端口: 8080"
echo "   Docker 模式: 已启用"
echo ""
echo "=========================================="
echo "  启动应用..."
echo "=========================================="
echo ""

# 切换到指定用户运行应用
exec gosu ${PUID}:${PGID} "$@"
