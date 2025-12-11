// CloudGather v2.1 - 前端交互脚本
let currentEditingTaskId = null;
let lastTasksData = null;
let currentLogTab = 'general';
let terminalOpen = false;
let taskLogTabs = new Set();

// 切换Tab
function switchTab(tabName) {
    // 更新按钮状态
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.closest('.tab-btn').classList.add('active');
    
    // 更新内容显示
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(`tab-${tabName}`).classList.add('active');
    
    // 如果切换到队列，立即加载
    if (tabName === 'queue') {
        loadQueue();
    }
}

// 切换日志终端
function toggleTerminal() {
    terminalOpen = !terminalOpen;
    const terminal = document.getElementById('terminal-modal');
    if (terminalOpen) {
        terminal.classList.add('show');
        loadLogs();
    } else {
        terminal.classList.remove('show');
    }
}

// 切换日志Tab
function switchLogTab(tabId) {
    currentLogTab = tabId;
    // 更新Tab样式
    document.querySelectorAll('.terminal-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    event.target.classList.add('active');
    loadLogs();
}

// 查看任务日志
function viewTaskLog(taskId, taskName) {
    // 添加任务日志Tab（如果不存在）
    if (!taskLogTabs.has(taskId)) {
        taskLogTabs.add(taskId);
        const tabsContainer = document.getElementById('task-log-tabs');
        const tab = document.createElement('div');
        tab.className = 'terminal-tab';
        tab.dataset.taskId = taskId;
        tab.innerHTML = `<i class="fas fa-file-alt mr-2"></i>${taskName}`;
        tab.onclick = () => {
            currentLogTab = taskId;
            document.querySelectorAll('.terminal-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            loadLogs();
        };
        tabsContainer.appendChild(tab);
    }
    
    // 打开终端并切换到该任务的Tab
    if (!terminalOpen) {
        toggleTerminal();
    }
    currentLogTab = taskId;
    document.querySelectorAll('.terminal-tab').forEach(tab => {
        tab.classList.remove('active');
        if (tab.dataset.taskId === taskId) {
            tab.classList.add('active');
        }
    });
    loadLogs();
}

// 格式化字节大小
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// 格式化时间间隔
function formatInterval(seconds) {
    if (seconds < 60) return `${seconds}秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins > 0 ? `${hours}小时${mins}分钟` : `${hours}小时`;
}

// 获取状态徽章
function getStatusBadge(status) {
    const badges = {
        'IDLE': '<span class="status-badge status-idle"><i class="fas fa-circle mr-1"></i>空闲</span>',
        'QUEUED': '<span class="status-badge status-queued"><i class="fas fa-clock mr-1"></i>队列中</span>',
        'RUNNING': '<span class="status-badge status-running"><i class="fas fa-spinner fa-spin mr-1"></i>运行中</span>',
        'ERROR': '<span class="status-badge status-error"><i class="fas fa-exclamation-circle mr-1"></i>错误</span>'
    };
    return badges[status] || badges['IDLE'];
}

// 加载系统状态
async function loadSystemStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        // 更新统计
        document.getElementById('stat-total').textContent = data.task_count;
        document.getElementById('stat-queued').textContent = data.queue_size;
        
        document.getElementById('stat-scheduler').textContent = data.running ? '运行中' : '已停止';
        document.getElementById('stat-scheduler').className = data.running ? 
            'text-lg font-bold text-green-500' : 'text-lg font-bold text-red-500';
        
        // 更新系统资源
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
        
        // 更新设置页面
        document.getElementById('config-path').textContent = data.config_path;
        document.getElementById('is-docker').textContent = data.is_docker ? 'Docker' : '本地';
        
    } catch (error) {
        console.error('加载系统状态失败:', error);
    }
}

// 加载任务列表
async function loadTasks() {
    try {
        const response = await fetch('/api/tasks');
        const data = await response.json();
        const tasks = data.tasks || [];
        
        // 更新运行中任务数
        const running = tasks.filter(t => t.status === 'RUNNING').length;
        document.getElementById('stat-running').textContent = running;
        
        // 检查是否需要重新渲染
        const currentData = JSON.stringify(tasks);
        if (currentData !== lastTasksData) {
            renderTasks(tasks);
            lastTasksData = currentData;
        } else {
            // 只更新状态
            updateTaskStatus(tasks);
        }
    } catch (error) {
        console.error('加载任务失败:', error);
    }
}

// 只更新任务状态（防止闪烁）
function updateTaskStatus(tasks) {
    tasks.forEach(task => {
        const taskCard = document.querySelector(`[data-task-id="${task.id}"]`);
        if (taskCard) {
            const statusBadge = taskCard.querySelector('.status-badge-container');
            if (statusBadge) {
                statusBadge.innerHTML = getStatusBadge(task.status);
            }
        }
    });
}

// 渲染任务列表
function renderTasks(tasks) {
    const container = document.getElementById('tasks-container');
    
    if (tasks.length === 0) {
        container.innerHTML = `
            <div class="text-center py-12 text-gray-500">
                <i class="fas fa-inbox text-6xl mb-4"></i>
                <p class="text-lg">暂无任务</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = tasks.map(task => `
        <div class="task-card" data-task-id="${task.id}">
            <div class="flex items-start justify-between mb-4">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-2">
                        <h4 class="text-lg font-bold text-white">${task.name}</h4>
                        <span class="status-badge-container">${getStatusBadge(task.status)}</span>
                        ${task.enabled ? 
                            '<span class="text-xs px-2 py-1 bg-green-500/20 text-green-500 rounded">已启用</span>' : 
                            '<span class="text-xs px-2 py-1 bg-gray-500/20 text-gray-400 rounded">已禁用</span>'}
                    </div>
                </div>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4 text-sm">
                <div class="flex items-center text-gray-400">
                    <i class="fas fa-folder-open text-blue-500 mr-2"></i>
                    <span>源：</span>
                    <span class="ml-2 font-mono text-gray-300">${task.source_path}</span>
                </div>
                <div class="flex items-center text-gray-400">
                    <i class="fas fa-folder text-green-500 mr-2"></i>
                    <span>目标：</span>
                    <span class="ml-2 font-mono text-gray-300">${task.target_path}</span>
                </div>
                <div class="flex items-center text-gray-400">
                    <i class="fas fa-clock text-yellow-500 mr-2"></i>
                    <span>间隔：${formatInterval(task.interval)}</span>
                </div>
                <div class="flex items-center gap-2">
                    ${task.recursive ? '<span class="text-xs px-2 py-1 bg-blue-500/20 text-blue-400 rounded"><i class="fas fa-code-branch mr-1"></i>递归</span>' : ''}
                    ${task.verify_md5 ? '<span class="text-xs px-2 py-1 bg-purple-500/20 text-purple-400 rounded"><i class="fas fa-shield-alt mr-1"></i>MD5</span>' : ''}
                    ${task.last_run_time ? `<span class="text-xs text-gray-500"><i class="fas fa-history mr-1"></i>${new Date(task.last_run_time).toLocaleString()}</span>` : ''}
                </div>
            </div>
            
            <div class="flex gap-2 flex-wrap">
                <button onclick="triggerTask('${task.id}')" 
                        class="btn btn-primary text-sm"
                        ${task.status !== 'IDLE' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>
                    <i class="fas fa-play"></i>立即运行
                </button>
                <button onclick="viewTaskLog('${task.id}', '${task.name}')" 
                        class="btn btn-secondary text-sm">
                    <i class="fas fa-terminal"></i>查看日志
                </button>
                <button onclick="editTask('${task.id}')" 
                        class="btn btn-secondary text-sm">
                    <i class="fas fa-edit"></i>编辑
                </button>
                <button onclick="deleteTask('${task.id}', '${task.name}')" 
                        class="btn btn-secondary text-sm border-red-500/50 text-red-500 hover:bg-red-500/10">
                    <i class="fas fa-trash"></i>删除
                </button>
            </div>
        </div>
    `).join('');
}

// 加载任务队列
async function loadQueue() {
    try {
        const response = await fetch('/api/queue');
        const data = await response.json();
        const queue = data.queue || [];
        
        document.getElementById('queue-count').textContent = `${queue.length} 个任务排队中`;
        
        const container = document.getElementById('queue-container');
        
        if (queue.length === 0) {
            container.innerHTML = `
                <div class="text-center py-12 text-gray-500">
                    <i class="fas fa-hourglass-half text-6xl mb-4"></i>
                    <p class="text-lg">队列为空</p>
                </div>
            `;
            return;
        }
        
        container.innerHTML = queue.map((task, index) => `
            <div class="task-card">
                <div class="flex items-center gap-4">
                    <div class="h-10 w-10 rounded-full bg-yellow-500/20 flex items-center justify-center text-yellow-500 font-bold">
                        ${index + 1}
                    </div>
                    <div class="flex-1">
                        <h4 class="text-white font-bold">${task.name}</h4>
                        <p class="text-sm text-gray-400">${task.source_path} → ${task.target_path}</p>
                    </div>
                    ${getStatusBadge(task.status)}
                </div>
            </div>
        `).join('');
        
    } catch (error) {
        console.error('加载队列失败:', error);
    }
}

// 加载日志
async function loadLogs() {
    if (!terminalOpen) return;
    
    try {
        const response = await fetch(`/api/logs?task_id=${currentLogTab}`);
        const data = await response.json();
        const logs = data.logs || [];
        
        const container = document.getElementById('terminal-content');
        if (logs.length === 0) {
            container.innerHTML = '<div class="text-gray-500">暂无日志</div>';
        } else {
            container.innerHTML = logs.map(log => 
                `<div class="mb-1">${log}</div>`
            ).join('');
            container.scrollTop = container.scrollHeight;
        }
    } catch (error) {
        console.error('加载日志失败:', error);
    }
}

// 清空当前日志
async function clearCurrentLog() {
    try {
        await fetch(`/api/logs/clear?task_id=${currentLogTab}`, { method: 'POST' });
        loadLogs();
        showNotification('日志已清空', 'success');
    } catch (error) {
        console.error('清空日志失败:', error);
        showNotification('清空失败', 'error');
    }
}

// 显示通知
function showNotification(message, type = 'info') {
    const colors = {
        success: 'bg-green-500',
        error: 'bg-red-500',
        warning: 'bg-yellow-500',
        info: 'bg-blue-500'
    };
    
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 ${colors[type]} text-white px-6 py-3 rounded-lg shadow-lg z-50 fade-in`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.opacity = '0';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// 显示添加任务模态框
function showAddTaskModal() {
    currentEditingTaskId = null;
    document.getElementById('modalTitle').textContent = '添加任务';
    document.getElementById('taskForm').reset();
    document.getElementById('taskId').value = '';
    document.getElementById('taskRecursive').checked = true;
    document.getElementById('taskEnabled').checked = true;
    document.getElementById('taskModal').classList.remove('hidden');
}

// 关闭模态框
function closeTaskModal() {
    document.getElementById('taskModal').classList.add('hidden');
    currentEditingTaskId = null;
}

// 编辑任务
async function editTask(taskId) {
    try {
        const response = await fetch('/api/tasks');
        const data = await response.json();
        const task = data.tasks.find(t => t.id === taskId);
        
        if (!task) {
            showNotification('任务不存在', 'error');
            return;
        }
        
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
        
        document.getElementById('taskModal').classList.remove('hidden');
    } catch (error) {
        console.error('加载任务失败:', error);
        showNotification('加载任务失败', 'error');
    }
}

// 保存任务
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
            response = await fetch(`/api/tasks/${currentEditingTaskId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(taskData)
            });
        } else {
            response = await fetch('/api/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(taskData)
            });
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

// 删除任务
async function deleteTask(taskId, taskName) {
    if (!confirm(`确定要删除任务"${taskName}"吗？`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/tasks/${taskId}`, {
            method: 'DELETE'
        });
        
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

// 触发任务
async function triggerTask(taskId) {
    try {
        const response = await fetch(`/api/tasks/${taskId}/trigger`, {
            method: 'POST'
        });
        
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

// 启动调度器
async function startScheduler() {
    try {
        const response = await fetch('/api/scheduler/start', { method: 'POST' });
        const result = await response.json();
        
        if (result.success) {
            showNotification('调度器已启动', 'success');
            loadSystemStatus();
        } else {
            showNotification('启动失败', 'error');
        }
    } catch (error) {
        console.error('启动调度器失败:', error);
        showNotification('启动调度器失败', 'error');
    }
}

// 停止调度器
async function stopScheduler() {
    if (!confirm('确定要停止调度器吗？')) {
        return;
    }
    
    try {
        const response = await fetch('/api/scheduler/stop', { method: 'POST' });
        const result = await response.json();
        
        if (result.success) {
            showNotification('调度器已停止', 'warning');
            loadSystemStatus();
        } else {
            showNotification('停止失败', 'error');
        }
    } catch (error) {
        console.error('停止调度器失败:', error);
        showNotification('停止调度器失败', 'error');
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadSystemStatus();
    loadTasks();
    
    // 定时刷新
    setInterval(() => {
        loadSystemStatus();
        loadTasks();
        if (terminalOpen) {
            loadLogs();
        }
        // 如果在队列Tab，刷新队列
        if (document.getElementById('tab-queue').classList.contains('active')) {
            loadQueue();
        }
    }, 3000);
});

// 点击模态框外部关闭
document.getElementById('taskModal').addEventListener('click', (e) => {
    if (e.target.id === 'taskModal') {
        closeTaskModal();
    }
});
