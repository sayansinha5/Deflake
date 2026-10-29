from typing import TypedDict


class FlakeState(TypedDict, total=False):
    run_id: str
    flake_id: str
    test_id: str
    category: str
    stopped: str
    agreement_k: int
    agreement_n: int
