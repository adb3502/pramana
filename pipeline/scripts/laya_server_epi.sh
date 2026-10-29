#!/bin/bash
# Fine-tuned Laya (ckpt1) as model "epi" on 127.0.0.1:8766. Logs: logs/laya_server_epi.log
cd ~/laya && LAYA_HOST=127.0.0.1 LAYA_PORT=8766 LAYA_DEVICE=cuda LAYA_DEFAULT_MODEL=epi LAYA_PRELOAD=1 LAYA_MODELS=epi \
  LAYA_EXTRA_MODELS='{"epi": "/home/adb/laya/ckpt1"}' exec ~/laya/.venv/bin/laya-serve
