#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export LC_ALL=C

readonly project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly environment="$project_root/.venv"
readonly sample="$project_root/config/pyduckhunt.example.toml"
readonly configuration="$project_root/config/pyduckhunt.toml"
readonly python_command="${PYDUCKHUNT_PYTHON:-python3}"

fail() {
  printf '[KO] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: ./install.sh [--check]

Without arguments, install the pyDuckHunt beta into the project-local .venv.
--check validates prerequisites and filesystem boundaries without changing them.
EOF
}

mode='install'
case "${1:-}" in
  '') ;;
  --check) mode='check' ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; fail "unsupported argument: $1" ;;
esac
[[ $# -le 1 ]] || fail 'only one argument is accepted'

command -v "$python_command" >/dev/null || fail "Python command not found: $python_command"
command -v install >/dev/null || fail 'install command not found'
[[ -f "$project_root/pyproject.toml" ]] || fail 'pyproject.toml is absent'
[[ -f "$sample" && ! -L "$sample" ]] || fail 'disabled configuration example is unsafe or absent'

"$python_command" - <<'PY'
import sys
import venv

if sys.version_info < (3, 11):
    raise SystemExit("[KO] pyDuckHunt requires Python 3.11 or newer")
print(f"PYTHON={sys.version.split()[0]}")
PY

if [[ -e "$environment" ]]; then
  [[ -d "$environment" && ! -L "$environment" ]] \
    || fail '.venv must be a real directory'
fi
if [[ -e "$configuration" ]]; then
  [[ -f "$configuration" && ! -L "$configuration" ]] \
    || fail 'existing configuration must be one regular file'
fi

if [[ "$mode" == check ]]; then
  printf 'ENVIRONMENT=%s\n' "$([[ -d "$environment" ]] && printf present || printf absent)"
  printf 'CONFIGURATION=%s\n' "$([[ -f "$configuration" ]] && printf preserved || printf absent)"
  printf '[OK] Installation prerequisites and boundaries are valid; nothing was changed.\n'
  exit 0
fi

[[ "$(id -u)" -ne 0 ]] || fail 'run the installer as the unprivileged bot account, not root'

if [[ ! -d "$environment" ]]; then
  "$python_command" -m venv "$environment"
  printf '[INFO] Created project virtual environment: %s\n' "$environment"
else
  [[ -x "$environment/bin/python" ]] || fail 'existing .venv has no executable Python'
  printf '[INFO] Reusing project virtual environment: %s\n' "$environment"
fi

"$environment/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-deps \
  --editable "$project_root"

if [[ ! -e "$configuration" ]]; then
  install -m 0600 -- "$sample" "$configuration"
  configuration_state='created-disabled'
else
  configuration_state='preserved'
fi

"$environment/bin/pyduckhunt" --version
printf 'CONFIGURATION=%s state=%s\n' "$configuration" "$configuration_state"
printf '[OK] pyDuckHunt beta installed locally.\n'
printf '[INFO] No IRC connection, service installation or process start was performed.\n'
printf '[INFO] Review docs/INSTALL.md and keep game.enabled=false until pilot-check succeeds.\n'
