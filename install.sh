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
Usage: ./install.sh [--check] [--language fr|en]

Without arguments, install the pyDuckHunt beta into the project-local .venv.
--check validates prerequisites and filesystem boundaries without changing them.
--language chooses the message language for a new configuration (default: fr).
An existing configuration is preserved; a conflicting language choice is refused.
EOF
}

mode='install'
language='fr'
language_explicit='false'
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) mode='check'; shift ;;
    --language)
      [[ $# -ge 2 ]] || fail '--language requires fr or en'
      [[ "$language_explicit" == false ]] || fail '--language may only be supplied once'
      language="$2"; language_explicit='true'; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "unsupported argument: $1" ;;
  esac
done
[[ "$language" == fr || "$language" == en ]] || fail 'language must be fr or en'

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

# Resolve the requested language before any installation side effect.
"$python_command" - "$configuration" "$language" "$language_explicit" <<'PYLANG'
import sys
import tomllib
from pathlib import Path
path, requested, explicit = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == 'true'
try:
    existing = tomllib.loads(path.read_text(encoding='utf-8')).get('game', {}).get('language', 'fr') if path.exists() else requested
except (OSError, ValueError):
    raise SystemExit('[KO] Existing configuration cannot be read safely.')
if existing not in ('fr', 'en'):
    raise SystemExit('[KO] Existing game.language must be fr or en.')
if path.exists() and explicit and requested != existing:
    raise SystemExit('[KO] Existing language differs; update game.language explicitly in your private configuration first.')
print('LANGUAGE=' + existing)
PYLANG

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
  "$python_command" - "$sample" "$configuration" "$language" <<'PYLANG'
import os
import sys
from pathlib import Path
sample, target, language = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
text = sample.read_text(encoding='utf-8')
if language == 'en':
    text = text.replace('language = "fr"', 'language = "en"', 1)
    text = text.replace('spontaneous_launch_announcement = "allez, je lance un canard"',
                        'spontaneous_launch_announcement = "all right, here comes a duck"', 1)
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as handle:
    handle.write(text)
PYLANG
  configuration_state='created-disabled'
else
  configuration_state='preserved'
fi

"$environment/bin/pyduckhunt" --version
printf 'CONFIGURATION=%s state=%s\n' "$configuration" "$configuration_state"
printf '[OK] pyDuckHunt beta installed locally.\n'
printf '[INFO] No IRC connection, service installation or process start was performed.\n'
printf '[INFO] Next: docs/INSTALL.md#configure-and-start. Review the target, then set game.enabled=true before pilot-check.\n'
printf '[INFO] pilot-check opens no connection; launching the bot is a separate step.\n'
