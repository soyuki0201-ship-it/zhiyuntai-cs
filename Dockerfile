FROM python:3.11-slim

WORKDIR /app

# 复制依赖文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "run:app"]
