# Python execution plugin

The first E4 capability is manually run from a completed Python code block in a
learning conversation or question discussion. It is disabled initially. Enable
it in Settings → 扩展能力, or use the explicit 启用并运行 action. The model has
no Python tool or automatic execution grant.

## Build on the Linux service host

```sh
.venv/bin/python scripts/build-python-sandbox.py
```

Requires Docker and the service host's CPython 3.12. The script copies only the
interpreter, standard library, required shared libraries and pinned NumPy 2.2.6,
pandas 2.2.3 and Matplotlib 3.10.1 wheels into a scratch image. It never copies
home directories, the project, app configuration or credentials. No Docker
registry is required; downloading wheels needs PyPI at build time. The
Dockerfile is a template for this script, not a standalone build context.
The completed image is `nautilus-python:1`; accepted runs freeze its immutable
image ID. Rebuild after updating the host interpreter or dependencies.

At runtime there are no network connections, host mounts or Docker sockets in
the container. It runs as UID/GID 65534, with a read-only root, no capabilities,
no-new-privileges, Docker's default seccomp profile, 1 CPU, 64 PIDs, no extra
swap and a 64 MiB temporary workspace. The memory budget defaults to 512 MiB
(selectable 128/256/512/1024); wall timeout defaults to 30 seconds (1–300).
These are execution resource budgets, not text truncation thresholds. Each
run starts fresh. The application also checks host memory while collecting
output and validates PNGs before returning them. Do not expose this prototype
as a public multi-tenant execution service; containers share the host kernel.

## Records and boundaries

Code, stdin, stdout/stderr, PNGs, status and environment are stored under
`python_runs` in the original reply's existing run snapshot, separate from the
model's parameters, teaching state, help and formal evidence. No new database
schema or parallel learning-history system is introduced. Only completed,
owned, unpurged replies may run. Inherited replies retain their original source
and do not offer execution in this first slice. Editing a snippet does not edit
the original reply. Results are not automatically sent to a model or adopted
as evidence. The user can copy code and results into a later message.

Source clearing removes these adjunct records through existing snapshot erasure
and managed-backup machinery. A source check during and before publication
prevents late resurrection. Disabling cancels active work. Closing the dialog
continues the accepted run; stopping the server cancels it. On restart only
containers labeled for this database are removed and pending records become
interrupted. Unrelated Docker containers are never stopped. There is no
automatic package installation, arbitrary executable plugin import, or formal
code-grading policy in this slice.

## Checks

```sh
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/test_python_execution.py
```

Real-container tests skip if the optional image is not built. The browser
journey is `frontend/e2e/python-execution.spec.ts`; use the repository's isolated
Playwright environment, never the trial database.
