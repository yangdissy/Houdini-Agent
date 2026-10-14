# Real Houdini integration tests

These tests launch a separate `hython` process with temporary Houdini preferences,
home, application data, HIP, JOB, package, log, and artifact directories. They do
not run during the default pytest suite.

## Run

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m pytest `
  tests/integration/test_houdini_isolated.py `
  -m houdini_integration `
  --run-houdini-integration `
  --hython "C:/Program Files/Side Effects Software/Houdini 21.0.596/bin/hython.exe" `
  -q
```

The executable is resolved in this order:

1. `--hython`
2. `HOUDINI_TEST_HYTHON`
3. `HFS/bin/hython.exe`

The runner does not scan installed Houdini versions or silently choose one.

## Isolation boundary

The runner constructs a minimal environment and does not inherit production
Houdini search paths, API keys, or proxy settings. It starts a new process group
and terminates the whole process tree on timeout. Successful runs are removed;
failed and timed-out runs retain their manifest, stdout, stderr, HIP, and other
artifacts at the path printed by pytest.

Process isolation is not a security sandbox. The child process still has the
permissions of the current Windows user. Only repository-owned scenarios may be
passed to the runner.

`hython` validates real HOM, tool dispatch, Undo, update mode, HIP persistence,
and package/HDA loading. It does not validate the Houdini GUI, Qt event loop,
`BlockingQueuedConnection`, AITab, or panel lifecycle.