// CloudGather - 蓝粉白纯色 + 独立日志窗 + MD侧边栏 + Cron 调度 + 一言
let currentEditingTaskId = null;
let lastTasksData = null;
let tasksCache = [];
let queueCache = [];
let currentView = 'dashboard';
const logWindows = new Map(); // logId -> element
const logCache = {}; // 本地缓存各日志内容
const logAutoScroll = {}; // 记录每个日志窗口是否自动滚动
let taskFormDirty = false; // 表单是否已修改
let directoryCache = {}; // 目录缓存

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
    
    // 只在移动端执行切换逻辑
    if (window.innerWidth <= 1024) {
        sidebar.classList.toggle('show');
        if (mask) {
            mask.classList.toggle('show');
        }
    }
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
            
            // 磁盘信息
            if (data.system.disk_total) {
                const diskPercent = Math.round(data.system.disk_percent);
                const diskUsed = formatBytes(data.system.disk_used);
                const diskTotal = formatBytes(data.system.disk_total);
                document.getElementById('disk-text').textContent = `${diskUsed} / ${diskTotal}`;
                document.getElementById('disk-percent').textContent = diskPercent + '%';
                document.getElementById('disk-progress').style.width = diskPercent + '%';
            }
        }
        
        // 最近执行任务
        if (data.recent_tasks && data.recent_tasks.length > 0) {
            const recentHtml = data.recent_tasks.map(t => {
                const time = t.last_run_time ? new Date(t.last_run_time).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}) : '-';
                return `<div class="flex items-center justify-between py-1 border-b border-gray-100 dark:border-gray-700 last:border-0">
                    <span class="truncate flex-1" title="${t.name}">${t.name}</span>
                    <span class="text-xs text-gray-500 ml-2">${time}</span>
                </div>`;
            }).join('');
            document.getElementById('recent-tasks').innerHTML = recentHtml;
        } else {
            document.getElementById('recent-tasks').innerHTML = '<p class="text-gray-500">暂无最近执行记录</p>';
        }
        
        document.getElementById('config-path').textContent = data.config_path;
        document.getElementById('is-docker').textContent = data.is_docker ? 'Docker' : '本地';
        document.getElementById('app-version').textContent = 'v' + (data.version || 'Unknown');  // 显示版本号
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
    container.innerHTML = tasks.map(task => {
        // 根据调度类型显示不同信息
        let scheduleInfo = '';
        if (task.schedule_type === 'CRON') {
            scheduleInfo = `<div class="flex items-center"><i class="fas fa-calendar-alt text-purple-500 mr-2"></i><code class="px-2 py-1 bg-gray-100 rounded text-xs font-mono">${task.cron_expression}</code></div>`;
        } else {
            scheduleInfo = `<div class="flex items-center"><i class="fas fa-clock text-yellow-500 mr-2"></i><span>间隔：${formatInterval(task.interval)}</span></div>`;
        }
        
        // 渲染进度条（仅当任务正在运行时）
        let progressBar = '';
        if (task.status === 'RUNNING' && task.progress) {
            const p = task.progress;
            progressBar = `
                <div class="mt-3 mb-2">
                    <div class="flex items-center justify-between text-xs mb-1">
                        <span class="text-gray-600">进度: ${p.done} / ${p.total} 文件</span>
                        <span class="text-blue-600 font-bold">${p.percent}%</span>
                    </div>
                    <div class="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div class="h-full bg-blue-500 transition-all" style="width: ${p.percent}%"></div>
                    </div>
                    <div class="flex items-center gap-3 text-xs text-gray-500 mt-1">
                        <span><i class="fas fa-check text-green-500 mr-1"></i>成功: ${p.success}</span>
                        <span><i class="fas fa-forward text-yellow-500 mr-1"></i>跳过: ${p.skipped}</span>
                        <span><i class="fas fa-times text-red-500 mr-1"></i>失败: ${p.failed}</span>
                    </div>
                </div>
            `;
        }
        
        // 渲染最终统计信息（仅当任务有执行结果时）
        let statsInfo = '';
        if (task.stats) {
            const s = task.stats;
            statsInfo = `
                <div class="mt-2 p-2 bg-gray-50 dark:bg-gray-800 rounded text-xs">
                    <div class="flex items-center gap-3 text-gray-600 dark:text-gray-400">
                        <span><i class="fas fa-file mr-1"></i>总数: ${s.total}</span>
                        <span><i class="fas fa-check text-green-500 mr-1"></i>成功: ${s.success}</span>
                        <span><i class="fas fa-forward text-yellow-500 mr-1"></i>跳过: ${s.skipped}</span>
                        <span><i class="fas fa-times text-red-500 mr-1"></i>失败: ${s.failed}</span>
                    </div>
                </div>
            `;
        }
        
        return `
        <div class="task-card" data-task-id="${task.id}">
            <div class="flex items-start justify-between mb-3">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-1">
                        <h4 class="text-lg font-bold">${task.name}</h4>
                        <span class="status-badge-container">${getStatusBadge(task.status)}</span>
                        ${task.is_slow_storage ? '<span class="text-xs px-2 py-1 bg-orange-100 text-orange-600 rounded" title="网络云盘优化"><i class="fas fa-hdd mr-1"></i>云盘</span>' : ''}
                    </div>
                </div>
                <div class="flex items-center gap-2" title="${task.enabled ? '任务已启用' : '任务已禁用'}">
                    <span class="text-sm text-gray-600">${task.enabled ? '已启用' : '已禁用'}</span>
                    <label class="toggle-switch">
                        <input type="checkbox" ${task.enabled ? 'checked' : ''} onchange="toggleTaskEnabled('${task.id}', this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
            <div class="mb-3">
                <div class="flex items-center text-sm text-gray-600">
                    <div class="flex items-center"><i class="fas fa-folder-open text-blue-500 mr-2"></i><span class="font-mono">${task.source_path}</span></div>
                    <span class="mx-1 text-gray-400">→</span>
                    <div class="flex items-center"><i class="fas fa-folder text-green-500 mr-2"></i><span class="font-mono">${task.target_path}</span></div>
                </div>
            </div>
            <div class="flex items-center gap-4 text-sm text-gray-600 mb-3">
                ${scheduleInfo}
                ${task.last_run_time ? `<span class="text-xs text-gray-500"><i class="fas fa-history mr-1"></i>上次: ${new Date(task.last_run_time).toLocaleString()}</span>` : ''}
                ${task.next_run_time ? `<span class="text-xs text-blue-600"><i class="fas fa-clock mr-1"></i>下次: ${new Date(task.next_run_time).toLocaleString()}</span>` : ''}
            </div>
            <div class="flex gap-2 flex-wrap mt-3">
                <button onclick="triggerTask('${task.id}')" class="btn btn-primary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}><i class="fas fa-play"></i>立即运行</button>
                <button onclick="openLogWindow('${task.id}', '${task.name.replace(/'/g, "''")} 日志')" class="btn btn-secondary text-sm"><i class="fas fa-terminal"></i>查看日志</button>
                <button onclick="showAdvancedTools('${task.id}')" class="btn btn-secondary text-sm"><i class="fas fa-wrench"></i>高级工具</button>
                <button onclick="editTask('${task.id}')" class="btn btn-secondary text-sm"><i class="fas fa-edit"></i>编辑</button>
                <button onclick="deleteTask('${task.id}', '${task.name.replace(/'/g, "''")}')" class="btn btn-secondary text-sm border-red-500 text-red-500"><i class="fas fa-trash"></i>删除</button>
            </div>
            ${progressBar}
            ${statsInfo}
        </div>
        `;
    }).join('');
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

