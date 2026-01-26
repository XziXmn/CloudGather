"""
系统设置 API
处理 OpenList 配置等系统设置
"""

import json
import logging
from pathlib import Path
from typing import Optional
from flask import Blueprint, jsonify, request
import requests

# 配置文件路径
OPENLIST_CONFIG_PATH = Path('config/openlist.json')
EXTENSIONS_CONFIG_PATH = Path('config/extensions.json')
SYSTEM_CONFIG_PATH = Path('config/system.json')

settings_bp = Blueprint('settings', __name__)

# 全局变量，由 init_settings_bp 初始化
_is_docker = False


def init_settings_bp(is_docker: bool):
    """初始化设置蓝图"""
    global _is_docker
    _is_docker = is_docker
    
    # 确保配置目录存在
    OPENLIST_CONFIG_PATH.parent.mkdir(exist_ok=True)
    EXTENSIONS_CONFIG_PATH.parent.mkdir(exist_ok=True)
    SYSTEM_CONFIG_PATH.parent.mkdir(exist_ok=True)


def load_openlist_config() -> dict:
    """加载 OpenList 配置"""
    if OPENLIST_CONFIG_PATH.exists():
        try:
            with open(OPENLIST_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"加载 OpenList 配置失败: {e}")
    return {}


def save_openlist_config(config: dict) -> bool:
    """保存 OpenList 配置"""
    try:
        with open(OPENLIST_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"保存 OpenList 配置失败: {e}")
        return False


@settings_bp.route('/settings/openlist', methods=['GET'])
def get_openlist_config():
    """获取 OpenList 配置"""
    config = load_openlist_config()
    # 不返回密码
    if 'password' in config:
        config_copy = config.copy()
        config_copy['password'] = ''
        return jsonify({'success': True, 'config': config_copy})
    return jsonify({'success': True, 'config': config})


