// CloudGather - 前端交互脚本
let currentEditingTaskId = null;

// 页面切换
function showSection(sectionName) {
    // 隐藏所有部分
    document.querySelectorAll('main > section').forEach(section => {
        section.classList.add('hidden');
    });
    
    // 显示目标部分
    document.getElementById(sectionName).classList.remove('hidden');
    
    // 更新导航高亮
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('border-blue-500', 'bg-gray-700');
        link.classList.add('border-transparent');
    });
    event.target.closest('.nav-link').classList.add('border-blue-500', 'bg-gray-700');
    event.target.closest('.nav-link').classList.remove('border-transparent');
}

// 获取任务状态徽章
function getStatusBadge(status) {
    const badges = {
        'IDLE': '<span class="status-badge bg-gray-600 text-gray-200"><i class="fas fa-circle text-xs mr-1"></i>空闲</span>',
        'QUEUED': '<span class="status-badge bg-yellow-600 text-yellow-100"><i class="fas fa-clock text-xs mr-1"></i>队列中</span>',
        'RUNNING': '<span class="status-badge bg-green-600 text-green-100"><i class="fas fa-spinner fa-spin text-xs mr-1"></i>运行中</span>',
        'ERROR': '<span class="status-badge bg-red-600 text-red-100"><i class="fas fa-exclamation-circle text-xs mr-1"></i>错误</span>'
    };
    return badges[status] || badges['IDLE'];
}

// 格式化时间间隔
function formatInterval(seconds) {
    if (seconds < 60) return `${seconds}秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins > 0 ? `${hours}小时${mins}分钟` : `${hours}小时`;
}

// 加载任务列表
async function loadTasks() {
    try {
        const response = await fetch('/api/tasks');
        const data = await response.json();
        const tasks = data.tasks || [];
        
        // 更新统计
        updateStats(tasks);
        
        // 渲染任务列表
        renderTasks(tasks);
    } catch (error) {
        console.error('加载任务失败:', error);
        showNotification('加载任务失败', 'error');
    }
}

// 更新统计数据
function updateStats(tasks) {
    const total = tasks.length;
    const running = tasks.filter(t => t.status === 'RUNNING').length;
    const queued = tasks.filter(t => t.status === 'QUEUED').length;
    
    document.getElementById('stat-total').textContent = total;
    document.getElementById('stat-running').textContent = running;
    document.getElementById('stat-queued').textContent = queued;
}

// 渲染任务列表
function renderTasks(tasks) {
    const container = document.getElementById('tasks-container');
    
    if (tasks.length === 0) {
        container.innerHTML = `
            <div class="text-center py-12 text-gray-400">
                <i class="fas fa-inbox text-6xl mb-4"></i>
                <p class="text-lg">暂无任务</p>
                <p class="text-sm mt-2">点击右上角"添加任务"开始</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = tasks.map(task => `
        <div class="bg-gray-700 rounded-lg p-6 mb-4 hover:bg-gray-650 transition-colors fade-in">
            <div class="flex justify-between items-start mb-4">
                <div class="flex-1">
                    <div class="flex items-center gap-3 mb-2">
                        <h4 class="text-xl font-bold text-white">${task.name}</h4>
                        ${getStatusBadge(task.status)}
                        ${task.enabled ? '<span class="text-xs px-2 py-1 bg-green-600 text-green-100 rounded">已启用</span>' : '<span class="text-xs px-2 py-1 bg-gray-600 text-gray-300 rounded">已禁用</span>'}
                    </div>
                </div>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4 text-sm">
                <div class="flex items-center text-gray-300">
                    <i class="fas fa-folder-open text-blue-400 mr-2"></i>
                    <span class="text-gray-400">源：</span>
                    <span class="ml-2 font-mono">${task.source_path}</span>
                </div>
                <div class="flex items-center text-gray-300">
                    <i class="fas fa-folder text-green-400 mr-2"></i>
                    <span class="text-gray-400">目标：</span>
                    <span class="ml-2 font-mono">${task.target_path}</span>
                </div>
                <div class="flex items-center text-gray-300">
                    <i class="fas fa-clock text-yellow-400 mr-2"></i>
                    <span>间隔：${formatInterval(task.interval)}</span>
                </div>
                <div class="flex items-center gap-3 text-gray-300">
                    ${task.recursive ? '<span class="text-xs px-2 py-1 bg-blue-600 text-blue-100 rounded"><i class="fas fa-code-branch mr-1"></i>递归</span>' : ''}
                    ${task.verify_md5 ? '<span class="text-xs px-2 py-1 bg-purple-600 text-purple-100 rounded"><i class="fas fa-shield-alt mr-1"></i>MD5</span>' : ''}
                    ${task.last_run_time ? `<span class="text-xs text-gray-400"><i class="fas fa-history mr-1"></i>${new Date(task.last_run_time).toLocaleString()}</span>` : ''}
                </div>
            </div>
            
            <div class="flex gap-2">
                <button onclick="triggerTask('${task.id}')" 
                        class="px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg transition-colors text-sm flex items-center"
                        ${task.status !== 'IDLE' ? 'disabled opacity-50 cursor-not-allowed' : ''}>
                    <i class="fas fa-play mr-2"></i>立即运行
                </button>
                <button onclick="editTask('${task.id}')" 
                        class="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors text-sm flex items-center">
                    <i class="fas fa-edit mr-2"></i>编辑
                </button>
                <button onclick="deleteTask('${task.id}', '${task.name}')" 
                        class="px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors text-sm flex items-center">
                    <i class="fas fa-trash mr-2"></i>删除
                </button>
            </div>
        </div>
    `).join('');
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
    document.getElementById('taskModal').classList.add('flex');
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
        document.getElementById('taskModal').classList.add('flex');
    } catch (error) {
        console.error('加载任务失败:', error);
        showNotification('加载任务失败', 'error');
    }
}

