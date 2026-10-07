#!/usr/bin/env python3
"""Build a dedicated image from installed CPython and pinned public wheels.

Linux/CPython 3.12 only. No home directory, project data, settings or credentials
are copied. Docker needs no registry access; PyPI is only used at build time.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile

PROJECT=Path(__file__).resolve().parents[1]
REQUIREMENTS=['numpy==2.2.6','pandas==2.2.3','matplotlib==3.10.1']

def main():
    if sys.platform!='linux' or sys.version_info[:2]!=(3,12):
        raise SystemExit('Use Linux CPython 3.12 to build this image.')
    executable=Path(sys._base_executable).resolve()
    stdlib=Path(sysconfig.get_path('stdlib')).resolve()
    with tempfile.TemporaryDirectory(prefix='nautilus-python-build-') as directory:
        context=Path(directory);root=context/'root';root.mkdir()
        def copy(source):
            source=Path(source)
            dest=root/str(source).lstrip('/')
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,dest,follow_symlinks=True)
        copy(executable)
        shutil.copytree(stdlib,root/str(stdlib).lstrip('/'),ignore=shutil.ignore_patterns('__pycache__','site-packages','dist-packages','test','tests','ensurepip'))
        modules=[executable,*stdlib.rglob('*.so')]
        libraries=set()
        for module in modules:
            if 'site-packages' in module.parts or 'dist-packages' in module.parts:continue
            output=subprocess.run(['ldd',str(module)],capture_output=True,text=True,check=False).stdout
            libraries.update(re.findall(r'(/[^\s()]+)',output))
        for library in sorted(libraries):copy(library)
        target=root/'usr/local/lib/python3.12/dist-packages'
        subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:',
            '--target',str(target),*REQUIREMENTS],check=True)
        # Scientific wheels also depend on system C/C++ runtime libraries.
        for module in target.rglob('*.so*'):
            output=subprocess.run(['ldd',str(module)],capture_output=True,text=True,check=False).stdout
            for library in re.findall(r'(/[^\s()]+)',output):
                if not Path(library).is_relative_to(root):copy(library)
        shutil.copy2(PROJECT/'backend/sandbox/runner.py',context/'runner.py')
        # Set a known site-package directory explicitly; no build-host env paths.
        dockerfile=(PROJECT/'backend/sandbox/Dockerfile').read_text().replace('@@PYTHON@@',str(executable))
        (context/'Dockerfile').write_text(dockerfile)
        subprocess.run(['docker','build','--network=none','-t','nautilus-python:1',str(context)],check=True)

if __name__=='__main__':main()
