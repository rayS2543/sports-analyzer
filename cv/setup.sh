#!/usr/bin/env bash
# Reproducible local setup: venv + deps + roboflow/sports weights (~400 MB, Google Drive).
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/pip install -q --no-deps rtmlib==0.0.16  # see requirements.txt
mkdir -p weights
# Same Drive ids as roboflow/sports examples/soccer/setup.sh
get() { [ -s "weights/$1" ] || .venv/bin/gdown -q -O "weights/$1" "https://drive.google.com/uc?id=$2"; }
get football-player-detection.pt 17PXFNlx-jI7VjVo_vQnB1sONjRyvoB-q
get football-pitch-detection.pt 1Ma5Kt86tgpdjCTKfum79YMgNnSjcoOyf
get football-ball-detection.pt 1isw4wx-MK9h9LMr36VvIWlJD6ppUvw7V
# Foul review: RTMPose-x Halpe26 (feet: big toe, small toe, heel), OpenMMLab release (Apache-2.0), ~200 MB
FOOT=weights/rtmpose-x-halpe26-384x288.onnx
if [ ! -s "$FOOT" ]; then
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/m.zip" https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-x_simcc-body7_pt-body7-halpe26_700e-384x288-7fb6e239_20230606.zip
  unzip -q -j -o "$tmp/m.zip" '*end2end.onnx' -d "$tmp" && mv "$tmp/end2end.onnx" "$FOOT"
  rm -rf "$tmp"
fi
.venv/bin/python -m pytest -q
echo "ok: run with  cd cv && .venv/bin/python -m var_cv.analyze --help"
