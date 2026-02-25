import argparse
import json
import os

import streamlit as st
from PIL import Image
from dotenv import load_dotenv

load_dotenv()
from cad3dify import generate_step_from_2d_cad_image, generate_step_v2


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_type", type=str, default="qwen")
    return parser.parse_args()


args = parse_args()

st.title("2D図面 → 3D CAD")

# 侧边栏
st.sidebar.header("设置")
pipeline_mode = st.sidebar.radio(
    "管道模式",
    ["v2 增强 (推荐)", "v1 经典"],
    index=0,
)
if pipeline_mode == "v1 经典":
    model_type = st.sidebar.selectbox(
        "模型",
        ["qwen", "qwen-vl", "gpt", "claude", "gemini"],
        index=0,
    )

uploaded_file = st.sidebar.file_uploader("上传工程图纸", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    ext = os.path.splitext(uploaded_file.name)[1].lstrip(".")
    st.image(image, caption="上传的图纸", use_column_width=True)
    st.write(f"图像尺寸: {image.size[0]} × {image.size[1]}")

    temp_file = f"temp.{ext}"
    with open(temp_file, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if pipeline_mode == "v2 增强 (推荐)":
        # V2 模式：显示中间结果
        spec_container = st.empty()
        progress_container = st.empty()
        # 用列表存储可变状态（Python 闭包需要可变容器）
        progress_state = {"geometry": None, "rounds": []}

        def on_spec_ready(spec, reasoning=None):
            with spec_container.container():
                st.subheader("📐 图纸分析结果")
                if reasoning:
                    with st.expander("📝 CoT 推理过程", expanded=False):
                        st.code(reasoning, language=None)
                st.write(f"**零件类型:** {spec.part_type.value}")
                st.write(f"**描述:** {spec.description}")
                st.write(f"**总体尺寸:** {spec.overall_dimensions}")
                with st.expander("详细 JSON", expanded=False):
                    st.json(spec.model_dump())

        def on_progress(stage, data):
            if stage == "geometry":
                progress_state["geometry"] = data
            elif stage == "refinement_round":
                progress_state["rounds"].append(data)

            with progress_container.container():
                geo = progress_state["geometry"]
                if geo is not None:
                    if geo["is_valid"]:
                        bbox = geo["bbox"]
                        if bbox:
                            st.success(
                                f"✅ 几何验证通过 — 体积: {geo['volume']:.1f} mm³, "
                                f"包围盒: {bbox[0]:.0f}×{bbox[1]:.0f}×{bbox[2]:.0f} mm"
                            )
                        else:
                            st.success(f"✅ 几何验证通过 — 体积: {geo['volume']:.1f} mm³")
                    else:
                        st.error(f"❌ 几何验证失败: {geo['error']}")

                if progress_state["rounds"]:
                    st.write("**改进轮次状态:**")
                    for rd in progress_state["rounds"]:
                        status = rd["status"]
                        if status == "PASS":
                            icon = "✅"
                        elif status == "refined":
                            icon = "🔄"
                        else:
                            icon = "⚠️"
                        st.write(
                            f"  {icon} 第 {rd['round']}/{rd['total']} 轮: {status}"
                        )

        with st.spinner("V2 管道处理中..."):
            generate_step_v2(
                temp_file, "output.step",
                on_spec_ready=on_spec_ready,
                on_progress=on_progress,
            )
        st.success("3D CAD 模型生成完成!")
    else:
        # V1 经典模式
        with st.spinner("处理中..."):
            generate_step_from_2d_cad_image(
                temp_file, "output.step", model_type=model_type
            )
        st.success("3D CAD 模型生成完成!")
else:
    st.info("请在左侧上传工程图纸。")
