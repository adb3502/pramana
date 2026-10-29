#!/bin/bash
# Fine-tuned Laya: epi (ckpt1) and epi2 (ckpt2) on 127.0.0.1:8766, default epi2. Logs: logs/laya_server_epi.log
cd ~/laya && LAYA_HOST=127.0.0.1 LAYA_PORT=8766 LAYA_DEVICE=cuda LAYA_DEFAULT_MODEL=epi2 LAYA_PRELOAD=1 LAYA_MODELS=epi,epi2 \
  LAYA_EXTRA_MODELS='{"epi": "/home/adb/laya/ckpt1", "epi2": "/home/adb/laya/ckpt2"}' exec ~/laya/.venv/bin/laya-serve
