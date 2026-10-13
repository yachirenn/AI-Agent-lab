import os
from decimal import ROUND_DOWN, Decimal


def points_for_kwh(kwh: Decimal) -> int:
    """Pakai Decimal, bukan float: 0.1 + 0.2 != 0.3 di float, dan uang/poin tidak boleh meleset."""
    rate = Decimal(os.environ.get("POINTS_PER_KWH", "10"))
    return int((kwh * rate).to_integral_value(rounding=ROUND_DOWN))