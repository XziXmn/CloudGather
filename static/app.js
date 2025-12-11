// CloudGather v2.4 - 蓝粉白纯色 + 独立日志窗 + MD侧边栏
let currentEditingTaskId = null;
let lastTasksData = null;
let tasksCache = [];
let queueCache = [];
let currentView = 'dashboard';
const logWindows = new Map(); // logId -> element
const logCache = {}; // 本地缓存各日志内容

function applyTheme(theme) {
    document.body.setAttribute('data-theme', theme);
    const toggle = document.getElementById('themeToggle');
    if (toggle) {
        toggle.innerHTML = theme === 'light'
            ? '<i class="fas fa-sun"></i><span class="hidden sm:inline">浅色</span>'
            : '<i class="fas fa-moon"></i><span class="hidden sm:inline">深色</span>';
    }
    localStorage.setItem('cg-theme', theme);
}

function toggleTheme() {
    const next = document.body.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    applyTheme(next);
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mask = document.getElementById('sidebar-mask');
    if (window.innerWidth <= 1024) {
        sidebar.classList.toggle('show');
        if (mask) mask.style.display = sidebar.classList.contains('show') ? 'block' : 'none';
        return;
    }
    sidebar.classList.toggle('collapsed');
}

function setActiveNav(view, navEl = null) {
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
    const el = navEl || document.querySelector(`.nav-item[data-view="${view}"]`);
    if (el) el.classList.add('active');
}

function switchView(view, navEl = null) {
    currentView = view;
    setActiveNav(view, navEl);
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const target = document.getElementById(`view-${view}`);
    if (target) target.classList.add('active');

    if (view === 'tasks') {
        loadTasks();
    } else if (view === 'settings') {
        loadSystemStatus();
    } else if (view === 'dashboard') {
        loadSystemStatus();
        loadTasks();
    }
}

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
    loadLogsFor(logId);
}

function closeLogWindow(logId) {
    const modal = logWindows.get(logId);
    if (modal) {
        modal.remove();
        logWindows.delete(logId);
    }
}

