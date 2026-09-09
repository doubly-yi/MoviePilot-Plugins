"""Envelope codec."""
import base64
import json
import struct
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _constants():
    data = json.loads(Path(__file__).with_name("codec_tables.json").read_text())
    tables = {}
    for name, encoded in data["tables"].items():
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) not in (256, 1024):
            raise ValueError("Invalid codec table")
        tables[name] = struct.unpack("<256I", raw) if len(raw) == 1024 else raw
    return data["keys"], tables


def parse_wbc_key(value: str):
    raw = bytes.fromhex(value)
    if len(raw) < 5:
        raise ValueError("Invalid codec key")
    mode = raw[0] ^ raw[3]
    sizes = (128, 192, 128, 64, 192, 128, 128, 192, 256, 64, 192, 128)
    if mode // 2 >= len(sizes):
        raise ValueError("Unknown codec mode")
    rounds = (sizes[mode // 2] >> 5) + 6
    key = bytes(raw[i] ^ raw[i % 3] for i in range(4, len(raw)))
    if len(key) < (rounds + 1) * 16:
        raise ValueError("Truncated codec key")
    return key, rounds


def _xor(table, a: int, b: int) -> int:
    return (table[((a >> 4) << 4) ^ (b >> 4)] & 0xf0) | ((table[((a & 15) << 4) ^ (b & 15)] >> 4) & 15)


def wbc_block(block: bytes, key: bytes, rounds: int, decrypt=False) -> bytes:
    if len(block) != 16:
        raise ValueError("Invalid codec block size")
    _, tables = _constants()
    prefix = "dec" if decrypt else "enc"
    state = [_xor(tables[prefix + "InitXor"], block[i], key[i]) for i in range(16)]
    xor = tables[prefix + "RoundXor"]
    indices = ([0, 4, 8, 12], [13, 1, 5, 9] if decrypt else [5, 9, 13, 1],
               [10, 14, 2, 6], [7, 11, 15, 3] if decrypt else [15, 3, 7, 11])
    for r in range(1, rounds):
        combined = []
        for n in range(4):
            table = tables[prefix + ("Td" if decrypt else "Te") + str(n)]
            current = b"".join(struct.pack(">I", table[state[i]]) for i in indices[n])
            combined = list(current) if n == 0 else [_xor(xor, a, b) for a, b in zip(combined, current)]
        state = [_xor(xor, combined[i], key[r * 16 + i]) for i in range(16)]
    shift = ([0, 13, 10, 7, 4, 1, 14, 11, 8, 5, 2, 15, 12, 9, 6, 3] if decrypt
             else [0, 5, 10, 15, 4, 9, 14, 3, 8, 13, 2, 7, 12, 1, 6, 11])
    sbox = tables[prefix + ("InvSbox" if decrypt else "Sbox")]
    return bytes(_xor(tables[prefix + "FinalXor"], sbox[state[shift[i]]], key[rounds * 16 + i]) for i in range(16))


def wbc_cbc(data: bytes, key_hex: str, iv: bytes, decrypt=False) -> bytes:
    if len(data) % 16 or len(iv) != 16:
        raise ValueError("Invalid codec CBC length")
    key, rounds = parse_wbc_key(key_hex)
    result = bytearray()
    previous = iv
    for offset in range(0, len(data), 16):
        block = data[offset:offset + 16]
        if decrypt:
            decoded = wbc_block(block, key, rounds, True)
            result.extend(a ^ b for a, b in zip(decoded, previous))
            previous = block
        else:
            previous = wbc_block(bytes(a ^ b for a, b in zip(block, previous)), key, rounds)
            result.extend(previous)
    return bytes(result)


ENCODE = (0, 8, 4, 12, 1, 9, 5, 13, 2, 10, 6, 14, 3, 11, 7, 15)
DECODE = (0, 4, 8, 12, 2, 6, 10, 14, 1, 5, 9, 13, 3, 7, 11, 15)
MYSTERY = tuple(ENCODE[ENCODE[n ^ 8]] for n in range(16))
TRANSFORM = tuple(ENCODE[ENCODE[n]] for n in range(16))


def _nibble(data: bytes, table) -> bytes:
    return bytes((table[b >> 4] << 4) | table[b & 15] for b in data)


def _pad(data: bytes) -> bytes:
    size = 16 - len(data) % 16
    return data + bytes([size]) * size


def _strip(data: bytes) -> bytes:
    if data and 1 <= data[-1] <= 16 and data[-data[-1]:] == bytes([data[-1]]) * data[-1]:
        return data[:-data[-1]]
    return data


def encrypt_envelope(plaintext: str) -> str:
    keys, _ = _constants()
    inner_iv = bytes.fromhex(keys["innerEncryptIv"])
    inner = wbc_cbc(_nibble(_pad(plaintext.encode()), MYSTERY), keys["innerEncryptKey"], inner_iv)
    outer_plain = base64.b64encode(_nibble(inner, TRANSFORM)) + _nibble(inner_iv, TRANSFORM)
    outer = wbc_cbc(_nibble(_pad(outer_plain), MYSTERY), keys["outerEncryptKey"], bytes.fromhex(keys["outerEncryptIv"]))
    return base64.b64encode(_nibble(outer, TRANSFORM)).decode()


def decrypt_envelope(encoded: str) -> str:
    keys, _ = _constants()
    raw = base64.b64decode(encoded, validate=True)
    if not raw or len(raw) % 16:
        raise ValueError("Invalid codec envelope")
    outer = wbc_cbc(_nibble(raw, ENCODE) + bytes(256), keys["outerDecryptKey"], bytes.fromhex(keys["outerDecryptIv"]), True)
    content = _strip(_nibble(outer[:len(raw)], DECODE))
    size = len(content)
    if size < 16:
        raise ValueError("Truncated codec envelope")
    inner_raw = base64.b64decode(content[:-16], validate=True)
    if not inner_raw or len(inner_raw) % 16:
        raise ValueError("Invalid codec inner envelope")
    inner = wbc_cbc(_nibble(inner_raw, ENCODE) + bytes(256), keys["innerDecryptKey"], outer[size - 16:size], True)
    return _strip(_nibble(inner[:len(inner_raw)], DECODE)).decode()
