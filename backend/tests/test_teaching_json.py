"""Streaming text, strict framing, and bounded teaching metadata."""

import itertools
import json

import pytest

from app.teaching_json import JsonTeachingDecoder


TOKEN = 'synthetic-token'


def envelope(reply, teaching=None):
    return json.dumps({'reply': reply, 'teaching': teaching or {}, 'token': TOKEN}, ensure_ascii=False)


def decode_chunks(chunks, **kwargs):
    decoder = JsonTeachingDecoder(TOKEN, **kwargs)
    reply = ''.join(decoder.feed(chunk) for chunk in chunks)
    assert decoder.proposal() is None
    decoder.finish()
    return decoder, reply


@pytest.mark.parametrize('ensure_ascii', [True, False])
def test_every_split_preserves_escaped_unicode_and_only_root_reply(ensure_ascii):
    reply = '中文😀 "quoted" \\ /\n\r\t\b\f\x00 <think>literal</think>'
    teaching = {'step': 'private teaching text', 'nested': [{'reply': 'hidden', 'token': 'hidden'}]}
    raw = json.dumps({'reply': reply, 'teaching': teaching, 'token': TOKEN}, ensure_ascii=ensure_ascii)
    for split in range(len(raw) + 1):
        decoder, output = decode_chunks([raw[:split], raw[split:]])
        assert output == reply
        assert decoder.reply_length == len(reply)
        assert decoder.reason is None
        assert decoder.proposal() == teaching
    decoder, output = decode_chunks(raw)
    assert output == reply
    assert decoder.proposal() == teaching


def test_reply_is_emitted_before_its_string_or_envelope_closes():
    decoder = JsonTeachingDecoder(TOKEN)
    assert decoder.feed('{"reply":"first') == 'first'
    assert decoder.feed('\\uD83D') == ''
    assert decoder.feed('\\uDE00 second\\') == '😀 second'
    assert decoder.feed('nthird') == '\nthird'
    assert decoder.reply_length == len('first😀 second\nthird')
    assert decoder.proposal() is None
    assert decoder.feed('","teaching":{"step":"hidden"},"token":"synthetic-token"}') == ''
    assert decoder.proposal() is None
    decoder.finish()
    assert decoder.reason is None
    assert decoder.proposal() == {'step': 'hidden'}


def test_all_root_key_orders_and_json_whitespace():
    values = {'reply': 'visible中文', 'teaching': {'arbitrary': [True, None, -2.5]}, 'token': TOKEN}
    for order in itertools.permutations(values):
        raw = ' \n { ' + ' ,\t '.join(json.dumps(key) + ' : ' + json.dumps(values[key], ensure_ascii=False)
                                       for key in order) + ' }\r\n'
        decoder, output = decode_chunks(raw)
        assert output == values['reply']
        assert decoder.reason is None
        assert decoder.proposal() == values['teaching']


def test_escaped_root_keys_and_nested_strings_do_not_leak():
    raw = '{"teaching":{"rep\\u006cy":"private \\\" } ]","items":[{}]},' \
          '"rep\\u006cy":"<think>shown</think>","token":"synthetic-token"}'
    decoder, output = decode_chunks(raw)
    assert output == '<think>shown</think>'
    assert decoder.reason is None
    assert decoder.proposal() == {'reply': 'private " } ]', 'items': [{}]}


@pytest.mark.parametrize('tail', [
    ',"reply":"second","teaching":{},"token":"synthetic-token"}',
    ',"rep\\u006cy":"second","teaching":{},"token":"synthetic-token"}',
    ',"teaching":{"step":1,"step":2},"token":"synthetic-token"}',
    ',"teaching":{"items":[{"x":1,"\\u0078":2}]},"token":"synthetic-token"}',
    ',"teaching":{},"teaching":{},"token":"synthetic-token"}',
    ',"teaching":{},"token":"synthetic-token","token":"synthetic-token"}',
    ',"teaching":{},"token":"synthetic-token","extra":"hidden"}',
])
def test_duplicates_and_extra_keys_reject_without_losing_prefix(tail):
    decoder, output = decode_chunks(['{"reply":"visible"', tail])
    assert output == 'visible'
    assert decoder.reason == 'envelope_invalid_schema'
    assert decoder.proposal() is None


@pytest.mark.parametrize('raw', [
    '{}', '[]', '"plaintext"',
    '{"reply":123,"teaching":{},"token":"synthetic-token"}',
    '{"reply":"","teaching":[],"token":"synthetic-token"}',
    '{"reply":"","teaching":{},"token":false}',
    '{"reply":"","teaching":{}}',
])
def test_wrong_root_structure_is_schema_failure(raw):
    decoder, output = decode_chunks(raw)
    assert output == ''
    assert decoder.reason == 'envelope_invalid_schema'
    assert decoder.proposal() is None


