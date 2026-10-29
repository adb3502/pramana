#!/bin/bash
# Round-4 Laya (ckpt4), the gate checkpoint, on 127.0.0.1:8768.
cd ~/laya && LAYA_HOST=127.0.0.1 LAYA_PORT=8768 LAYA_DEVICE=cuda LAYA_DEFAULT_MODEL=epi4 LAYA_PRELOAD=1 LAYA_MODELS=epi4 \
  LAYA_EXTRA_MODELS='{"epi4": "/home/adb/laya/ckpt4"}' exec ~/laya/.venv/bin/laya-serve
