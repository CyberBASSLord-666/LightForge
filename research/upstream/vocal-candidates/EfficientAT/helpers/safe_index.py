"""Read legacy filename-index dictionaries without allowing executable pickle.

Only primitive dictionary/string/integer opcodes are accepted. This narrowly
preserves existing index data; it is not a general-purpose safe pickle loader.
"""
import io
import pickle
import pickletools

MAX_INDEX_BYTES = 128 * 1024 * 1024
MAX_MEMO_INDEX = 4_000_000
_ALLOWED_OPCODES = frozenset({
    'PROTO', 'FRAME', 'STOP', 'MARK', 'EMPTY_DICT', 'DICT', 'SETITEM', 'SETITEMS',
    'STRING', 'BINSTRING', 'SHORT_BINSTRING', 'UNICODE', 'BINUNICODE',
    'SHORT_BINUNICODE', 'BINUNICODE8', 'INT', 'BININT', 'BININT1', 'BININT2',
    'LONG', 'LONG1', 'LONG4', 'PUT', 'BINPUT', 'LONG_BINPUT', 'MEMOIZE',
    'GET', 'BINGET', 'LONG_BINGET',
})


class _IndexUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise pickle.UnpicklingError('Index pickle must not reference globals')

    def persistent_load(self, pid):
        raise pickle.UnpicklingError('Index pickle must not reference persistent objects')


def load_filename_index(stream):
    data = stream.read(MAX_INDEX_BYTES + 1)
    if len(data) > MAX_INDEX_BYTES:
        raise ValueError('Filename index exceeds maximum size')
    try:
        stop = None
        memo_size = 0
        for opcode, argument, position in pickletools.genops(data):
            if opcode.name not in _ALLOWED_OPCODES:
                raise ValueError(f'Forbidden filename-index pickle opcode: {opcode.name}')
            if opcode.name == 'MEMOIZE':
                if memo_size >= min(len(data), MAX_MEMO_INDEX):
                    raise ValueError('Filename index contains an excessive memo table')
                memo_size += 1
            if opcode.name in {'PUT', 'BINPUT', 'LONG_BINPUT', 'GET', 'BINGET', 'LONG_BINGET'}:
                if not 0 <= argument <= min(len(data), MAX_MEMO_INDEX):
                    raise ValueError('Filename index contains an excessive memo index')
                if opcode.name in {'PUT', 'BINPUT', 'LONG_BINPUT'}:
                    memo_size = max(memo_size, argument + 1)
            if opcode.name == 'FRAME' and argument > len(data) - position - 9:
                raise ValueError('Filename index frame exceeds available data')
            if opcode.name == 'STOP':
                stop = position
        if stop != len(data) - 1:
            raise ValueError('Filename index contains missing or trailing pickle data')
        result = _IndexUnpickler(io.BytesIO(data)).load()
    except (pickle.UnpicklingError, EOFError, OverflowError) as exc:
        raise ValueError('Invalid filename-index pickle') from exc
    if type(result) is not dict or any(type(k) is not str or type(v) is not int or v < 0
                                       for k, v in result.items()):
        raise ValueError('Filename index must be a dictionary of strings to nonnegative integers')
    return result