async function loadSystemStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        document.getElementById('stat-total').textContent = data.task_count;
        document.getElementById('stat-queued').textContent = data.queue_size;
        document.getElementById('stat-scheduler').textContent = data.running ? '运行中' : '异常';

        if (data.system) {
            const cpu = Math.round(data.system.cpu_percent);
            const memPercent = Math.round(data.system.memory_percent);
            const memUsed = formatBytes(data.system.memory_used);
            const memTotal = formatBytes(data.system.memory_total);
            document.getElementById('cpu-percent').textContent = cpu + '%';
            document.getElementById('cpu-progress').style.width = cpu + '%';
            document.getElementById('memory-text').textContent = `${memUsed} / ${memTotal}`;
            document.getElementById('memory-percent').textContent = memPercent + '%';
            document.getElementById('memory-progress').style.width = memPercent + '%';
        }
        document.getElementById('config-path').textContent = data.config_path;
        document.getElementById('is-docker').textContent = data.is_docker ? 'Docker' : '本地';
    } catch (error) {
        console.error('加载系统状态失败:', error);
    }
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function formatInterval(seconds) {
    if (seconds < 60) return `${seconds}秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins > 0 ? `${hours}小时${mins}分钟` : `${hours}小时`;
}

function getStatusBadge(status) {
    const badges = {
        'IDLE': '<span class="status-badge status-idle"><i class="fas fa-circle mr-1"></i>空闲</span>',
        'QUEUED': '<span class="status-badge status-queued"><i class="fas fa-clock mr-1"></i>队列中</span>',
        'RUNNING': '<span class="status-badge status-running"><i class="fas fa-spinner fa-spin mr-1"></i>运行中</span>',
        'ERROR': '<span class="status-badge status-error"><i class="fas fa-exclamation-circle mr-1"></i>错误</span>'
    };
    return badges[status] || badges['IDLE'];
}

async function loadTasks() {
    try {
        const response = await fetch('/api/tasks');
        const data = await response.json();
        const tasks = data.tasks || [];
        tasksCache = tasks;
        const running = tasks.filter(t => t.status === 'RUNNING').length;
        document.getElementById('stat-running').textContent = running;
        const currentData = JSON.stringify(tasks);
        if (currentData !== lastTasksData) {
            renderTasks(tasks);
            lastTasksData = currentData;
        } else {
            updateTaskStatus(tasks);
        }
    } catch (error) {
        console.error('加载任务失败:', error);
    }
}

function updateTaskStatus(tasks) {
    tasks.forEach(task => {
        const taskCard = document.querySelector(`[data-task-id="${task.id}"]`);
        if (taskCard) {
            const statusBadge = taskCard.querySelector('.status-badge-container');
            if (statusBadge) statusBadge.innerHTML = getStatusBadge(task.status);
        }
    });
}

function renderTasks(tasks) {
    const container = document.getElementById('tasks-container');
    if (tasks.length === 0) {
        container.innerHTML = '<div class="text-center py-12 text-gray-400"><i class="fas fa-inbox text-5xl mb-4"></i><p>暂无任务</p></div>';
        return;
    }
    container.innerHTML = tasks.map(task => `
        <div class="task-card" data-task-id="${task.id}">
            <div class="flex items-start justify-between mb-3">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-1">
                        <h4 class="text-lg font-bold">${task.name}</h4>
                        <span class="status-badge-container">${getStatusBadge(task.status)}</span>
                        ${task.enabled ? '<span class="text-xs px-2 py-1 bg-green-100 text-green-700 rounded">已启用</span>' : '<span class="text-xs px-2 py-1 bg-gray-200 text-gray-600 rounded">已禁用</span>'}
                    </div>
                </div>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm text-gray-600">
                <div class="flex items-center"><i class="fas fa-folder-open text-blue-500 mr-2"></i><span class="font-mono">${task.source_path}</span></div>
                <div class="flex items-center"><i class="fas fa-folder text-green-500 mr-2"></i><span class="font-mono">${task.target_path}</span></div>
                <div class="flex items-center"><i class="fas fa-clock text-yellow-500 mr-2"></i><span>间隔：${formatInterval(task.interval)}</span></div>
                <div class="flex items-center gap-2">
                    ${task.recursive ? '<span class="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded"><i class="fas fa-code-branch mr-1"></i>递归</span>' : ''}
                    ${task.verify_md5 ? '<span class="text-xs px-2 py-1 bg-purple-100 text-purple-700 rounded"><i class="fas fa-shield-alt mr-1"></i>MD5</span>' : ''}
                    ${task.last_run_time ? `<span class="text-xs text-gray-500"><i class="fas fa-history mr-1"></i>${new Date(task.last_run_time).toLocaleString()}</span>` : ''}
                </div>
            </div>
            <div class="flex gap-2 flex-wrap mt-3">
                <button onclick="triggerTask('${task.id}')" class="btn btn-primary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}><i class="fas fa-play"></i>立即运行</button>
                <button onclick="openLogWindow('${task.id}', '${task.name.replace(/'/g, "\''")} 日志')" class="btn btn-secondary text-sm"><i class="fas fa-terminal"></i>查看日志</button>
                <button onclick="editTask('${task.id}')" class="btn btn-secondary text-sm"><i class="fas fa-edit"></i>编辑</button>
                <button onclick="deleteTask('${task.id}', '${task.name.replace(/'/g, "\''")}')" class="btn btn-secondary text-sm border-red-500 text-red-500"><i class="fas fa-trash"></i>删除</button>
            </div>
        </div>
    `).join('');
}

async function loadQueue(updateTab = true) {
    try {
        const response = await fetch('/api/queue');
        const data = await response.json();
        const queue = data.queue || [];
        queueCache = queue;
        if (updateTab) renderQueueTab(queue);
    } catch (error) {
        console.error('加载队列失败:', error);
    }
}

function renderQueueTab(queue) {
    const container = document.getElementById('queue-container');
    if (queue.length === 0) {
        container.innerHTML = '<div class="text-center py-12 text-gray-400"><i class="fas fa-hourglass-half text-5xl mb-4"></i><p>队列为空</p></div>';
        return;
    }
    container.innerHTML = queue.map((task, index) => `
        <div class="task-card">
            <div class="flex items-center gap-4">
                <div class="h-10 w-10 rounded-full bg-yellow-100 flex items-center justify-center text-yellow-700 font-bold">${index + 1}</div>
                <div class="flex-1">
                    <h4 class="font-bold">${task.name}</h4>
                    <p class="text-sm text-gray-500">${task.source_path} → ${task.target_path}</p>
                </div>
                ${getStatusBadge(task.status)}
            </div>
        </div>
    `).join('');
}

function renderQueueModal(queue = []) {
    const modalCount = document.getElementById('queue-modal-count');
    const modalContainer = document.getElementById('queue-modal-container');
    modalCount.textContent = `${queue.length} 条`;
    if (queue.length === 0) {
        modalContainer.innerHTML = '<div class="text-gray-500 text-center py-6">队列为空</div>';
        return;
    }
    modalContainer.innerHTML = queue.map((task, index) => `
        <div class="task-card">
            <div class="flex items-center gap-4">
                <div class="h-10 w-10 rounded-full bg-yellow-100 flex items-center justify-center text-yellow-700 font-bold">${index + 1}</div>
                <div class="flex-1">
                    <h4 class="font-bold">${task.name}</h4>
                    <p class="text-sm text-gray-500">${task.source_path} → ${task.target_path}</p>
                </div>
                ${getStatusBadge(task.status)}
            </div>
        </div>
    `).join('');
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
            container.scrollTop = container.scrollHeight;
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

function showNotification(message, type = 'info') {
    const colors = { success: 'bg-green-500', error: 'bg-red-500', warning: 'bg-yellow-500', info: 'bg-blue-500' };
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 ${colors[type]} text-white px-6 py-3 rounded-lg shadow-lg z-50`;
    notification.textContent = message;
    document.body.appendChild(notification);
    setTimeout(() => { notification.style.opacity = '0'; setTimeout(() => notification.remove(), 300); }, 3000);
}

