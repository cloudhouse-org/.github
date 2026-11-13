#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo 'Run this setup as root on dyw-003.' >&2
  exit 1
fi

readonly group='cloudhouse-review'
readonly config_dir='/etc/cloudhouse-review'
readonly token_file="$config_dir/ocr-token"

if ! getent group "$group" >/dev/null; then
  echo 'Required cloudhouse-review group does not exist.' >&2
  exit 1
fi
if ! id -nG cloudhouse-review | tr ' ' '\n' | grep -Fxq "$group"; then
  echo 'The cloudhouse-review runner account is not a member of the required group.' >&2
  exit 1
fi
if [[ -L "$config_dir" || -L "$token_file" || -e "$token_file" ]]; then
  echo 'Refusing to replace an existing token path.' >&2
  exit 1
fi

install -d -o root -g "$group" -m 0750 "$config_dir"
printf 'OCR model token (hidden): ' >/dev/tty
if ! IFS= read -r -s token </dev/tty; then
  printf '\n' >/dev/tty
  echo 'Could not read token from terminal.' >&2
  exit 1
fi
printf '\n' >/dev/tty
if [[ -z "$token" || "$token" =~ [[:space:]] ]]; then
  unset token
  echo 'Token must be non-empty and contain no whitespace.' >&2
  exit 1
fi

umask 077
tmp_file="$(mktemp "$config_dir/.ocr-token.XXXXXX")"
cleanup() {
  rm -f -- "$tmp_file"
  unset token 2>/dev/null || true
}
trap cleanup EXIT
printf '%s\n' "$token" >"$tmp_file"
unset token
chown "root:$group" "$tmp_file"
chmod 0640 "$tmp_file"
if ! ln -- "$tmp_file" "$token_file"; then
  echo 'Token path already exists; no file was replaced.' >&2
  exit 1
fi
rm -f -- "$tmp_file"
trap - EXIT
printf 'Installed local OCR token with root:%s ownership and mode 0640.\n' "$group"
