"""
Paper Trading Execution Engine
-------------------------------
Simulates order fills in-process (no real exchange calls).
ORDERS list is the in-memory order book used by /exchange/orders/all
and /exchange/proof for audit proof.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List

ORDERS: List[Dict[str, Any]] = []


def execute_trade(symbol: str, action: str, price: float) -> Dict[str, Any]:
    """
    Record a paper trade order and return the filled order dict.

    Parameters
    ----------
    symbol : trading pair, e.g. "BTCUSDT"
    action : "BUY" or "SELL"
    price  : current market price
    """
    order: Dict[str, Any] = {
        "orderId": str(uuid.uuid4()),
        "symbol": symbol,
        "side": action,
        "price": price,
        "status": "FILLED",
        "execution_mode": "paper",
        "timestamp": datetime.utcnow().isoformat(),
    }
    ORDERS.append(order)
    return order
