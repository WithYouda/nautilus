"""Capacity checks for complete content, independent of business text length.

The reserve is for concurrent requests and JSON/string copies. It is derived
from currently available host/container memory, never a fixed document quota.
"""
from pathlib import Path
import os


def available_memory():
    available = None
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                available = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError):
        pass
    try:
        maximum = Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if maximum != 'max':
            remaining = max(0, int(maximum) - int(Path('/sys/fs/cgroup/memory.current').read_text()))
            available = min(available, remaining) if available is not None else remaining
    except (OSError, ValueError):
        pass
    if available is None:
        try:
            available = os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        except (OSError, ValueError, AttributeError):
            pass
    return available


def ensure_capacity(byte_count):
    """Reject before an allocation threatens remaining memory; never truncate."""
    available = available_memory()
    if available is not None and byte_count * 8 > available:
        from .providers import ProviderError
        raise ProviderError('本机当前可用内存不足以完整处理这些内容，请关闭其他任务或缩小本次范围后重试。原始内容没有截断。', kind='resource_limit')
