# 使用轻量级 Python 镜像
FROM python:3.9-slim

# 设置容器内的工作目录
WORKDIR /app

# 1. 复制依赖清单
COPY requirements.txt .

# 2. 安装依赖 (使用清华源加速)
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 复制后端代码
COPY app.py .

# 4. 复制前端页面
COPY fujifilm_inventory_api.html .

# 5. [核心修复] 集成预置数据到应用目录 (/app/data)
# 创建目录结构
RUN mkdir -p /app/data/uploads

# 将本地 data 目录下的文件复制到容器的 /app/data 目录下
# 注意：目标路径必须写全 /app/data/
COPY data/products.json /app/data/
COPY data/uploads/ /app/data/uploads/

# 6. 定义应用数据目录为 Volume
# 这样启动时如果用户挂载了 volume，数据会持久化；没挂载则使用上面的预置数据
VOLUME /app/data

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["python", "app.py"]