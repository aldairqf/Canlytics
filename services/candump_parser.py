from services.can_data_parser import StreamCanParser


class CandumpParser(StreamCanParser):
    def __init__(self, normalize_time: bool = False):
        super().__init__(normalize_time=normalize_time, format_hint="candump")
