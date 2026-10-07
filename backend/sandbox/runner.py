"""Container-only supervisor: user code runs in a separate process, no host mounts."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

PRELUDE = '''import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
_figures = Path('/work/figures')
_figures.mkdir(exist_ok=True)
def _show(*args, **kwargs):
    for number in plt.get_fignums():
        plt.figure(number).savefig(_figures / ('figure-' + str(len(list(_figures.glob('*.png')))) + '.png'))
    plt.close('all')
plt.show = _show
try:
    exec(compile(Path('/work/main.py').read_text(), '<学习代码>', 'exec'), {'__name__': '__main__', '__file__': '/work/main.py'})
finally:
    _show()
'''

payload = json.load(sys.stdin)
Path('/work/main.py').write_text(payload['code'])
Path('/work/launch.py').write_text(PRELUDE)
Path('/work/input.txt').write_text(payload.get('stdin', ''))
with open('/work/input.txt','rb') as data, open('/work/stdout','wb') as out, open('/work/stderr','wb') as err:
    result = subprocess.run([sys.executable,'-I','/work/launch.py'], stdin=data, stdout=out, stderr=err)
# Symlinks and arbitrary files are never followed out to the host (there are no
# host mounts), and only generated PNG files are returned as viewable artifacts.
figures = []
for path in sorted(Path('/work/figures').glob('*.png')):
    if path.is_file() and not path.is_symlink():
        raw = path.read_bytes()
        if raw.startswith(b'\x89PNG\r\n\x1a\n'):
            figures.append(base64.b64encode(raw).decode('ascii'))
print(json.dumps({'exit_code': result.returncode,
    'stdout': Path('/work/stdout').read_text(errors='replace'),
    'stderr': Path('/work/stderr').read_text(errors='replace'), 'figures': figures}))
