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
# -w 1 --threads 4：单 worker 多线程
# 原因：ChromaDB PersistentClient 的内存 collection 不跨进程同步，
# 多 worker 会导致「写知识的进程」和「读知识的进程」看到不同数据，
# 必须单 worker 保证向量库内存状态一致。多线程足以应对当前流量。
CMD ["gunicorn", "-w", "1", "--threads", "4", "-t", "60", "-b", "0.0.0.0:8000", "run:app"]
