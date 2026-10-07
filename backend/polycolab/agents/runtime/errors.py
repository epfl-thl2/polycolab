"""Stable private runtime conflict codes, shared by services and HTTP adapters."""


class RuntimeApiConflict(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