function showNotification(message, type = 'info') {
    const colors = { success: 'bg-green-500', error: 'bg-red-500', warning: 'bg-yellow-500', info: 'bg-blue-500' };
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 ${colors[type]} text-white px-6 py-3 rounded-lg shadow-lg z-50`;
    notification.textContent = message;
    document.body.appendChild(notification);
    setTimeout(() => { notification.style.opacity = '0'; setTimeout(() => notification.remove(), 300); }, 3000);
}

function showAddTaskModal() {
    // 检查是否有草稿
    const draft = localStorage.getItem('task-draft');
    if (draft && !currentEditingTaskId) {
        if (confirm('检测到未保存的草稿，是否加载？')) {
            loadDraft();
            document.getElementById('taskModal').classList.add('show');
            return;
        } else {
            localStorage.removeItem('task-draft');
        }
    }
    
    currentEditingTaskId = null;
    taskFormDirty = false;
    document.getElementById('modalTitle').textContent = '添加任务';
    document.getElementById('taskForm').reset();
    document.getElementById('taskId').value = '';
    
    // 重置子规则按钮状态（默认启用「文件不存在」规则）
    ['ruleNotExists', 'ruleSizeDiff', 'ruleMtimeNewer'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) {
            // 默认启用「文件不存在」规则
            if (id === 'ruleNotExists') {
                btn.dataset.active = 'true';
                btn.style.borderColor = '#3b82f6';
                btn.style.background = '#eff6ff';
                btn.style.color = '#1e40af';
            } else {
                btn.dataset.active = 'false';
                btn.style.borderColor = '#e5e9f2';
                btn.style.background = 'transparent';
                btn.style.color = '#6b7280';
            }
        }
    });
    
    document.getElementById('taskModal').classList.add('show');
    
    // 初始化目录自动提示
    initDirectoryAutocomplete();
}

function loadDraft() {
    try {
        const draft = JSON.parse(localStorage.getItem('task-draft'));
        if (draft) {
            document.getElementById('taskName').value = draft.name || '';
            document.getElementById('taskSource').value = draft.source_path || '';
            document.getElementById('taskTarget').value = draft.target_path || '';
            document.getElementById('cronExpression').value = draft.cron_expression || '';
            document.getElementById('taskThreadCount').value = draft.thread_count || 1;
            
            // 恢复子规则状态
            const rules = {
                ruleNotExists: draft.rule_not_exists || false,
                ruleSizeDiff: draft.rule_size_diff || false,
                ruleMtimeNewer: draft.rule_mtime_newer || false
            };
            
            Object.keys(rules).forEach(id => {
                const btn = document.getElementById(id);
                if (btn && rules[id]) {
                    btn.dataset.active = 'true';
                    btn.style.borderColor = '#3b82f6';
                    btn.style.background = '#eff6ff';
                    btn.style.color = '#1e40af';
                }
            });
        }
    } catch (e) {
        console.error('加载草稿失败:', e);
    }
}

function saveDraft() {
    if (!taskFormDirty) return;
    const draft = {
        name: document.getElementById('taskName').value,
        source_path: document.getElementById('taskSource').value,
        target_path: document.getElementById('taskTarget').value,
        cron_expression: document.getElementById('cronExpression').value,
        thread_count: parseInt(document.getElementById('taskThreadCount').value) || 1,
        rule_not_exists: document.getElementById('ruleNotExists').dataset.active === 'true',
        rule_size_diff: document.getElementById('ruleSizeDiff').dataset.active === 'true',
        rule_mtime_newer: document.getElementById('ruleMtimeNewer').dataset.active === 'true'
    };
    localStorage.setItem('task-draft', JSON.stringify(draft));
}

function closeTaskModal() {
    // 默认保存草稿，不再提示
    if (taskFormDirty && !currentEditingTaskId) {
        saveDraft();
    }
    
    document.getElementById('taskModal').classList.remove('show');
    currentEditingTaskId = null;
    taskFormDirty = false;
    
    // 移除目录提示
    removeDirectoryAutocomplete();
}

// 切换子规则按钮状态
function toggleRule(button, ruleKey) {
    const isActive = button.dataset.active === 'true';
    
    if (isActive) {
        // 关闭
        button.dataset.active = 'false';
        button.style.borderColor = '#e5e9f2';
        button.style.background = 'transparent';
        button.style.color = '#6b7280';
    } else {
        // 启用
        button.dataset.active = 'true';
        button.style.borderColor = '#3b82f6';
        button.style.background = '#eff6ff';
        button.style.color = '#1e40af';
    }
    
    taskFormDirty = true;
}



// 加载一言（自动调用）
async function loadHitokoto() {
    const contentEl = document.getElementById('hitokoto-content');
    
    if (!contentEl) return;
    
    try {
        const response = await fetch('https://v1.hitokoto.cn/');
        const data = await response.json();
        
        // 显示一言内容
        const text = data.hitokoto || '今天也要加油哦！';
        const from = data.from ? ` —— ${data.from}` : '';
        contentEl.textContent = `${text}${from}`;
        
    } catch (error) {
        console.error('加载一言失败:', error);
        contentEl.textContent = '保持热爱，奔赴山海';
    }
}

// 页面加载时自动获取一言
window.addEventListener('DOMContentLoaded', () => {
    loadHitokoto();
    // 每30分钟更新一次一言
    setInterval(loadHitokoto, 30 * 60 * 1000);
});

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
        
        // 设置子规则按钮状态
        const rules = {
            ruleNotExists: task.rule_not_exists || false,
            ruleSizeDiff: task.rule_size_diff || false,
            ruleMtimeNewer: task.rule_mtime_newer || false
        };
        
        Object.keys(rules).forEach(id => {
            const btn = document.getElementById(id);
            if (btn) {
                if (rules[id]) {
                    btn.dataset.active = 'true';
                    btn.style.borderColor = '#3b82f6';
                    btn.style.background = '#eff6ff';
                    btn.style.color = '#1e40af';
                } else {
                    btn.dataset.active = 'false';
                    btn.style.borderColor = '#e5e9f2';
                    btn.style.background = 'transparent';
                    btn.style.color = '#6b7280';
                }
            }
        });
        
        // 线程数
        document.getElementById('taskThreadCount').value = task.thread_count || 1;
        
        // 慢速存储选项
        const slowStorageCheckbox = document.getElementById('isSlowStorage');
        if (slowStorageCheckbox) {
            slowStorageCheckbox.checked = task.is_slow_storage || false;
        }
        
        // 填充 Cron 表达式
        document.getElementById('cronExpression').value = task.cron_expression || '';
        validateCron();
        
        document.getElementById('taskModal').classList.add('show');
        initDirectoryAutocomplete();
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
        schedule_type: 'CRON',  // 只支持 Cron 模式
        cron_expression: document.getElementById('cronExpression').value.trim(),
        thread_count: parseInt(document.getElementById('taskThreadCount').value) || 1,
        rule_not_exists: document.getElementById('ruleNotExists').dataset.active === 'true',
        rule_size_diff: document.getElementById('ruleSizeDiff').dataset.active === 'true',
        rule_mtime_newer: document.getElementById('ruleMtimeNewer').dataset.active === 'true',
        is_slow_storage: document.getElementById('isSlowStorage') ? document.getElementById('isSlowStorage').checked : false,
        enabled: true  // 默认启用，后续可通过开关控制
    };
    
    if (!taskData.cron_expression) {
        showNotification('Cron 表达式不能为空', 'error');
        return;
    }
    
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
            // 清除草稿
            localStorage.removeItem('task-draft');
            taskFormDirty = false;
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

// 监听表单变化
function initFormChangeListener() {
    const inputs = ['taskName', 'taskSource', 'taskTarget', 'cronExpression', 'taskThreadCount'];
    inputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', () => { taskFormDirty = true; });
            el.addEventListener('change', () => { taskFormDirty = true; });
        }
    });
}

// 目录自动提示功能
let currentDropdown = null;
let currentInputField = null;

function initDirectoryAutocomplete() {
    const sourceInput = document.getElementById('taskSource');
    const targetInput = document.getElementById('taskTarget');
    
    if (sourceInput) setupDirectoryInput(sourceInput);
    if (targetInput) setupDirectoryInput(targetInput);
}

function setupDirectoryInput(input) {
    input.addEventListener('focus', () => {
        currentInputField = input;
        showDirectoryDropdown(input);
    });
    
    input.addEventListener('input', debounce(() => {
        showDirectoryDropdown(input);
    }, 300));
    
    input.addEventListener('blur', () => {
        // 延迟移除，以便点击下拉框
        setTimeout(() => {
            if (currentInputField === input) {
                removeDirectoryDropdown();
                currentInputField = null;
            }
        }, 200);
    });
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

async function showDirectoryDropdown(input) {
    const path = input.value.trim() || '/';
    
    try {
        const response = await fetch(`/api/directories?path=${encodeURIComponent(path)}`);
        const data = await response.json();
        
        if (!data.success && data.error) {
            // 如果有错误，不显示下拉框
            removeDirectoryDropdown();
            return;
        }
        
        const directories = data.directories || [];
        if (directories.length === 0 && !data.parent_path) {
            removeDirectoryDropdown();
            return;
        }
        
        renderDirectoryDropdown(input, directories, data.current_path, data.parent_path);
    } catch (error) {
        console.error('获取目录失败:', error);
        removeDirectoryDropdown();
    }
}

function renderDirectoryDropdown(input, directories, currentPath, parentPath) {
    removeDirectoryDropdown();
    
    const dropdown = document.createElement('div');
    dropdown.className = 'directory-dropdown';
    dropdown.style.cssText = `
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        max-height: 300px;
        overflow-y: auto;
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.15);
        z-index: 1000;
        margin-top: 4px;
    `;
    
    // 添加当前路径显示
    if (currentPath) {
        const pathInfo = document.createElement('div');
        pathInfo.className = 'px-3 py-2 text-xs text-gray-500 border-b border-gray-200 font-mono';
        pathInfo.textContent = `当前: ${currentPath}`;
        dropdown.appendChild(pathInfo);
    }
    
    // 添加返回上一级
    if (parentPath && parentPath !== currentPath) {
        const parentItem = createDirectoryItem('📁 ..',  parentPath, input);
        parentItem.style.fontWeight = 'bold';
        dropdown.appendChild(parentItem);
    }
    
    // 添加子目录
    directories.forEach(dir => {
        const item = createDirectoryItem('📂 ' + dir.name, dir.path, input);
        dropdown.appendChild(item);
    });
    
    if (directories.length === 0 && (!parentPath || parentPath === currentPath)) {
        const emptyItem = document.createElement('div');
        emptyItem.className = 'px-3 py-2 text-sm text-gray-400 text-center';
        emptyItem.textContent = '此目录下无子目录';
        dropdown.appendChild(emptyItem);
    }
    
    // 将下拉框附加到 input 的父元素
    const parent = input.parentElement;
    parent.style.position = 'relative';
    parent.appendChild(dropdown);
    
    currentDropdown = dropdown;
}

function createDirectoryItem(text, path, input) {
    const item = document.createElement('div');
    item.className = 'px-3 py-2 text-sm cursor-pointer hover:bg-blue-50 transition-colors';
    item.textContent = text;
    item.style.cursor = 'pointer';
    
    item.addEventListener('mousedown', (e) => {
        e.preventDefault(); // 防止 input blur
    });
    
    item.addEventListener('click', () => {
        input.value = path;
        taskFormDirty = true;
        removeDirectoryDropdown();
        input.focus();
        // 重新加载目录
        setTimeout(() => showDirectoryDropdown(input), 100);
    });
    
    return item;
}

function removeDirectoryDropdown() {
    if (currentDropdown) {
        currentDropdown.remove();
        currentDropdown = null;
    }
}

function removeDirectoryAutocomplete() {
    removeDirectoryDropdown();
    currentInputField = null;
}

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

async function toggleTaskEnabled(taskId, enabled) {
    try {
        const response = await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        });
        const result = await response.json();
        if (result.success) {
            showNotification(enabled ? '任务已启用' : '任务已禁用', 'success');
            loadTasks();
        } else {
            showNotification(result.error || '操作失败', 'error');
            // 恢复原来的状态
            loadTasks();
        }
    } catch (error) {
        console.error('切换任务状态失败:', error);
        showNotification('操作失败', 'error');
        loadTasks();
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

// ========== Cron 相关功能 ==========

// Cron 验证
let cronValidationTimeout = null;
async function validateCron() {
    clearTimeout(cronValidationTimeout);
    const expression = document.getElementById('cronExpression').value.trim();
    const validationDiv = document.getElementById('cronValidation');
    
    if (!expression) {
        validationDiv.innerHTML = '';
        return;
    }
    
    cronValidationTimeout = setTimeout(async () => {
        try {
            const response = await fetch('/api/cron/validate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ expression })
            });
            const data = await response.json();
            
            if (data.valid) {
                validationDiv.innerHTML = `<span class="text-green-600">✓ ${data.description}</span>`;
            } else {
                validationDiv.innerHTML = `<span class="text-red-600">✗ ${data.error}</span>`;
            }
        } catch (error) {
            validationDiv.innerHTML = `<span class="text-red-600">✗ 验证失败</span>`;
        }
    }, 500);
}

// 显示 Cron 预设
let cronPresetsCache = null;
async function showCronPresets() {
    const presetList = document.getElementById('cronPresetList');
    const container = presetList.querySelector('div');
    
    if (presetList.style.display === 'block') {
        presetList.style.display = 'none';
        return;
    }
    
    if (!cronPresetsCache) {
        try {
            const response = await fetch('/api/cron/presets');
            const data = await response.json();
            cronPresetsCache = data.presets || [];
        } catch (error) {
            showNotification('加载预设失败', 'error');
            return;
        }
    }
    
    container.innerHTML = cronPresetsCache.map(preset => `
        <div class="px-3 py-2 bg-white hover:bg-blue-50 rounded cursor-pointer text-sm transition-colors" onclick="selectCronPreset('${preset.expression}')">
            <div class="flex items-center justify-between">
                <span class="font-semibold">${preset.name}</span>
                <code class="text-xs bg-gray-100 px-2 py-1 rounded">${preset.expression}</code>
            </div>
            <div class="text-xs text-gray-500 mt-1">${preset.description}</div>
        </div>
    `).join('');
    
    presetList.style.display = 'block';
}

function selectCronPreset(expression) {
    document.getElementById('cronExpression').value = expression;
    document.getElementById('cronPresetList').style.display = 'none';
    validateCron();
    taskFormDirty = true;
}

// 随机生成 Cron
async function generateRandomCron() {
    const patterns = ['hourly', 'daily', 'night'];
    const randomPattern = patterns[Math.floor(Math.random() * patterns.length)];
    
    try {
        const response = await fetch(`/api/cron/random?pattern=${randomPattern}`);
        const data = await response.json();
        
        document.getElementById('cronExpression').value = data.expression;
        validateCron();
        showNotification(`随机生成: ${data.description}`, 'success');
        taskFormDirty = true;
    } catch (error) {
        showNotification('生成失败', 'error');
    }
}

// 高级工具功能
function showAdvancedTools(taskId) {
    const task = tasksCache.find(t => t.id === taskId);
    if (!task) {
        showNotification('任务不存在', 'error');
        return;
    }
    
    // 创建高级工具弹窗
    const modal = document.createElement('div');
    modal.className = 'overlay-modal show';
    modal.id = 'advancedToolsModal';
    modal.innerHTML = `
        <div class="modal-card card" onclick="event.stopPropagation()">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2">
                    <i class="fas fa-wrench text-blue-500 text-xl"></i>
                    <h3 class="text-xl font-bold">高级工具</h3>
                </div>
                <button class="btn btn-secondary text-sm" onclick="closeAdvancedTools()"><i class="fas fa-times"></i>关闭</button>
            </div>
            <div class="mb-4">
                <p class="text-sm text-gray-600 mb-2">任务: <span class="font-bold">${task.name}</span></p>
                <p class="text-xs text-gray-500">${task.source_path} → ${task.target_path}</p>
            </div>
            <div class="space-y-3">
                <div class="border border-gray-200 rounded-lg p-4 hover:border-blue-300 transition-colors">
                    <div class="flex items-start gap-3">
                        <i class="fas fa-sync-alt text-orange-500 text-2xl mt-1"></i>
                        <div class="flex-1">
                            <h4 class="font-bold text-lg mb-1">全量覆盖更新</h4>
                            <p class="text-sm text-gray-600 mb-3">强制覆盖所有已存在的同名文件，不删除目标多余文件。此操作不会修改任务的持久配置。</p>
                            <button onclick="triggerFullOverwrite('${taskId}')" class="btn btn-primary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>
                                <i class="fas fa-bolt"></i>立即执行
                            </button>
                        </div>
                    </div>
                </div>
                <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                    <div class="flex items-start gap-2">
                        <i class="fas fa-exclamation-triangle text-yellow-600 mt-0.5"></i>
                        <p class="text-xs text-yellow-700">
                            <strong>注意：</strong>全量覆盖会替换所有已存在文件，请确保源文件完整且正确。此操作仅执行一次，不影响定时任务的同步策略。
                        </p>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeAdvancedTools();
    });
}

