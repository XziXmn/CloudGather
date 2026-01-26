// 日志窗口相关逻辑
const logWindows = new Map(); // logId -> element
const logCache = {}; // 本地缓存各日志内容
const logAutoScroll = {}; // 记录每个日志窗口是否自动滚动

function openLogWindow(logId, title) {
    if (logWindows.has(logId)) {
        logWindows.get(logId).classList.add('show');
        return;
    }
    const root = document.getElementById('log-root');
    const modal = document.createElement('div');
    modal.className = 'log-modal show';
    modal.dataset.logId = logId;
    modal.innerHTML = `
        <div class="log-card" onclick="event.stopPropagation()">
            <div class="log-header">
                <div class="flex items-center gap-2">
                    <i class="fas fa-terminal"></i>
                    <span class="font-bold">${title}</span>
                </div>
                <div class="flex items-center gap-2 text-sm">
                    <button class="btn btn-secondary" onclick="clearLogs('${logId}')"><i class="fas fa-eraser"></i>清空</button>
                    <button class="btn btn-secondary" onclick="closeLogWindow('${logId}')"><i class="fas fa-times"></i>关闭</button>
                </div>
            </div>
            <div id="log-content-${logId}" class="log-content"><div class="text-gray-400">加载中...</div></div>
        </div>
    `;
    modal.addEventListener('click', (e) => { if (e.target === modal) closeLogWindow(logId); });
    root.appendChild(modal);
    logWindows.set(logId, modal);
    
    // 初始化为自动滚动
    logAutoScroll[logId] = true;
    
    // 添加滚动监听：检测用户是否向上滚动
    const container = modal.querySelector(`#log-content-${logId}`);
    if (container) {
        container.addEventListener('scroll', () => {
            const isAtBottom = container.scrollHeight - (container.scrollTop + container.clientHeight) < 50;
            logAutoScroll[logId] = isAtBottom;
        });
    }
    
    loadLogsFor(logId);
}

function closeLogWindow(logId) {
    const modal = logWindows.get(logId);
    if (modal) {
        modal.remove();
        logWindows.delete(logId);
        delete logAutoScroll[logId]; // 清理滚动状态
    }
}

async function loadLogsFor(logId) {
    try {
        const response = await fetch(`/api/logs?task_id=${logId}`);
        const data = await response.json();
        const logs = data.logs || [];
        logCache[logId] = logs;
        const container = document.getElementById(`log-content-${logId}`);
        if (!container) return;
        if (logs.length === 0) {
            container.innerHTML = '<div class="text-gray-400">暂无日志</div>';
        } else {
            container.innerHTML = logs.map(log => `<div class="mb-1">${log}</div>`).join('');
            // 智能滚动：只有当 logAutoScroll[logId] 为 true 时才自动滚动到底部
            if (logAutoScroll[logId] !== false) {
                container.scrollTop = container.scrollHeight;
            }
        }
    } catch (error) {
        console.error('加载日志失败:', error);
    }
}

async function clearLogs(logId) {
    try {
        await fetch(`/api/logs/clear?task_id=${logId}`, { method: 'POST' });
        logCache[logId] = [];
        const container = document.getElementById(`log-content-${logId}`);
        if (container) container.innerHTML = '<div class="text-gray-400">已清空</div>';
        showNotification('日志已清空', 'success');
    } catch (error) {
        console.error('清空日志失败:', error);
        showNotification('清空失败', 'error');
    }
}
