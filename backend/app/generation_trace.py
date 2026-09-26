"""Ordered, timed presentation of actual model/tool events (never synthetic reasoning)."""
from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timezone

from .providers import ProviderError


def stamp():
    return datetime.now(timezone.utc).isoformat()


def interrupt_trace(value, status='interrupted'):
    """Seal a saved trace without counting server downtime as model thinking."""
    trace = copy.deepcopy(value)
    if not trace or trace.get('status') != 'running':
        return trace
    trace['status'] = status
    trace['finished_at'] = trace.get('updated_at', trace.get('started_at'))
    for part in trace.get('parts', []):
        if part.get('status') == 'running':
            part['status'] = status
            part['finished_at'] = trace['finished_at']
    return trace


class GenerationRecorder:
    def __init__(self, publish, *, clock=time.monotonic):
        self.publish = publish
        self.clock = clock
        self.started = clock()
        self.last_publish = -float('inf')
        self.trace = {'version': 1, 'status': 'running', 'started_at': stamp(), 'elapsed_ms': 0, 'parts': []}
        self.active = None
        self.beginnings = {}
        self.native = None

    def _new(self, kind, **fields):
        if len(self.trace['parts']) >= 1024:
            raise ProviderError('回复过程片段超过限制', kind='output_limit')
        part = {'id': f"part-{len(self.trace['parts']) + 1}", 'type': kind, 'status': 'running',
                'started_at': stamp(), 'duration_ms': 0, **fields}
        self.beginnings[part['id']] = self.clock()
        self.trace['parts'].append(part)
        return part

    def _close(self, part, status='succeeded'):
        if part and part['status'] == 'running':
            part.update(status=status, finished_at=stamp(), duration_ms=max(0, round((self.clock() - self.beginnings[part['id']]) * 1000)))

    def boundary(self):
        self._close(self.active)
        self.active = None
        self.flush(force=True)

    def observe(self, chunk):
        if chunk.kind in {'content', 'reasoning'}:
            if not chunk.text:
                return
            kind = 'text' if chunk.kind == 'content' else 'reasoning'
            new = self.active is None or self.active['type'] != kind
            if new:
                self._close(self.active)
                self.active = self._new(kind, text='')
            self.active['text'] += chunk.text
            self.flush(force=new)
        elif chunk.kind == 'turn_end':
            self.boundary()
        elif chunk.kind == 'tool_start':
            self._close(self.active)
            self.active = None
            info = json.loads(chunk.text)
            self._new('tool', **info)
            self.flush(force=True)
        elif chunk.kind == 'tool_end':
            info = json.loads(chunk.text)
            part = next((part for part in reversed(self.trace['parts']) if part.get('call_id') == info['call_id']), None)
            if part:
                self._close(part, info.get('status', 'succeeded'))
                part.update({key: value for key, value in info.items() if key not in {'status', 'duration_ms'}})
                self.flush(force=True)

    def native_event(self, trace, kind):
        status = trace.get('status')
        if status in {'off', 'queued', 'not_used'}:
            return
        if self.native is None:
            self._close(self.active)
            self.active = None
            self.native = self._new('tool', name='native_search', service_name=trace.get('service_name'))
        self.native['result'] = copy.deepcopy(trace)
        if status in {'succeeded', 'failed'}:
            self._close(self.native, status)
        self.flush(force=True)

    def flush(self, *, force=False):
        tick = self.clock()
        self.trace['elapsed_ms'] = max(0, round((tick - self.started) * 1000))
        self.trace['updated_at'] = stamp()
        for part in self.trace['parts']:
            if part['status'] == 'running':
                part['duration_ms'] = max(0, round((tick - self.beginnings[part['id']]) * 1000))
        if force or tick - self.last_publish >= .2:
            self.last_publish = tick
            self.publish(copy.deepcopy(self.trace))

    def finish(self, status):
        if self.trace['status'] != 'running':
            return
        for part in self.trace['parts']:
            self._close(part, status)
        self.trace.update(status=status, finished_at=stamp())
        self.flush(force=True)