function closeAdvancedTools() {
    const modal = document.getElementById('advancedToolsModal');
    if (modal) {
        modal.remove();
    }
}

async function triggerFullOverwrite(taskId) {
    const task = tasksCache.find(t => t.id === taskId);
    if (!task) {
        showNotification('任务不存在', 'error');
        return;
    }
    
    // 二次确认
    if (!confirm(`确认对任务「${task.name}」执行全量覆盖吗？\n\n此操作将强制覆盖所有已存在的同名文件！`)) {
        return;
    }
    
    try {
        // 发送全量覆盖请求
        const response = await fetch(`/api/tasks/${taskId}/full-overwrite`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('全量覆盖任务已加入队列', 'success');
            closeAdvancedTools();
            // 打开日志窗口
            setTimeout(() => {
                openLogWindow(taskId, task.name + ' 日志');
            }, 500);
        } else {
            showNotification(result.error || '执行失败', 'error');
        }
    } catch (error) {
        console.error('全量覆盖失败:', error);
        showNotification('执行失败', 'error');
    }
}

(function init() {
    const savedTheme = localStorage.getItem('cg-theme') || 'light';
    applyTheme(savedTheme);
    document.addEventListener('DOMContentLoaded', () => {
        loadSystemStatus();
        loadTasks();
        loadQueue(false);
        
        // 初始化表单监听
        initFormChangeListener();
        
        setInterval(() => {
            loadSystemStatus();
            loadTasks();
            if (logWindows.size > 0) {
                logWindows.forEach((_, logId) => loadLogsFor(logId));
            }
            if (currentView === 'queue') loadQueue();
        }, 3000);
        
        // 修改任务模态框逻辑：禁用点击外部关闭，只支持 X 按钮和 ESC 键
        const taskModal = document.getElementById('taskModal');
        if (taskModal) {
            // 监听 ESC 键
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && taskModal.classList.contains('show')) {
                    closeTaskModal();
                }
            });
        }
        
        // 其他模态框保持原有逻辑
        ['runningModal', 'queueModal'].forEach(id => {
            const modal = document.getElementById(id);
            if (modal) modal.addEventListener('click', (e) => { if (e.target.id === id) modal.classList.remove('show'); });
        });
    });
})();