// 关闭模态框
function closeTaskModal() {
    document.getElementById('taskModal').classList.add('hidden');
    document.getElementById('taskModal').classList.remove('flex');
    currentEditingTaskId = null;
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
            // 更新任务
            response = await fetch(`/api/tasks/${currentEditingTaskId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(taskData)
            });
        } else {
            // 创建任务
            response = await fetch('/api/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(taskData)
            });
        }
        
        const result = await response.json();
        
        if (result.success) {
            showNotification(currentEditingTaskId ? '任务已更新' : '任务已创建', 'success');
            closeTaskModal();
            loadTasks();
        } else {
            showNotification(result.error || '操作失败', 'error');
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

// 加载日志
async function loadLogs() {
    try {
        const response = await fetch('/api/logs');
        const data = await response.json();
        const logs = data.logs || [];
        
        const container = document.getElementById('log-content');
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

// 清空日志
async function clearLogs() {
    document.getElementById('log-content').innerHTML = '<div class="text-gray-500">日志已清空</div>';
    showNotification('日志已清空', 'success');
}

// 加载系统状态
async function loadSystemStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        document.getElementById('stat-scheduler').textContent = data.running ? '运行中' : '已停止';
        document.getElementById('stat-scheduler').className = data.running ? 
            'text-lg font-bold text-green-400 mt-2' : 'text-lg font-bold text-red-400 mt-2';
        
        document.getElementById('system-running').textContent = data.running ? '运行中' : '已停止';
        document.getElementById('system-running').className = data.running ? 
            'text-green-400 font-semibold' : 'text-red-400 font-semibold';
        document.getElementById('system-tasks').textContent = data.task_count;
        document.getElementById('system-queue').textContent = data.queue_size;
        document.getElementById('system-config').textContent = data.config_path;
    } catch (error) {
        console.error('加载系统状态失败:', error);
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

// 通知提示
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

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadTasks();
    loadSystemStatus();
    
    // 定时刷新
    setInterval(() => {
        loadTasks();
        loadSystemStatus();
        if (!document.getElementById('logs').classList.contains('hidden')) {
            loadLogs();
        }
    }, 3000);
});

// 点击模态框外部关闭
document.getElementById('taskModal').addEventListener('click', (e) => {
    if (e.target.id === 'taskModal') {
        closeTaskModal();
    }
});
