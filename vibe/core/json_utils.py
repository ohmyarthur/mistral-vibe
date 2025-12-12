from __future__ import annotations

from importlib.util import find_spec
import json
from typing import Any, TextIO


_HAS_ORJSON = find_spec("orjson") is not None
if _HAS_ORJSON:
    import orjson


def dumps_bytes(
    obj: Any,
    *,
    indent: int | None = None,
    ensure_ascii: bool = True,
) -> bytes:
    if _HAS_ORJSON:
        option = 0
        if ensure_ascii and hasattr(orjson, "OPT_ESCAPE_UNICODE"):
            option |= orjson.OPT_ESCAPE_UNICODE
        if indent is None:
            return orjson.dumps(obj, option=option)
        if indent == 2:
            return orjson.dumps(obj, option=option | orjson.OPT_INDENT_2)

    return json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent).encode("utf-8")


def dumps(
    obj: Any,
    *,
    indent: int | None = None,
    ensure_ascii: bool = True,
) -> str:
    return dumps_bytes(obj, indent=indent, ensure_ascii=ensure_ascii).decode("utf-8")


def loads(data: str | bytes | bytearray | memoryview) -> Any:
    if _HAS_ORJSON:
        if isinstance(data, str):
            return orjson.loads(data.encode("utf-8"))
        return orjson.loads(data)
    if isinstance(data, (bytes, bytearray, memoryview)):
        data = bytes(data).decode("utf-8")
    return json.loads(data)


def dump(
    obj: Any,
    fp: TextIO,
    *,
    indent: int | None = None,
    ensure_ascii: bool = True,
) -> None:
    fp.write(dumps(obj, indent=indent, ensure_ascii=ensure_ascii))
