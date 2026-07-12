from __future__ import annotations


class DbcPayload:
    """DBC-style byte/bit addressing over a raw CAN payload."""

    @staticmethod
    def extract_bits(payload: bytes, start_bit: int, length: int, le: bool) -> int:
        """le=True: start_bit is the LSB (Intel). le=False: start_bit is the MSB (Motorola)."""
        data_int = int.from_bytes(payload, byteorder="little", signed=False)
        raw = 0
        if le:
            for i in range(length):
                raw |= ((data_int >> (start_bit + i)) & 1) << i
            return raw

        byte = start_bit // 8
        bit = start_bit % 8
        for i in range(length):
            raw |= ((data_int >> (byte * 8 + bit)) & 1) << (length - 1 - i)
            if bit > 0:
                bit -= 1
            else:
                byte += 1
                bit = 7
        return raw

    @staticmethod
    def mux_value(payload: bytes, start: int, length: int) -> int:
        """Big-endian value of ``length`` bytes at ``start``; missing trailing bytes count as zero."""
        value = 0
        for i in range(length):
            idx = start + i
            if idx < len(payload):
                value += payload[idx] << (8 * (length - 1 - i))
        return value
