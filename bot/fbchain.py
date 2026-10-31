"""Pure-python Solana helpers for the rugcheck fallback (read-only): base58, PDA derivation, raw account reads."""
import hashlib, base64
from common import rpc
A = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58d(s):
    n = 0
    for ch in s: n = n * 58 + A.index(ch)
    b = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + b
def b58e(b):
    n = int.from_bytes(b, "big"); s = ""
    while n: n, r = divmod(n, 58); s = A[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s
P_ = 2 ** 255 - 19; D_ = (-121665 * pow(121666, P_ - 2, P_)) % P_
def on_curve(b):
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= P_: return False
    u = (y * y - 1) % P_; v = (D_ * y * y + 1) % P_
    x2 = u * pow(v, P_ - 2, P_) % P_
    return x2 == 0 or pow(x2, (P_ - 1) // 2, P_) == 1
def pda(seeds, program):
    pid = b58d(program)
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"".join(seeds) + bytes([bump]) + pid + b"ProgramDerivedAddress").digest()
        if not on_curve(h): return b58e(h)
    raise ValueError("no pda")
def raw(addr):
    v = rpc("getAccountInfo", [addr, {"encoding": "base64"}])["value"]
    return None if v is None else (v["owner"], base64.b64decode(v["data"][0]))
def u64(b, o): return int.from_bytes(b[o:o + 8], "little")
def pk(b, o): return b58e(b[o:o + 32])
