"""SFT and GRPO training configuration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SFTConfig:
    """Configuration for SFT (Supervised Fine-Tuning)."""
    base_model: str = "Qwen/Qwen2.5-Coder-7B"
    dataset_path: str = ""
    output_dir: str = "outputs/sft"
    num_epochs: int = 3
    batch_size: int = 4
    learning_rate: float = 2e-5
    max_seq_length: int = 4096
    lora_rank: int = 16
    lora_alpha: int = 32


@dataclass
class GRPOConfig:
    """Configuration for GRPO (Group Relative Policy Optimization)."""
    sft_model_path: str = ""
    output_dir: str = "outputs/grpo"
    num_epochs: int = 1
    batch_size: int = 2
    group_size: int = 4
    kl_coeff: float = 0.1
    reward_threshold: float = 1e-5  # Chamfer Distance threshold for full score


@dataclass
class EvalMetrics:
    """Evaluation metrics for a fine-tuned model."""
    compile_rate: float = 0.0
    execute_rate: float = 0.0
    chamfer_distance_mean: float = float("inf")
    chamfer_distance_median: float = float("inf")
    sample_count: int = 0
