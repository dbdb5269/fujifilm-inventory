# 使用轻量级 Python 镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 1. 复制依赖清单
COPY requirements.txt .

# 2. 安装依赖 (保留了清华源加速)
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 复制后端代码
COPY app.py .

# 4. 复制前端页面 (这是新增的关键一步，因为不再有 Nginx 了)
COPY fujifilm_inventory_api.html .

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["python", "app.py"]