function showAddTaskModal() {
    currentEditingTaskId = null;
    document.getElementById('modalTitle').textContent = '添加任务';
    document.getElementById('taskForm').reset();
    document.getElementById('taskId').value = '';
    document.getElementById('taskRecursive').checked = true;
    document.getElementById('taskEnabled').checked = true;
    document.getElementById('taskModal').classList.add('show');
}

function closeTaskModal() {
    document.getElementById('taskModal').classList.remove('show');
    currentEditingTaskId = null;
}

async function editTask(taskId) {
    try {
        const response = await fetch('/api/tasks');
        const data = await response.json();
        const task = data.tasks.find(t => t.id === taskId);
        if (!task) { showNotification('任务不存在', 'error'); return; }
        currentEditingTaskId = taskId;
        document.getElementById('modalTitle').textContent = '编辑任务';
        document.getElementById('taskId').value = taskId;
        document.getElementById('taskName').value = task.name;
        document.getElementById('taskSource').value = task.source_path;
        document.getElementById('taskTarget').value = task.target_path;
        document.getElementById('taskInterval').value = task.interval;
        document.getElementById('taskRecursive').checked = task.recursive;
        document.getElementById('taskMd5').checked = task.verify_md5;
        document.getElementById('taskEnabled').checked = task.enabled;
        document.getElementById('taskModal').classList.add('show');
    } catch (error) {
        console.error('加载任务失败:', error);
        showNotification('加载任务失败', 'error');
    }
}

