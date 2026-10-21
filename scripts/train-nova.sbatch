#!/bin/bash
# Submit from the repository root with YOUR account/partition, for example:
# sbatch -A YOUR_ACCOUNT -p YOUR_PARTITION scripts/train-nova.sbatch /absolute/path/dataset.yaml
# Activate a CUDA-capable Python environment before submission.
#SBATCH --job-name=minis-pose
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=minis-%j.out
set -euo pipefail

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo "Submit with sbatch; do not run training on a login node." >&2
  exit 1
fi
dataset_path="${1:?Pass the prepared pose dataset.yaml as the first argument}"
python - "$dataset_path" <<'PY'
import sys
from pathlib import Path
import yaml
import torch
path = Path(sys.argv[1]).resolve()
with path.open() as stream:
    config = yaml.safe_load(stream)
if config.get("kpt_shape") != [1, 3]:
    raise SystemExit("Use the reviewed one-base-keypoint pose dataset, not the raw detection export")
if not torch.cuda.is_available():
    raise SystemExit("Allocated environment cannot use CUDA; check PyTorch and your GPU allocation")
print("Dataset:", path)
print("GPU:", torch.cuda.get_device_name(0), flush=True)
PY
python -m token_tracker.dataset train "$dataset_path" --device 0 --epochs "${EPOCHS:-60}" --imgsz 960
