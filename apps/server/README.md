# LifeOS Server

```powershell
# 环境(工作区内)
$env:Path = "C:\Users\zdl20\.local\bin;$env:Path"
$env:UV_CACHE_DIR = "D:\ai\code\.uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "D:\ai\code\.uv-python"

cd D:\ai\code\lifeos\apps\server
uv venv --python 3.12 .venv
.venv\Scripts\python -m uv pip install -e ".[dev]"

# 启动
.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload

# 测试
.venv\Scripts\python -m pytest
```
