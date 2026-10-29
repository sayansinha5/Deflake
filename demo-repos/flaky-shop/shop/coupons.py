import random
from dataclasses import dataclass

# No 0/O, 1/I/L: codes are read out over the phone.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 2


@dataclass(frozen=True)
class Coupon:
    code: str
    percent: float


def generate_code() -> str:
    return "".join(random.choice(ALPHABET) for _ in range(CODE_LENGTH))


def generate_batch(count: int, percent: float) -> list[Coupon]:
    if not 0 < percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return [Coupon(generate_code(), percent) for _ in range(count)]


def redeem(coupons: list[Coupon], code: str) -> Coupon:
    for coupon in coupons:
        if coupon.code == code.upper():
            return coupon
    raise KeyError(code)
