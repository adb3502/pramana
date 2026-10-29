#!/bin/bash
# Round-3 Laya (ckpt3: oversampled Opus rulings, is_datum, header/label/section state) on 127.0.0.1:8767. Evaluation server; 8766 (epi2) stays.
cd ~/laya && LAYA_HOST=127.0.0.1 LAYA_PORT=8767 LAYA_DEVICE=cuda LAYA_DEFAULT_MODEL=epi3 LAYA_PRELOAD=1 LAYA_MODELS=epi3 \
  LAYA_EXTRA_MODELS='{"epi3": "/home/adb/laya/ckpt3"}' exec ~/laya/.venv/bin/laya-serve
