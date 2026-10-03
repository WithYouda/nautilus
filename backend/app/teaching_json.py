"""Stream only the reply from a bounded, strictly validated teaching envelope."""

import json
import math


_WHITESPACE = ' \t\r\n'
_FIELDS = {'reply', 'teaching', 'token'}
_VALUE_STARTS = '"{[tfn-0123456789'
_ESCAPES = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f',
            'n': '\n', 'r': '\r', 't': '\t'}


class _InvalidJson(ValueError):
    pass


class _InvalidSchema(ValueError):
    pass


class _Oversized(ValueError):
    pass


class _StringDecoder:
    """Decode one JSON string with only a fixed-size escape carry."""

    __slots__ = ('_state', '_value', '_digits', '_high')

    def __init__(self):
        self._state = 'text'
        self._value = 0
        self._digits = 0
        self._high = 0

    def feed(self, char: str) -> tuple[str, bool]:
        if self._state == 'text':
            if char == '"':
                return '', True
            if char == '\\':
                self._state = 'escape'
                return '', False
            if ord(char) < 0x20 or 0xD800 <= ord(char) <= 0xDFFF:
                raise _InvalidJson
            return char, False
        if self._state == 'escape':
            if char == 'u':
                self._state = 'unicode'
                self._value = self._digits = 0
                return '', False
            if char not in _ESCAPES:
                raise _InvalidJson
            self._state = 'text'
            return _ESCAPES[char], False
        if self._state == 'low_backslash':
            if char != '\\':
                raise _InvalidJson
            self._state = 'low_u'
            return '', False
        if self._state == 'low_u':
            if char != 'u':
                raise _InvalidJson
            self._state = 'low_unicode'
            self._value = self._digits = 0
            return '', False
        if char not in '0123456789abcdefABCDEF':
            raise _InvalidJson
        self._value = (self._value << 4) | int(char, 16)
        self._digits += 1
        if self._digits < 4:
            return '', False
        value = self._value
        if self._state == 'low_unicode':
            if not 0xDC00 <= value <= 0xDFFF:
                raise _InvalidJson
            self._state = 'text'
            return chr(0x10000 + ((self._high - 0xD800) << 10) + value - 0xDC00), False
        if 0xD800 <= value <= 0xDBFF:
            self._high = value
            self._state = 'low_backslash'
            return '', False
        if 0xDC00 <= value <= 0xDFFF:
            raise _InvalidJson
        self._state = 'text'
        return chr(value), False


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidSchema
        result[key] = value
    return result


def _invalid_constant(_value):
    raise _InvalidJson


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise _InvalidJson
    return number