@settings_bp.route('/settings/openlist', methods=['POST'])
def save_openlist_config_api():
    """保存 OpenList 配置"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '无效的请求数据'}), 400
        
        # 验证必需字段
        url = data.get('url', '').strip()
        if not url:
            return jsonify({'success': False, 'error': '服务器地址不能为空'}), 400
        
        # 构建配置对象
        config = {
            'url': url,
            'username': data.get('username', '').strip(),
            'password': data.get('password', '').strip(),
            'token': data.get('token', '').strip(),
            'public_url': data.get('public_url', '').strip()
        }
        
        # 如果没有提供新密码，保留旧密码
        if not config['password']:
            old_config = load_openlist_config()
            if 'password' in old_config:
                config['password'] = old_config['password']
        
        # 保存配置
        if save_openlist_config(config):
            logging.info(f"✅ OpenList 配置已保存: {url}")
            return jsonify({'success': True, 'message': '配置已保存'})
        else:
            return jsonify({'success': False, 'error': '保存配置失败'}), 500
            
    except Exception as e:
        logging.error(f"保存 OpenList 配置异常: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/settings/openlist/test', methods=['POST'])
def test_openlist_connection():
    """测试 OpenList 连接"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '无效的请求数据'}), 400
        
        url = data.get('url', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        token = data.get('token', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': '服务器地址不能为空'}), 400
        
        # 如果提供了 token，直接测试
        if token:
            test_result = _test_with_token(url, token)
            if test_result['success']:
                return jsonify({'success': True, 'message': '连接成功'})
            else:
                return jsonify({'success': False, 'error': test_result.get('error', '连接失败')})
        
        # 如果提供了用户名和密码，先登录获取 token
        if username and password:
            login_result = _login_openlist(url, username, password)
            if login_result['success']:
                return jsonify({'success': True, 'message': '连接成功'})
            else:
                return jsonify({'success': False, 'error': login_result.get('error', '登录失败')})
        
        # 如果既没有 token 也没有用户名密码
        return jsonify({'success': False, 'error': '请提供 Token 或用户名密码'})
        
    except Exception as e:
        logging.error(f"测试 OpenList 连接异常: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _test_with_token(url: str, token: str) -> dict:
    """使用 token 测试连接"""
    try:
        # 测试 /api/me 接口
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.get(f"{url}/api/me", headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 200:
                return {'success': True}
            else:
                return {'success': False, 'error': data.get('message', '未知错误')}
        else:
            return {'success': False, 'error': f'HTTP {response.status_code}'}
            
    except requests.exceptions.Timeout:
        return {'success': False, 'error': '连接超时'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': '无法连接到服务器'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def _login_openlist(url: str, username: str, password: str) -> dict:
    """登录 OpenList"""
    try:
        # 调用登录接口
        login_url = f"{url}/api/auth/login"
        payload = {
            'username': username,
            'password': password
        }
        
        response = requests.post(login_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 200:
                token = data.get('data', {}).get('token')
                if token:
                    return {'success': True, 'token': token}
                else:
                    return {'success': False, 'error': '未返回 Token'}
            else:
                return {'success': False, 'error': data.get('message', '登录失败')}
        else:
            return {'success': False, 'error': f'HTTP {response.status_code}'}
            
    except requests.exceptions.Timeout:
        return {'success': False, 'error': '连接超时'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': '无法连接到服务器'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ========== 文件扩展名设置 ==========

def load_extensions_config() -> dict:
    """加载文件扩展名配置"""
    if EXTENSIONS_CONFIG_PATH.exists():
        try:
            with open(EXTENSIONS_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"加载文件扩展名配置失败: {e}")
    # 返回默认配置
    return {
        'subtitle': '.srt,.ass,.ssa,.sub,.vtt',
        'image': '.jpg,.jpeg,.png,.bmp,.gif,.webp',
        'nfo': '.nfo',
        'other': ''
    }


def save_extensions_config(config: dict) -> bool:
    """保存文件扩展名配置"""
    try:
        with open(EXTENSIONS_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"保存文件扩展名配置失败: {e}")
        return False


@settings_bp.route('/settings/extensions', methods=['GET'])
def get_extensions_config():
    """获取文件扩展名配置"""
    config = load_extensions_config()
    return jsonify({'success': True, 'extensions': config})


@settings_bp.route('/settings/extensions', methods=['POST'])
def save_extensions_config_api():
    """保存文件扩展名配置"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '无效的请求数据'}), 400
        
        # 构建配置对象
        config = {
            'subtitle': data.get('subtitle', '').strip(),
            'image': data.get('image', '').strip(),
            'nfo': data.get('nfo', '').strip(),
            'other': data.get('other', '').strip()
        }
        
        # 验证扩展名格式
        for key, value in config.items():
            if value and key != 'other':  # other 可以为空
                exts = [e.strip() for e in value.split(',') if e.strip()]
                for ext in exts:
                    if not ext.startswith('.'):
                        return jsonify({
                            'success': False, 
                            'error': f'扩展名格式错误: "{ext}" 必须以点开头'
                        }), 400
        
        # 保存配置
        if save_extensions_config(config):
            logging.info(f"✅ 文件扩展名配置已保存")
            return jsonify({'success': True, 'message': '配置已保存'})
        else:
            return jsonify({'success': False, 'error': '保存配置失败'}), 500
            
    except Exception as e:
        logging.error(f"保存文件扩展名配置异常: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 系统通用设置 ==========

def load_system_config() -> dict:
    """加载系统通用配置"""
    if SYSTEM_CONFIG_PATH.exists():
        try:
            with open(SYSTEM_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"加载系统配置失败: {e}")
    # 返回默认配置
    return {
        'sync_retry_count': 3
    }


def save_system_config(config: dict) -> bool:
    """保存系统通用配置"""
    try:
        with open(SYSTEM_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"保存系统配置失败: {e}")
        return False


@settings_bp.route('/settings/system', methods=['GET'])
def get_system_config():
    """获取系统通用配置"""
    config = load_system_config()
    return jsonify({'success': True, 'config': config})


@settings_bp.route('/settings/system', methods=['POST'])
def save_system_config_api():
    """保存系统通用配置"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '无效的请求数据'}), 400
        
        # 构建配置对象
        config = {
            'sync_retry_count': int(data.get('sync_retry_count', 3))
        }
        
        # 验证重试次数
        if config['sync_retry_count'] < 0:
            config['sync_retry_count'] = 0
        if config['sync_retry_count'] > 10:
            config['sync_retry_count'] = 10
            
        # 保存配置
        if save_system_config(config):
            logging.info(f"✅ 系统通用配置已保存")
            return jsonify({'success': True, 'message': '配置已保存'})
        else:
            return jsonify({'success': False, 'error': '保存配置失败'}), 500
            
    except Exception as e:
        logging.error(f"保存系统配置异常: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
