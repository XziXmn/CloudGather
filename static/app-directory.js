// 目录自动提示相关逻辑
let currentDropdown = null;
let currentInputField = null;

function initDirectoryAutocomplete() {
    const sourceInput = document.getElementById('taskSource');
    const targetInput = document.getElementById('taskTarget');
    const strmSourceInput = document.getElementById('strmSourceDir');
    const strmTargetInput = document.getElementById('strmTargetDir');
    
    if (sourceInput) setupDirectoryInput(sourceInput);
    if (targetInput) setupDirectoryInput(targetInput);
    if (strmSourceInput) setupDirectoryInput(strmSourceInput);
    if (strmTargetInput) setupDirectoryInput(strmTargetInput);
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
