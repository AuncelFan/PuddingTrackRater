# PuddingTrackRater

KML 轨迹难度评测器。

## 环境搭建

```bash
uv sync --dev
```

首次使用前如果尚未安装 `uv`，请先按照官方文档安装：
<https://docs.astral.sh/uv/getting-started/installation/>。

更新依赖锁文件或同步环境：

```bash
uv lock
uv sync --dev
```

## 调试运行

```bash
uv run python run.py
```

服务启动后访问 <http://127.0.0.1:5000>，交互式 API 文档位于
<http://127.0.0.1:5000/docs>。

## 后端结构

- `app/main.py`：FastAPI 应用、接口与静态文件服务。
- `app/rater/rater.py`：`Rater` 评分器，负责 KML 解析、轨迹预处理和难度计算。

## 部署前检查

当前发布版本的 `app/static/dist` 中已包含构建好的前端静态文件。使用该版本进行
Uvicorn 或 Docker 部署时，无需重复安装 Node.js 或重新构建前端；部署前请确认
`app/static/dist/index.html` 和 `app/static/dist/assets/` 存在且内容完整。

如果修改了 `frontend/` 中的前端源码，或者 `app/static/dist` 缺失、内容过期，
请在部署前使用以下命令重新生成静态文件：

```bash
cd frontend
npm ci
npm run build
cd ..
```

## 部署运行

```bash
uv run uvicorn app:app --host 0.0.0.0 --port 5000 --workers 2
```

## Docker 部署

Docker 镜像会直接复制 `app/static/dist` 中已有的前端静态文件，不会在镜像构建
过程中安装 Node.js 或重复构建前端。

使用 Docker Compose 构建并启动：

```bash
docker compose up --build -d
```

服务启动后访问 <http://127.0.0.1:5000>，停止服务：

```bash
docker compose down
```

也可以直接构建和运行镜像：

```bash
docker build -t pudding-track-rater .
docker run --rm -p 5000:5000 pudding-track-rater
```

## 测试

```bash
uv run pytest
```
