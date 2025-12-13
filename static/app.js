// CloudGather v0.3.5 - 蓝粉白纯色 + 独立日志窗 + MD侧边栏 + Cron 调度
let currentEditingTaskId = null;
let lastTasksData = null;
let tasksCache = [];
let queueCache = [];
let currentView = 'dashboard';
const logWindows = new Map(); // logId -> element
const logCache = {}; // 本地缓存各日志内容
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
        document.getElementById('app-version').textContent = 'v' + (data.version || '0.3.5');  // 显示版本号
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
            scheduleInfo = `<div class="flex items-center"><i class="fas fa-calendar-alt text-purple-500 mr-2"></i><span>Cron: <code class="px-2 py-1 bg-gray-100 rounded text-xs font-mono">${task.cron_expression}</code></span></div>`;
        } else {
            scheduleInfo = `<div class="flex items-center"><i class="fas fa-clock text-yellow-500 mr-2"></i><span>间隔：${formatInterval(task.interval)}</span></div>`;
        }
        
        return `
        <div class="task-card" data-task-id="${task.id}">
            <div class="flex items-start justify-between mb-3">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-1">
                        <h4 class="text-lg font-bold">${task.name}</h4>
                        <span class="status-badge-container">${getStatusBadge(task.status)}</span>
                        ${task.enabled ? '<span class="text-xs px-2 py-1 bg-green-100 text-green-700 rounded">已启用</span>' : '<span class="text-xs px-2 py-1 bg-gray-200 text-gray-600 rounded">已禁用</span>'}
                        ${task.schedule_type === 'CRON' ? '<span class="text-xs px-2 py-1 bg-purple-100 text-purple-700 rounded"><i class="fas fa-calendar-alt mr-1"></i>Cron</span>' : '<span class="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded"><i class="fas fa-clock mr-1"></i>间隔</span>'}
                    </div>
                </div>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm text-gray-600">
                <div class="flex items-center"><i class="fas fa-folder-open text-blue-500 mr-2"></i><span class="font-mono">${task.source_path}</span></div>
                <div class="flex items-center"><i class="fas fa-folder text-green-500 mr-2"></i><span class="font-mono">${task.target_path}</span></div>
                ${scheduleInfo}
                <div class="flex items-center gap-2">
                    ${task.recursive ? '<span class="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded"><i class="fas fa-code-branch mr-1"></i>递归</span>' : ''}
                    ${task.verify_md5 ? '<span class="text-xs px-2 py-1 bg-purple-100 text-purple-700 rounded"><i class="fas fa-shield-alt mr-1"></i>MD5</span>' : ''}
                    ${task.last_run_time ? `<span class="text-xs text-gray-500"><i class="fas fa-history mr-1"></i>${new Date(task.last_run_time).toLocaleString()}</span>` : ''}
                </div>
            </div>
            <div class="flex gap-2 flex-wrap mt-3">
                <button onclick="triggerTask('${task.id}')" class="btn btn-primary text-sm" ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}><i class="fas fa-play"></i>立即运行</button>
                <button onclick="openLogWindow('${task.id}', '${task.name.replace(/'/g, "''")} 日志')" class="btn btn-secondary text-sm"><i class="fas fa-terminal"></i>查看日志</button>
                <button onclick="editTask('${task.id}')" class="btn btn-secondary text-sm"><i class="fas fa-edit"></i>编辑</button>
                <button onclick="deleteTask('${task.id}', '${task.name.replace(/'/g, "''")}')" class="btn btn-secondary text-sm border-red-500 text-red-500"><i class="fas fa-trash"></i>删除</button>
            </div>
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
    document.getElementById('taskRecursive').checked = true;
    document.getElementById('taskEnabled').checked = true;
    
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
            document.getElementById('taskInterval').value = draft.interval || 300;
            document.getElementById('taskRecursive').checked = draft.recursive !== false;
            document.getElementById('taskMd5').checked = draft.verify_md5 || false;
            document.getElementById('taskEnabled').checked = draft.enabled !== false;
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
        interval: parseInt(document.getElementById('taskInterval').value) || 300,
        recursive: document.getElementById('taskRecursive').checked,
        verify_md5: document.getElementById('taskMd5').checked,
        enabled: document.getElementById('taskEnabled').checked
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
        document.getElementById('taskRecursive').checked = task.recursive;
        document.getElementById('taskMd5').checked = task.verify_md5;
        document.getElementById('taskEnabled').checked = task.enabled;
        
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
        recursive: document.getElementById('taskRecursive').checked,
        verify_md5: document.getElementById('taskMd5').checked,
        enabled: document.getElementById('taskEnabled').checked
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
    const inputs = ['taskName', 'taskSource', 'taskTarget', 'cronExpression', 'taskRecursive', 'taskMd5', 'taskEnabled'];
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
