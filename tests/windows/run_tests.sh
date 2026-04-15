#!/usr/bin/env bash
# run_tests.sh — Bring up the Windows VM, run the test suite, tear down.
#
# Environment variables:
#   KEEP_VM=1   — skip vagrant destroy on exit (useful for debugging)

set -euo pipefail
cd "$(dirname "$0")"

echo "==> Bringing up Windows VM (libvirt) ..."
vagrant up --provider=libvirt

echo "==> Running pytest inside VM ..."
vagrant winrm --shell=powershell --command \
  "cd C:\chatplays; python -m pytest tests/windows/test_windows_controller.py -v"
EXIT_CODE=$?

if [[ "${KEEP_VM:-0}" != "1" ]]; then
    echo "==> Destroying VM ..."
    vagrant destroy -f
else
    echo "==> KEEP_VM=1 — VM left running. Use 'vagrant destroy -f' to clean up."
fi

exit $EXIT_CODE
