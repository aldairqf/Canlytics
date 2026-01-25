# core/signal.py

class Signal:
    def __init__(
        self,
        name: str,
        can_id: str | None = None,
        id_match: str = "exact",
        pgn: int | None = None,
        start_bit: int = 0,
        length: int = 8,
        le: bool = True,
        scale: float = 1.0,
        offset: float = 0.0,
        mux_bytes: int = 0,
        mux_start: int = 0,
        mux_value: str | None = None,
        type_data: str = "uint"
    ):
        self.name = name
        self.can_id = can_id
        self.id_match = id_match
        self.pgn = pgn
        self.start_bit = start_bit
        self.length = length
        self.le = le
        self.scale = scale
        self.offset = offset
        self.mux_start = mux_start
        self.mux_bytes = mux_bytes
        self.mux_value = mux_value
        self.type_data = type_data
