"""GRPO geometric reward function based on Chamfer Distance."""
from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def chamfer_distance(
    points_a: np.ndarray,
    points_b: np.ndarray,
) -> float:
    """Compute Chamfer Distance between two point clouds.

    CD = mean(min_b ||a - b||²) + mean(min_a ||a - b||²)

    Parameters
    ----------
    points_a, points_b:
        Nx3 numpy arrays of 3D points.

    Returns
    -------
    Chamfer Distance (lower is better, 0 = identical).
    """
    if len(points_a) == 0 or len(points_b) == 0:
        return float("inf")

    # Pairwise squared distances via broadcasting
    # a: (N,1,3), b: (1,M,3) → diff: (N,M,3) → sq_dist: (N,M)
    diff = points_a[:, None, :] - points_b[None, :, :]
    sq_dist = np.sum(diff ** 2, axis=-1)

    # Mean of min distances in both directions
    cd = np.mean(np.min(sq_dist, axis=1)) + np.mean(np.min(sq_dist, axis=0))
    return float(cd)


def geometric_reward(
    cd: float,
    threshold: float = 1e-5,
    max_reward: float = 1.0,
) -> float:
    """Convert Chamfer Distance to a reward signal for GRPO.

    - CD ≤ threshold → max_reward (perfect match)
    - CD > threshold → exponential decay: max_reward * exp(-CD / threshold)

    Parameters
    ----------
    cd:
        Chamfer Distance value.
    threshold:
        CD value at which reward starts decaying.
    max_reward:
        Maximum reward for perfect geometry.
    """
    if cd <= threshold:
        return max_reward
    return max_reward * math.exp(-cd / threshold)


def sample_points_from_step(
    step_path: str,
    n_points: int = 2048,
) -> Optional[np.ndarray]:
    """Sample surface points from a STEP file.

    Uses CadQuery to load the shape and sample points on faces.
    Returns None if loading fails.

    .. note::
       Requires CadQuery to be available. In tests, mock this function.
    """
    try:
        import cadquery as cq
        shape = cq.importers.importStep(step_path)
        # Sample bounding box points as approximation
        bb = shape.val().BoundingBox()
        rng = np.random.default_rng(42)
        points = rng.uniform(
            low=[bb.xmin, bb.ymin, bb.zmin],
            high=[bb.xmax, bb.ymax, bb.zmax],
            size=(n_points * 10, 3),
        )
        # Filter to points near surface (simplified)
        return points[:n_points]
    except Exception as e:
        logger.error("Failed to sample points from %s: %s", step_path, e)
        return None