document.getElementById('taskForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const taskData = {
        name: document.getElementById('taskName').value,
        source_path: document.getElementById('taskSource').value,
        target_path: document.getElementById('taskTarget').value,
        interval: parseInt(document.getElementById('taskInterval').value),
        recursive: document.getElementById('taskRecursive').checked,
        verify_md5: document.getElementById('taskMd5').checked,
        enabled: document.getElementById('taskEnabled').checked
    };
    try {
        let response;
        if (currentEditingTaskId) {
            response = await fetch(`/api/tasks/${currentEditingTaskId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(taskData) });
        } else {
            response = await fetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(taskData) });
        }
        const result = await response.json();
        if (result.success) {
            showNotification(currentEditingTaskId ? '任务已更新' : '任务已添加', 'success');
            closeTaskModal();
            loadTasks();
        } else {
            showNotification(result.error || '保存失败', 'error');
        }
    } catch (error) {
        console.error('保存任务失败:', error);
        showNotification('保存任务失败', 'error');
    }
});

async function deleteTask(taskId, taskName) {
    if (!confirm(`确定要删除任务"${taskName}"吗？`)) return;
    try {
        const response = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
        const result = await response.json();
        if (result.success) {
            showNotification('任务已删除', 'success');
            loadTasks();
        } else {
            showNotification(result.error || '删除失败', 'error');
        }
    } catch (error) {
        console.error('删除任务失败:', error);
        showNotification('删除任务失败', 'error');
    }
}

async function triggerTask(taskId) {
    try {
        const response = await fetch(`/api/tasks/${taskId}/trigger`, { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            showNotification('任务已触发', 'success');
            loadTasks();
        } else {
            showNotification(result.error || '触发失败', 'error');
        }
    } catch (error) {
        console.error('触发任务失败:', error);
        showNotification('触发任务失败', 'error');
    }
}

async function startScheduler() { showNotification('调度器默认常驻运行，无需手动启动', 'info'); }
async function stopScheduler() { showNotification('调度器默认开启，不提供停用入口', 'info'); }

function openRunningModal() {
    const running = (tasksCache || []).filter(t => t.status === 'RUNNING');
    const countEl = document.getElementById('running-count');
    const container = document.getElementById('running-container');
    if (countEl) countEl.textContent = `${running.length} 条`;
    if (container) {
        if (running.length === 0) {
            container.innerHTML = '<div class="text-gray-500 text-center py-6">暂无运行中的任务</div>';
        } else {
            container.innerHTML = running.map(task => `
                <div class="task-card">
                    <div class="flex items-center justify-between mb-2"><div class="font-bold">${task.name}</div>${getStatusBadge(task.status)}</div>
                    <p class="text-sm text-gray-500">${task.source_path} → ${task.target_path}</p>
                    ${task.last_run_time ? `<p class="text-xs text-gray-400 mt-1"><i class="fas fa-clock mr-1"></i>${new Date(task.last_run_time).toLocaleString()}</p>` : ''}
                </div>
            `).join('');
        }
    }
    document.getElementById('runningModal').classList.add('show');
}

async function openQueueModal() {
    await loadQueue(false);
    renderQueueModal(queueCache);
    document.getElementById('queueModal').classList.add('show');
}

function closeOverlay(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('show');
}

(function init() {
    const savedTheme = localStorage.getItem('cg-theme') || 'light';
    applyTheme(savedTheme);
    document.addEventListener('DOMContentLoaded', () => {
        loadSystemStatus();
        loadTasks();
        loadQueue(false);
        setInterval(() => {
            loadSystemStatus();
            loadTasks();
            if (logWindows.size > 0) {
                logWindows.forEach((_, logId) => loadLogsFor(logId));
            }
            if (currentView === 'queue') loadQueue();
        }, 3000);
        ['taskModal', 'runningModal', 'queueModal'].forEach(id => {
            const modal = document.getElementById(id);
            if (modal) modal.addEventListener('click', (e) => { if (e.target.id === id) modal.classList.remove('show'); });
        });
    });
})();
