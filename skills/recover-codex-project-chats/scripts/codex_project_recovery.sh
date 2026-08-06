#!/bin/zsh
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"

codex_dir="${CODEX_HOME:-$HOME/.codex}"
db_file="$codex_dir/state_5.sqlite"
catalog_db="$codex_dir/sqlite/codex-dev.db"
state_file="$codex_dir/.codex-global-state.json"
config_file="$codex_dir/config.toml"
command_name="${1:-diagnose}"
csv_path="${2:-}"
script_name="${0:t}"

usage() {
  print -- "Usage: $script_name diagnose [csv-path]"
  print -- "       $script_name repair-provider <source-provider> <target-provider>"
  print -- "       $script_name verify"
}

die() {
  print -u2 -- "ERROR: $*"
  exit 1
}

app_running() {
  pgrep -f '/Applications/(ChatGPT|Codex)\.app/Contents/(MacOS/(ChatGPT|Codex)|Resources/codex.*app-server|Frameworks/.*Codex)' >/dev/null 2>&1
}

validate_provider() {
  [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid provider name: $1"
}

require_tools() {
  local tool
  for tool in sqlite3 jq rg rsync perl; do
    command -v "$tool" >/dev/null 2>&1 || die "missing tool: $tool"
  done
}

require_files() {
  [[ -f "$db_file" ]] || die "missing database: $db_file"
  [[ -f "$state_file" ]] || die "missing global state: $state_file"
  [[ -f "$config_file" ]] || die "missing config: $config_file"
}

current_provider() {
  sed -n 's/^[[:space:]]*model_provider[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$config_file" | head -1
}

diagnose() {
  require_files
  print -- "codex_home=$codex_dir"
  if app_running; then print -- "desktop_running=yes"; else print -- "desktop_running=no"; fi
  print -- "current_provider=$(current_provider)"
  print -- "integrity=$(sqlite3 "$db_file" 'PRAGMA integrity_check;')"
  print -- "threads_total=$(sqlite3 "$db_file" 'SELECT COUNT(*) FROM threads;')"
  print -- "rollouts_sessions=$(find "$codex_dir/sessions" -type f -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')"
  print -- "rollouts_archived=$(find "$codex_dir/archived_sessions" -type f -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')"
  print -- "missing_rollouts=$(sqlite3 -separator $'\t' "$db_file" 'SELECT id,rollout_path FROM threads;' | while IFS=$'\t' read -r id path; do [[ -f "$path" ]] || print -- "$id"; done | wc -l | tr -d ' ')"
  print -- "\n[providers]"
  sqlite3 -header -column "$db_file" "SELECT model_provider,COUNT(*) total,SUM(archived=0) active,SUM(archived=0 AND preview<>'') visible FROM threads GROUP BY model_provider ORDER BY total DESC;"
  print -- "\n[cwd_counts]"
  sqlite3 -header -column "$db_file" "SELECT cwd,COUNT(*) total,SUM(archived=0) active,SUM(archived=0 AND preview<>'') visible FROM threads GROUP BY cwd ORDER BY total DESC;"
  print -- "\n[projects]"
  jq -r '."local-projects" // {} | to_entries[] | [.key,.value.name,(.value.rootPaths|join(";"))] | @tsv' "$state_file"
  print -- "\n[assignment_counts]"
  jq -r '."thread-project-assignments" // {} | to_entries[] | [.value.projectId,.value.cwd] | @tsv' "$state_file" | sort | uniq -c
  if [[ -n "$csv_path" ]]; then
    [[ -f "$csv_path" ]] || die "CSV not found: $csv_path"
    print -- "\n[csv]"
    print -- "path=$csv_path"
    print -- "header=$(sed -n '1p' "$csv_path")"
    print -- "physical_lines=$(wc -l < "$csv_path" | tr -d ' ')"
  fi
}

repair_provider() {
  require_tools
  require_files
  app_running && die "Codex Desktop is running. Quit it completely before repair."
  local source_provider="${2:-}"
  local target_provider="${3:-}"
  [[ -n "$source_provider" ]] || die "source provider is required"
  [[ -n "$target_provider" ]] || die "target provider is required"
  [[ "$source_provider" != "$target_provider" ]] || die "source and target providers are identical"
  validate_provider "$source_provider"
  validate_provider "$target_provider"
  local integrity
  integrity=$(sqlite3 "$db_file" 'PRAGMA integrity_check;')
  [[ "$integrity" == "ok" ]] || die "database integrity check failed: $integrity"

  local stamp backup_dir paths_file changed remaining_db remaining_jsonl
  stamp=$(date +%Y%m%d_%H%M%S)
  backup_dir="${CODEX_RECOVERY_BACKUP_DIR:-$HOME/Documents/Codex/codex-recovery-backups}/pre-provider-repair-$stamp"
  mkdir -p "$backup_dir"
  sqlite3 "$db_file" 'PRAGMA wal_checkpoint(TRUNCATE);'
  cp -p "$db_file" "$backup_dir/state_5.sqlite"
  [[ -f "$catalog_db" ]] && cp -p "$catalog_db" "$backup_dir/codex-dev.db"
  cp -p "$state_file" "$backup_dir/codex-global-state.json"
  cp -p "$config_file" "$backup_dir/config.toml"
  rsync -a "$codex_dir/sessions/" "$backup_dir/sessions/"
  rsync -a "$codex_dir/archived_sessions/" "$backup_dir/archived_sessions/"

  paths_file="$backup_dir/rollout-paths-before-repair.txt"
  sqlite3 "$db_file" "SELECT rollout_path FROM threads WHERE model_provider = '$source_provider';" > "$paths_file"
  sqlite3 "$db_file" "BEGIN IMMEDIATE; UPDATE threads SET model_provider='$target_provider' WHERE model_provider='$source_provider'; COMMIT;"
  if [[ -f "$catalog_db" ]] && sqlite3 "$catalog_db" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_thread_catalog';" | rg -q '^1$'; then
    sqlite3 "$catalog_db" "BEGIN IMMEDIATE; UPDATE local_thread_catalog SET model_provider='$target_provider' WHERE model_provider='$source_provider'; COMMIT;"
  fi

  changed=0
  while IFS= read -r rollout_path; do
    [[ -f "$rollout_path" ]] || continue
    if rg -q '\"model_provider\":\"[^\"]+\"' "$rollout_path"; then
      TARGET_PROVIDER="$target_provider" perl -pi -e 's/\"model_provider\":\"[^\"]+\"/\"model_provider\":\"$ENV{TARGET_PROVIDER}\"/g' "$rollout_path"
      changed=$((changed + 1))
    fi
  done < "$paths_file"

  remaining_db=$(sqlite3 "$db_file" "SELECT COUNT(*) FROM threads WHERE model_provider='$source_provider';")
  remaining_jsonl=$( (rg -l '\"model_provider\":\"'"$source_provider"'\"' "$codex_dir/sessions" "$codex_dir/archived_sessions" -g '*.jsonl' 2>/dev/null || true) | wc -l | tr -d ' ')
  [[ "$remaining_db" == "0" ]] || die "source-provider rows remain in database: $remaining_db"
  [[ "$remaining_jsonl" == "0" ]] || die "source-provider metadata remains in rollout files: $remaining_jsonl"
  [[ "$(sqlite3 "$db_file" 'PRAGMA integrity_check;')" == "ok" ]] || die "post-repair integrity check failed"
  print -- "repair=complete"
  print -- "source_provider=$source_provider"
  print -- "target_provider=$target_provider"
  print -- "jsonl_changed=$changed"
  print -- "backup=$backup_dir"
}

verify() {
  require_files
  app_running && die "Quit Codex Desktop before offline verification."
  print -- "integrity=$(sqlite3 "$db_file" 'PRAGMA integrity_check;')"
  print -- "current_provider=$(current_provider)"
  print -- "provider_rows=$(sqlite3 "$db_file" "SELECT COUNT(*) FROM threads WHERE model_provider='$(current_provider)';")"
  print -- "other_provider_rows=$(sqlite3 "$db_file" "SELECT COUNT(*) FROM threads WHERE model_provider<>'$(current_provider)';")"
  print -- "missing_rollouts=$(sqlite3 -separator $'\t' "$db_file" 'SELECT id,rollout_path FROM threads;' | while IFS=$'\t' read -r id path; do [[ -f "$path" ]] || print -- "$id"; done | wc -l | tr -d ' ')"
  print -- "assignments=$(jq '.["thread-project-assignments"] // {} | length' "$state_file")"
  sqlite3 -header -column "$db_file" "SELECT cwd,COUNT(*) total,SUM(archived=0 AND preview<>'') visible FROM threads GROUP BY cwd ORDER BY total DESC;"
}

case "$command_name" in
  -h|--help|help) usage ;;
  diagnose) diagnose ;;
  repair-provider) repair_provider "$@" ;;
  verify) verify ;;
  *) usage; die "unknown command: $command_name" ;;
esac
