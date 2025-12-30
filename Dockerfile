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

# 4. 复制前端页面 (确保文件名正确)
COPY fujifilm_inventory_api.html .

# 5. 集成预置数据 (核心修改)
# 创建容器内的目录结构
RUN mkdir -p /data/uploads

# 将本地 data 目录下的 products.json 和 uploads 图片复制到镜像内
# 注意：构建时请确保您的项目根目录下存在 data 文件夹及其内容
COPY data/products.json /data/
COPY data/uploads/ /data/uploads/

# 6. (可选) 创建数据目录挂载点
# 提醒：如果运行时使用 -v 挂载了宿主机目录到 /data，宿主机目录会覆盖镜像内的 /data
VOLUME /data

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["python", "app.py"]