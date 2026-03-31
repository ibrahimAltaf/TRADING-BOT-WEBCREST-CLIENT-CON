# BTC/USDT production LSTM (5m)

Train on a machine with TensorFlow:

```bash
export PYTHONPATH=.
python scripts/train_btc_production.py --interval 5m --limit 8000 --epochs 32
```

Outputs here: `model.keras`, `scaler.json`, `scaler.pkl`, `meta.json`, `dataset.npz`.

Point `ML_MODEL_DIR=models/btc_usdt_5m` in `.env`.