class JsonTeachingDecoder:
    """Extract root ``reply`` text without retaining it or exposing metadata.

    ``max_metadata`` bounds retained Unicode characters, including JSON framing
    and an empty-string placeholder for the reply. Reply length is unlimited.
    Only unescaped JSON control characters are rejected; valid escaped controls
    are decoded normally. ``finish`` is idempotent and seals further input.
    Teaching semantics and provider completion are the caller's responsibility.
    """

    __slots__ = ('_token', '_max_metadata', '_metadata', '_metadata_length',
                 '_state', '_string', '_key_parts', '_field', '_seen', '_stack',
                 '_proposal', '_finished', 'reason', 'reply_length')

    def __init__(self, token: str, max_metadata: int = 16384):
        if max_metadata < 0:
            raise ValueError('max_metadata must be nonnegative')
        self._token = token
        self._max_metadata = max_metadata
        self._metadata = []
        self._metadata_length = 0
        self._state = 'start'
        self._string = None
        self._key_parts = []
        self._field = None
        self._seen = set()
        self._stack = []
        self._proposal = None
        self._finished = False
        self.reason = None
        self.reply_length = 0

    def _append(self, char):
        if self._metadata_length >= self._max_metadata:
            raise _Oversized
        self._metadata.append(char)
        self._metadata_length += 1

    def _fail(self, reason):
        if self.reason is None:
            self.reason = reason
        self._metadata.clear()
        self._key_parts.clear()
        self._stack.clear()
        self._string = None
        self._proposal = None

    def feed(self, text: str) -> str:
        if self._finished or self.reason is not None:
            return ''
        emitted = []
        for char in text:
            try:
                piece = self._consume(char)
            except _Oversized:
                self._fail('envelope_oversized')
                break
            except _InvalidSchema:
                self._fail('envelope_invalid_schema')
                break
            except _InvalidJson:
                self._fail('envelope_invalid_json')
                break
            if piece:
                emitted.append(piece)
                self.reply_length += len(piece)
        return ''.join(emitted)

    def _consume(self, char):
        if self._state == 'reply':
            piece, closed = self._string.feed(char)
            if closed:
                self._string = None
                self._state = 'after_value'
            return piece

        self._append(char)
        if self._state == 'key':
            piece, closed = self._string.feed(char)
            if piece:
                self._key_parts.append(piece)
            if closed:
                key = ''.join(self._key_parts)
                self._key_parts.clear()
                self._string = None
                if key not in _FIELDS or key in self._seen:
                    raise _InvalidSchema
                self._seen.add(key)
                self._field = key
                self._state = 'colon'
            return ''
        if self._state == 'token':
            _, closed = self._string.feed(char)
            if closed:
                self._string = None
                self._state = 'after_value'
            return ''
        if self._state == 'metadata':
            if self._string is not None:
                _, closed = self._string.feed(char)
                if closed:
                    self._string = None
            elif char == '"':
                self._string = _StringDecoder()
            elif char in '{[':
                self._stack.append('}' if char == '{' else ']')
            elif char in '}]':
                if char != self._stack.pop():
                    raise _InvalidJson
                if not self._stack:
                    self._state = 'after_value'
            elif (ord(char) < 0x20 and char not in _WHITESPACE) or 0xD800 <= ord(char) <= 0xDFFF:
                raise _InvalidJson
            return ''
        if char in _WHITESPACE:
            return ''
        if self._state == 'start':
            if char != '{':
                raise _InvalidSchema if char in _VALUE_STARTS else _InvalidJson
            self._state = 'first_key'
        elif self._state in {'first_key', 'next_key'}:
            if char == '}' and self._state == 'first_key':
                self._state = 'done'
            elif char == '"':
                self._string = _StringDecoder()
                self._state = 'key'
            else:
                raise _InvalidJson
        elif self._state == 'colon':
            if char != ':':
                raise _InvalidJson
            self._state = 'value'
        elif self._state == 'value':
            if self._field == 'teaching' and char == '{':
                self._stack.append('}')
                self._state = 'metadata'
            elif self._field in {'reply', 'token'} and char == '"':
                self._string = _StringDecoder()
                self._state = self._field
                if self._field == 'reply':
                    self._append('"')  # Replace the streamed reply with an empty JSON string.
            else:
                raise _InvalidSchema if char in _VALUE_STARTS else _InvalidJson
        elif self._state == 'after_value':
            if char == ',':
                self._state = 'next_key'
            elif char == '}':
                self._state = 'done'
            else:
                raise _InvalidJson
        else:  # Only whitespace may follow the completed root object.
            raise _InvalidJson
        return ''

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self.reason is not None:
            return
        if self._state != 'done':
            self._fail('envelope_incomplete')
            return
        try:
            envelope = json.loads(''.join(self._metadata), object_pairs_hook=_strict_object,
                                  parse_constant=_invalid_constant, parse_float=_finite_float)
        except _InvalidSchema:
            self._fail('envelope_invalid_schema')
            return
        except (ValueError, RecursionError, OverflowError):
            self._fail('envelope_invalid_json')
            return
        if (set(envelope) != _FIELDS or not isinstance(envelope['reply'], str)
                or not isinstance(envelope['teaching'], dict) or not isinstance(envelope['token'], str)):
            self._fail('envelope_invalid_schema')
        elif envelope['token'] != self._token:
            self._fail('envelope_token_mismatch')
        else:
            self._proposal = envelope['teaching']
            self._metadata.clear()

    def proposal(self) -> dict | None:
        return self._proposal
