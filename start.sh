#!/bin/bash
# cad3dify 启动脚本
# 用法:
#   ./start.sh              # 默认 Qwen 模型 + Web UI
#   ./start.sh qwen         # Qwen 模型 + Web UI
#   ./start.sh claude       # Claude 模型 + Web UI
#   ./start.sh gemini       # Gemini 模型 + Web UI
#   ./start.sh cli image.jpg # CLI 模式，直接传图片

cd "$(dirname "$0")"
source .venv/bin/activate

MODEL_TYPE="${1:-qwen}"

if [ "$MODEL_TYPE" = "cli" ]; then
    IMAGE_PATH="$2"
    OUTPUT_PATH="${3:-output.step}"
    if [ -z "$IMAGE_PATH" ]; then
        echo "用法: ./start.sh cli <图片路径> [输出路径]"
        exit 1
    fi
    cd scripts
    python cli.py "$IMAGE_PATH" --output_filepath "$OUTPUT_PATH"
else
    cd scripts
    echo "🚀 启动 cad3dify Web UI (模型: $MODEL_TYPE)"
    echo "   浏览器打开: http://localhost:8501"
    streamlit run app.py -- --model_type "$MODEL_TYPE"
fi
