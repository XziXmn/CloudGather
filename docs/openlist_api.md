# OpenList API 文档

> **文档来源**: [https://fox.oplist.org.cn/](https://fox.oplist.org.cn/)  
> **许可证**: GNU Affero General Public License v3 (AGPL-3.0)  
> **生成时间**: 2026-01-08

## 目录

- [1. 概述](#1-概述)
- [2. 认证接口 (Authentication)](#2-认证接口-authentication)
  - [2.1 用户登录](#21-用户登录)
  - [2.2 预哈希密码登录](#22-预哈希密码登录)
  - [2.3 用户登出](#23-用户登出)
- [3. 文件系统接口 (File System)](#3-文件系统接口-file-system)
  - [3.1 列出目录内容](#31-列出目录内容)
  - [3.2 获取文件或目录信息](#32-获取文件或目录信息)
  - [3.3 获取目录树](#33-获取目录树)
  - [3.4 搜索文件和目录](#34-搜索文件和目录)
- [4. 公共接口 (Public)](#4-公共接口-public)
- [5. 其他接口章节索引](#5-其他接口章节索引)
- [6. 数据结构 (Schemas)](#6-数据结构-schemas)

---

## 1. 概述

OpenList 是一个文件列表程序，支持多种存储后端（本地、WebDAV、Alist、S3 等）。

**Base URL**: `http://your-openlist-server:port`

**认证方式**: 
- 大部分接口需要 JWT Token
- 在 Header 中添加: `Authorization: Bearer <token>`

**通用响应格式**:
```json
{
  "code": 200,
  "message": "success",
  "data": { ... }
}
```

**常见状态码**:
- `200`: 成功
- `400`: 请求参数有误
- `401`: 未认证
- `403`: 权限不足
- `404`: 资源未找到
- `500`: 服务器错误

---

## 2. 认证接口 (Authentication)

### 2.1 用户登录

**接口**: `POST /api/auth/login`

**说明**: 使用用户名和密码进行认证，返回 JWT Token

**请求头**:
```
Content-Type: application/json
```

**请求体**:
```json
{
  "username": "admin",
  "password": "my password",
  "otp_code": "123456"
}
```

**请求参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名 |
| password | string | 是 | 密码（明文） |
| otp_code | string | 否 | 2FA 验证码（启用双因素认证时必填） |

**成功响应** (200):
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| data.token | string | JWT Token，用于后续请求认证 |

**错误响应** (400):
- 用户名或密码错误
- 2FA 验证码错误或缺失

**cURL 示例**:
```bash
curl --location --request POST 'http://your-server/api/auth/login' \
--header 'Content-Type: application/json' \
--data-raw '{
  "username": "admin",
  "password": "my password",
  "otp_code": "123456"
}'
```

---

### 2.2 预哈希密码登录

**接口**: `POST /api/auth/login/hash`

**说明**: 使用用户名和预哈希密码（SHA256）进行认证

**请求头**:
```
Content-Type: application/json
```

**请求体**:
```json
{
  "username": "admin",
  "password": "hashed_password_string",
  "otp_code": "string"
}
```

**请求参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名 |
| password | string | 是 | 密码的 SHA256 哈希值 |
| otp_code | string | 否 | 2FA 验证码 |

**成功响应** (200):
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

**cURL 示例**:
```bash
curl --location --request POST 'http://your-server/api/auth/login/hash' \
--header 'Content-Type: application/json' \
--data-raw '{
  "username": "admin",
  "password": "hashed_password_string",
  "otp_code": "string"
}'
```

---

### 2.3 用户登出

**接口**: `GET /api/auth/logout`

**说明**: 使当前会话 Token 失效

**请求头**:
```
Authorization: Bearer <token>
```

**成功响应** (200):
```json
{
  "code": 200,
  "message": "success",
  "data": null
}
```

**错误响应** (401):
- Token 无效或已过期

**cURL 示例**:
```bash
curl --location --request GET 'http://your-server/api/auth/logout' \
--header 'Authorization: Bearer <token>'
```

---

## 3. 文件系统接口 (File System)

### 3.1 列出目录内容

**接口**: `POST /api/fs/list`

**说明**: 获取指定路径下的文件和目录列表，支持分页

**请求头**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体**:
```json
{
  "path": "/",
  "password": "",
  "refresh": false,
  "page": 1,
  "per_page": 30
}
```

**请求参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| path | string | 是 | 要列出的目录路径 |
| password | string | 否 | 私有存储的密码 |
| refresh | boolean | 否 | 是否强制刷新缓存（默认 false） |
| page | integer | 否 | 页码，从 1 开始（默认 1） |
| per_page | integer | 否 | 每页条数（默认 30） |

**成功响应** (200):
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "content": [
      {
        "id": "",
        "path": "D:\\files\\document.pdf",
        "name": "document.pdf",
        "size": 1024000,
        "is_dir": false,
        "modified": "2025-10-20T15:30:00+08:00",
        "created": "2025-10-20T10:00:00+08:00",
        "sign": "YBgnmykwCXUstXvNGtECaz_12gseXSL03cpqh5rTcGA=:0",
        "thumb": "",
        "type": 4,
        "hashinfo": "null",
        "hash_info": null,
        "mount_details": {
          "driver_name": "Local",
          "total_space": 1000000000000,
          "free_space": 500000000000
        }
      }
    ],
    "total": 14,
    "readme": "",
    "header": "",
    "write": true,
    "provider": "Local"
  }
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| data.content | array | 文件/目录列表 |
| data.content[].id | string | 文件 ID |
| data.content[].path | string | 文件完整路径 |
| data.content[].name | string | 文件/目录名称 |
| data.content[].size | integer | 文件大小（字节），目录为 0 |
| data.content[].is_dir | boolean | 是否为目录 |
| data.content[].modified | string | 修改时间（ISO 8601） |
| data.content[].created | string | 创建时间（ISO 8601） |
| data.content[].sign | string | 文件签名，用于生成下载链接 |
| data.content[].thumb | string | 缩略图 URL |
| data.content[].type | integer | 文件类型代码 |
| data.content[].mount_details | object | 挂载点详情 |
| data.total | integer | 总文件/目录数量 |
| data.readme | string | README 内容 |
| data.header | string | 头部信息 |
| data.write | boolean | 是否有写权限 |
| data.provider | string | 存储驱动名称 |

**错误响应**:
- `401`: 未认证
- `403`: 权限不足
- `404`: 路径不存在

**cURL 示例**:
```bash
curl --location --request POST 'http://your-server/api/fs/list' \
--header 'Authorization: Bearer <token>' \
--header 'Content-Type: application/json' \
--data-raw '{
  "path": "/",
  "password": "",
  "refresh": false,
  "page": 1,
  "per_page": 30
}'
```

**重要提示**:
- 对于大数据量场景（数万/十万文件），需要通过 `page` 和 `per_page` 参数进行分页
- `sign` 字段可用于构造下载 URL（格式通常为：`/d/<sign>/<filename>`）

---

### 3.2 获取文件或目录信息

**接口**: `POST /api/fs/get`

**说明**: 获取指定路径文件或目录的详细元数据

**请求头**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体**:
```json
{
  "path": "/document.pdf",
  "password": ""
}
```

**请求参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| path | string | 是 | 文件或目录的完整路径 |
| password | string | 否 | 私有存储的密码 |

**成功响应** (200):
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": "",
    "path": "D:\\files\\document.pdf",
    "name": "document.pdf",
    "size": 1024000,
    "is_dir": false,
    "modified": "2025-10-20T15:30:00+08:00",
    "created": "2025-10-20T10:00:00+08:00",
    "sign": "YBgnmykwCXUstXvNGtECaz_12gseXSL03cpqh5rTcGA=:0",
    "thumb": "",
    "type": 4,
    "hashinfo": "null",
    "hash_info": null,
    "mount_details": {
      "driver_name": "Local",
      "total_space": 1000000000000,
      "free_space": 500000000000
    }
  }
}
```

**响应字段说明**: 同 `/api/fs/list` 的 `content` 单项字段

**错误响应**:
- `401`: 未认证
- `404`: 文件/目录不存在

**cURL 示例**:
```bash
curl --location --request POST 'http://your-server/api/fs/get' \
--header 'Authorization: Bearer <token>' \
--header 'Content-Type: application/json' \
--data-raw '{
  "path": "/document.pdf",
  "password": ""
}'
```

**使用场景**:
- 当 `/api/fs/list` 返回的信息不包含某些字段时，可单独调用此接口获取完整信息
- 验证文件是否存在
- 获取单个文件的最新元数据

---

### 3.3 获取目录树

**接口**: `POST /api/fs/dirs`

**说明**: 获取目录结构（仅包含目录，不包含文件），用于导航

**请求头**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体**:
```json
{
  "path": "/",
  "password": "string",
  "force_root": false
}
```

**请求参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| path | string | 是 | 起始目录路径 |
| password | string | 否 | 私有存储的密码 |
| force_root | boolean | 否 | 是否强制从根目录开始 |

**成功响应** (200):
```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "name": "folder1",
      "path": "/folder1"
    },
    {
      "name": "folder2",
      "path": "/folder2"
    }
  ]
}
```

**响应字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| data | array | 目录列表 |
| data[].name | string | 目录名称 |
| data[].path | string | 目录完整路径 |

**cURL 示例**:
```bash
curl --location --request POST 'http://your-server/api/fs/dirs' \
--header 'Authorization: Bearer <token>' \
--header 'Content-Type: application/json' \
--data-raw '{
  "path": "/",
  "password": "string",
  "force_root": false
}'
```

**使用场景**:
- 前端目录选择器
- 快速获取目录层级结构
- 不需要文件信息时可减少数据传输量

---

### 3.4 搜索文件和目录

**接口**: `POST /api/fs/search`

**说明**: 在指定路径下搜索文件和目录

**请求头**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体**:
```json
{
  "path": "/",
  "keywords": "document",
  "scope": 0,
  "page": 1,
  "per_page": 30
}
```

**请求参数说明**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| path | string | 是 | 搜索起始路径 |
| keywords | string | 是 | 搜索关键词 |
| scope | integer | 否 | 搜索范围（0=当前目录，1=递归子目录） |
| page | integer | 否 | 页码 |
| per_page | integer | 否 | 每页条数 |

**成功响应** (200): 返回格式同 `/api/fs/list`

---

## 4. 公共接口 (Public)

### 4.1 获取公共设置

**接口**: `GET /api/public/settings`

**说明**: 获取 OpenList 的公共配置信息（无需认证）

**响应示例**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "title": "OpenList",
    "logo": "",
    "favicon": "",
    "announcement": "",
    "allow_indexed": true,
    "external_preview": false,
    "pagination_type": "all",
    "default_page_size": 30
  }
}
```

---

## 5. 其他接口章节索引

以下章节包含的接口可根据需要查阅原文档或告知我补充：

### 5.1 认证接口 (Authentication) - 其他
- `POST /api/auth/ldap` - LDAP 登录
- `POST /api/auth/2fa/generate` - 生成 2FA 密钥
- `POST /api/auth/2fa/verify` - 验证并启用 2FA
- `GET /api/auth/sso` - SSO 登录重定向
- `GET /api/auth/sso/callback` - SSO 回调处理
- WebAuthn 相关接口（begin/finish login/registration）

### 5.2 用户接口 (User)
- `GET /api/user/me` - 获取当前用户信息
- `POST /api/user/update` - 更新当前用户信息
- SSH 公钥管理接口

### 5.3 管理接口 (Admin)
- 用户管理（CRUD、2FA 管理、SSH key）
- 存储管理（CRUD、启用/禁用、重载）
- 驱动管理（列表、详情）
- 设置管理（CRUD、重置 API Token）
- Meta 管理
- 搜索索引管理

### 5.4 文件系统接口 (File System) - 其他
- `POST /api/fs/other` - 获取附加文件操作
- `POST /api/fs/mkdir` - 创建目录
- `POST /api/fs/rename` - 重命名文件/目录
- `POST /api/fs/batch_rename` - 批量重命名
- `POST /api/fs/regex_rename` - 正则表达式重命名
- `POST /api/fs/move` - 移动文件/目录
- `POST /api/fs/recursive_move` - 递归移动
- `POST /api/fs/copy` - 复制文件/目录
- `POST /api/fs/remove` - 删除文件/目录
- `POST /api/fs/remove_empty_directory` - 删除空目录
- `PUT /api/fs/put` - 上传文件（流式）
- `PUT /api/fs/form` - 上传文件（表单）
- `POST /api/fs/add_offline_download` - 添加离线下载任务
- `POST /api/fs/compress` - 解压归档文件
- `POST /api/fs/archive` - 获取归档元数据
- `POST /api/fs/list_archive` - 列出归档内容

### 5.5 分享接口 (Sharing)
- `POST /api/share/list` - 列出所有分享
- `GET /api/share/{id}` - 获取分享详情
- `POST /api/share/create` - 创建文件分享
- `POST /api/share/update` - 更新分享
- `POST /api/share/delete` - 删除分享
- `POST /api/share/enable` - 启用分享
- `POST /api/share/disable` - 禁用分享

---

## 6. 数据结构 (Schemas)

### 6.1 ApiResponse

通用 API 响应格式：

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

### 6.2 ErrorResponse

错误响应格式：

```json
{
  "code": 400,
  "message": "error description",
  "data": null
}
```

### 6.3 PageReq

分页请求参数：

```json
{
  "page": 1,
  "per_page": 30
}
```

### 6.4 Pagination

分页响应信息：

```json
{
  "total": 100,
  "page": 1,
  "per_page": 30
}
```

### 6.5 FsObject

文件/目录对象：

```json
{
  "id": "string",
  "path": "string",
  "name": "string",
  "size": 0,
  "is_dir": false,
  "modified": "2025-10-20T15:30:00+08:00",
  "created": "2025-10-20T10:00:00+08:00",
  "sign": "string",
  "thumb": "string",
  "type": 0,
  "hashinfo": "string",
  "hash_info": null,
  "mount_details": {
    "driver_name": "string",
    "total_space": 0,
    "free_space": 0
  }
}
```

### 6.6 FsListRequest

列目录请求：

```json
{
  "path": "/",
  "password": "",
  "refresh": false,
  "page": 1,
  "per_page": 30
}
```

### 6.7 FsListResponse

列目录响应：

```json
{
  "content": [],
  "total": 0,
  "readme": "",
  "header": "",
  "write": true,
  "provider": "Local"
}
```

### 6.8 FsGetRequest

获取文件信息请求：

```json
{
  "path": "/file.txt",
  "password": ""
}
```

### 6.9 FsGetResponse

获取文件信息响应：与 FsObject 相同

---

## 附录：CloudGather STRM 任务集成指南

### 核心流程

1. **认证**：调用 `/api/auth/login` 获取 Token
2. **遍历目录**：调用 `/api/fs/list` 递归获取所有文件
3. **生成 .strm**：
   - 对每个文件，构造下载 URL 或使用 `path` 字段
   - 写入到本地 `.strm` 文件
4. **分页处理**：对于大数据量，按 `page` 参数循环请求

### 下载 URL 构造方式

根据 OpenList 的实现，下载 URL 通常有以下几种形式：

1. **基于 sign 的下载链接**（推荐）：
   ```
   http://your-server/d/<sign>/<filename>
   ```
   其中 `sign` 和 `filename` 来自 `/api/fs/list` 响应

2. **基于 path 的访问**：
   ```
   /api/fs/get?path=<encoded_path>
   ```

3. **公共访问 URL**（如果配置了 public_url）：
   ```
   http://public-server/d/<sign>/<filename>
   ```

### Python 示例伪代码

```python
import requests

class OpenListClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.token = None
        self.login(username, password)
    
    def login(self, username, password):
        resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"username": username, "password": password}
        )
        self.token = resp.json()["data"]["token"]
    
    def list_dir(self, path="/", page=1, per_page=100):
        resp = requests.post(
            f"{self.base_url}/api/fs/list",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"path": path, "page": page, "per_page": per_page}
        )
        return resp.json()["data"]
    
    def iter_all_files(self, root_path="/"):
        """递归遍历所有文件"""
        page = 1
        while True:
            data = self.list_dir(root_path, page)
            for item in data["content"]:
                if item["is_dir"]:
                    # 递归子目录
                    yield from self.iter_all_files(item["path"])
                else:
                    yield item
            
            # 检查是否还有下一页
            if len(data["content"]) < 100:  # 假设 per_page=100
                break
            page += 1
```

---

## 更新日志

- **2026-01-08**: 初始版本，包含认证、文件系统、公共接口核心内容
- 如需补充其他章节，请告知具体接口名称

---

**参考链接**:
- 官方文档 1: https://doc.oplist.org/
- 官方文档 2: https://doc.openlist.team/
- GitHub: https://github.com/OpenListTeam/OpenList
