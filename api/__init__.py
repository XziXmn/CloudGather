"""
API 蓝图模块
"""
from flask import Flask

from api.tasks import tasks_bp
from api.status import status_bp


def register_blueprints(app: Flask):
    """注册所有 API 蓝图"""
    app.register_blueprint(tasks_bp, url_prefix='/api')
    app.register_blueprint(status_bp, url_prefix='/api')
