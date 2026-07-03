@echo off
chcp 65001 >nul
title 档案管理系统

python -c "import paddleocr" >nul 2>&1
if errorlevel 1 (
    echo [初始化] 正在安装依赖包...
    pip install paddleocr>=3.7.0 onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
)

echo [初始化] 检查OCR模型...
python -c "
from paddleocr import PaddleOCR
print('模型检查完成')
" 2>nul || echo [提示] OCR模型将在首次识别时自动下载，约需150MB空间

echo [启动] 正在启动档案管理系统...
python archive_tool/main.py