#!/bin/bash
# Local Laya server (own venv), loopback only. Logs: logs/laya_server.log
cd ~/laya && LAYA_HOST=127.0.0.1 LAYA_PORT=8765 LAYA_DEVICE=cuda LAYA_DEFAULT_MODEL=english LAYA_PRELOAD=1 LAYA_MODELS=english \
  exec ~/laya/.venv/bin/laya-serve
