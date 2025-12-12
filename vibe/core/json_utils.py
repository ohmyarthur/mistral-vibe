from __future__ import annotations

import json
from typing import Any, TextIO

try:
    import orjson
except ImportError:
    orjson = None


ORJSON_INDENT_2 = 2


def dumps_bytes(
    obj: Any, *, indent: int | None = None, ensure_ascii: bool = True
) -> bytes:
    if orjson is not None:
        option = 0
        if ensure_ascii:
            option |= int(getattr(orjson, "OPT_ESCAPE_UNICODE", 0))
        if indent is None:
            return orjson.dumps(obj, option=option)
        if indent == ORJSON_INDENT_2:
            return orjson.dumps(obj, option=option | orjson.OPT_INDENT_2)

    return json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent).encode("utf-8")


def dumps(obj: Any, *, indent: int | None = None, ensure_ascii: bool = True) -> str:
    return dumps_bytes(obj, indent=indent, ensure_ascii=ensure_ascii).decode("utf-8")


def loads(data: str | bytes | bytearray | memoryview) -> Any:
    if orjson is not None:
        if isinstance(data, str):
            return orjson.loads(data.encode("utf-8"))
        return orjson.loads(data)
    if isinstance(data, (bytes, bytearray, memoryview)):
        data = bytes(data).decode("utf-8")
    return json.loads(data)


def dump(
    obj: Any, fp: TextIO, *, indent: int | None = None, ensure_ascii: bool = True
) -> None:
    fp.write(dumps(obj, indent=indent, ensure_ascii=ensure_ascii))