@pytest.mark.parametrize('teaching', [
    '{"n":NaN}', '{"n":Infinity}', '{"n":-Infinity}', '{"n":1e400}',
    '{"n":}', '{"n":01}', '{"x":true,}', '{[}',
    '{"x":"\\uD800"}', '{"\\uDC00":true}', '{"x":"raw\ncontrol"}',
])
def test_invalid_metadata_is_never_adopted(teaching):
    decoder, output = decode_chunks(['{"reply":"visible","teaching":', teaching,
                                    ',"token":"synthetic-token"}'])
    assert output == 'visible'
    assert decoder.reason == 'envelope_invalid_json'
    assert decoder.proposal() is None


@pytest.mark.parametrize('bad', [
    '\\q', '\\uXY00', '\\uDC00', '\\uD800x', '\\uD800\\u0041',
    '\\uD800\\n', '\n', '\x00', '\ud800', '\udc00',
])
def test_invalid_reply_escapes_preserve_only_valid_prefix(bad):
    decoder, output = decode_chunks(['{"reply":"visible', bad,
                                    '","teaching":{},"token":"synthetic-token"}'])
    assert output == 'visible'
    assert decoder.reply_length == len(output)
    assert decoder.reason == 'envelope_invalid_json'
    assert decoder.proposal() is None


@pytest.mark.parametrize('raw', [
    '', ' ', '{', '{"reply":"visible', '{"reply":"visible\\',
    '{"reply":"visible\\u12', '{"reply":"visible\\uD83D\\uDE',
    '{"reply":"visible",', '{"reply":"visible","teaching":{',
    '{"reply":"visible","teaching":{},"token":"synthetic-token"',
])
def test_truncation_never_adopts_metadata_but_keeps_emitted_prefix(raw):
    decoder, output = decode_chunks(raw)
    assert output in {'', 'visible'}
    assert decoder.reason == 'envelope_incomplete'
    assert decoder.proposal() is None


@pytest.mark.parametrize('raw, expected', [
    ('plain text reply', ''), ('```json\n' + envelope('visible') + '\n```', ''),
    (envelope('visible') + 'garbage', 'visible'),
    (envelope('visible') + envelope('second'), 'visible'),
    ('{"reply":"visible",}', 'visible'),
    ('{"reply":"visible" "teaching":{},"token":"synthetic-token"}', 'visible'),
])
def test_invalid_framing_has_no_plaintext_fallback(raw, expected):
    decoder, output = decode_chunks(raw)
    assert output == expected
    assert decoder.reason == 'envelope_invalid_json'
    assert decoder.proposal() is None


def test_token_mismatch_is_stable_and_still_preserves_reply():
    decoder, output = decode_chunks(['{"token":"wrong","teaching":{},"reply":"visible"}'])
    assert output == 'visible'
    assert decoder.reason == 'envelope_token_mismatch'
    assert decoder.proposal() is None
    assert decoder.feed(envelope('late')) == ''
    decoder.finish()
    assert decoder.reason == 'envelope_token_mismatch'


def test_empty_reply_and_sealed_success_are_valid():
    decoder, output = decode_chunks([envelope('', {'unvalidated': 'allowed'})])
    assert output == ''
    assert decoder.reply_length == 0
    assert decoder.reason is None
    assert decoder.proposal() == {'unvalidated': 'allowed'}
    assert decoder.feed('trailing input after finish') == ''
    decoder.finish()
    assert decoder.reason is None


def test_metadata_character_limit_ignores_unlimited_reply():
    raw = envelope('ignored', {'text': '中文' * 80})
    retained = len(envelope('', {'text': '中文' * 80}))
    valid, output = decode_chunks([raw], max_metadata=retained)
    assert output == 'ignored'
    assert valid.reason is None
    oversized, output = decode_chunks([raw], max_metadata=retained - 1)
    assert output == 'ignored'
    assert oversized.reason == 'envelope_oversized'
    assert oversized.proposal() is None
    assert oversized.feed('late') == ''

    decoder = JsonTeachingDecoder(TOKEN, max_metadata=80)
    assert decoder.feed('{"reply":"') == ''
    chunk = '中文😀' * 1000
    retained_state = (list(decoder._metadata), decoder._metadata_length,
                      list(decoder._key_parts), list(decoder._stack))
    for _ in range(400):
        assert decoder.feed(chunk) == chunk
    assert decoder.reply_length == len(chunk) * 400
    assert (decoder._metadata, decoder._metadata_length, decoder._key_parts, decoder._stack) == retained_state
    assert decoder.feed('","teaching":{},"token":"synthetic-token"}') == ''
    decoder.finish()
    assert decoder.reason is None
    assert decoder.proposal() == {}


def test_oversized_non_reply_fields_never_leak():
    for raw in ['{"teaching":{"private":"' + 'x' * 1000,
                '{"token":"' + 'secret' * 1000,
                '{"' + 'unknown' * 1000]:
        decoder, output = decode_chunks(raw, max_metadata=80)
        assert output == ''
        assert decoder.reason == 'envelope_oversized'
        assert decoder._metadata_length <= 80
        assert decoder._metadata == []
        assert decoder.proposal() is None
