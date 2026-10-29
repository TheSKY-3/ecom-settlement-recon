# syntax=docker/dockerfile:1
# 对账工作台镜像：只装 Web 层运行时依赖 + 合成评测集（约 200MB）。
# 原始订单库 data/olist.db（177MB，由 Kaggle 原始数据构建）不随镜像走，按 README 挂载。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

# 先装依赖，代码或数据变化时可复用这一层缓存
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY src/ ./src/
COPY data/synthetic/ ./data/synthetic/

EXPOSE 8770

# 容器内自检：/api/overview 能正常返回即为健康（纯标准库，不额外装 curl）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8770/api/overview', timeout=3)"

CMD ["python", "-m", "src.workbench.serve", "--host", "0.0.0.0", "--port", "8770"]
