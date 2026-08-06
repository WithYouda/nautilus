#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d /tmp/nautilus-e2e-safety.XXXXXX)"
trap 'rm -rf -- "$TEST_ROOT"' EXIT INT TERM

assert_rejected_without_deleting() {
  local candidate="$1"
  local protected_path="$2"
  local marker="$protected_path/keep.marker"

  mkdir -p -- "$protected_path"
  : >"$marker"
  if NAUTILUS_E2E_DATA_DIR="$candidate" bash "$ROOT_DIR/scripts/start-e2e.sh" \
    >"$TEST_ROOT/start-e2e.out" 2>&1; then
    printf '%s\n' "危险数据目录未被拒绝：$candidate" >&2
    exit 1
  fi
  if [[ ! -f "$marker" ]]; then
    printf '%s\n' "拒绝危险路径时删除了受保护目标：$protected_path" >&2
    exit 1
  fi
}

traversal_target="$TEST_ROOT/traversal-target"
assert_rejected_without_deleting \
  "/tmp/nautilus-playwright.audit/../../${traversal_target#/}" \
  "$traversal_target"

existing_dir="/tmp/nautilus-playwright.existing-$$"
assert_rejected_without_deleting "$existing_dir" "$existing_dir"
rm -rf -- "$existing_dir"

symlink_target="$TEST_ROOT/symlink-target"
symlink_path="/tmp/nautilus-playwright.symlink-$$"
mkdir -p -- "$symlink_target"
: >"$symlink_target/keep.marker"
ln -s -- "$symlink_target" "$symlink_path"
if NAUTILUS_E2E_DATA_DIR="$symlink_path" bash "$ROOT_DIR/scripts/start-e2e.sh" \
  >"$TEST_ROOT/start-e2e.out" 2>&1; then
  printf '%s\n' "符号链接数据目录未被拒绝。" >&2
  exit 1
fi
if [[ ! -L "$symlink_path" ]] || [[ ! -f "$symlink_target/keep.marker" ]]; then
  printf '%s\n' "拒绝符号链接时修改或删除了目标。" >&2
  exit 1
fi
rm -- "$symlink_path"

printf '%s\n' "start-e2e 数据目录安全检查通过。"
