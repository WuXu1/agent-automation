# shellcheck shell=bash
# Stage: shared long-term memory (the "second brain"). Mem0's own server on this machine with Postgres + pgvector. Facts are
# extracted by DeepSeek (the same key, a fraction of a penny each) and searched with a small embedding model that runs here,
# so searching never sends your notes anywhere.

MEM0_SRC=/data/tools/mem0-src
MEM0_VENV=/data/tools/mem0-venv
MEM0_STATE=$HH/mem0-server
MEM0_ENV=$MEM0_STATE/server.env

stage_memory() {
  step "Shared memory (Mem0, on this server)"
  cat > /etc/postgresql/16/main/conf.d/crew-small.conf <<'CONF'
# small footprint for the 4 GB server (memory holds a few thousand short facts)
shared_buffers = 64MB
max_connections = 30
work_mem = 4MB
maintenance_work_mem = 32MB
effective_cache_size = 256MB
listen_addresses = 'localhost'
CONF
  chmod 644 /etc/postgresql/16/main/conf.d/crew-small.conf
  systemctl enable --quiet postgresql
  systemctl restart postgresql@16-main

  install -d -o hermes -g hermes -m 700 "$MEM0_STATE" /data/tools/mem0-cache
  if [ ! -s "$MEM0_ENV" ]; then
    local tmp; tmp="$(mktemp)"; chmod 600 "$tmp"
    {
      echo "POSTGRES_HOST=127.0.0.1"; echo "POSTGRES_PORT=5432"; echo "POSTGRES_DB=mem0"; echo "APP_DB_NAME=mem0_app"
      echo "POSTGRES_USER=mem0"; echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"; echo "POSTGRES_COLLECTION_NAME=memories"
      echo "ADMIN_API_KEY=$(openssl rand -hex 32)"; echo "JWT_SECRET=$(openssl rand -hex 32)"
      echo "OPENAI_API_KEY=$(env_get "$(env_of chief)" DEEPSEEK_API_KEY)"; echo "OPENAI_BASE_URL=https://api.deepseek.com/v1"
      echo "MEM0_DEFAULT_LLM_MODEL=deepseek-flash"; echo "MEM0_TELEMETRY=false"; echo "HISTORY_DB_PATH=$MEM0_STATE/history.db"
    } > "$tmp"
    install -o hermes -g hermes -m 600 "$tmp" "$MEM0_ENV"; rm -f "$tmp"
  else   # keep the DeepSeek key in step with the agents' (it may have been changed with crew-key)
    env_get "$(env_of chief)" DEEPSEEK_API_KEY | env_set "$MEM0_ENV" OPENAI_API_KEY
  fi
  local dbpw; dbpw="$(env_get "$MEM0_ENV" POSTGRES_PASSWORD)"
  sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL >/dev/null
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mem0') THEN CREATE ROLE mem0 LOGIN; END IF;
END \$\$;
ALTER ROLE mem0 PASSWORD '$dbpw';
SQL
  local db
  for db in mem0 mem0_app; do
    sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 || sudo -u postgres createdb -O mem0 "$db"
  done
  sudo -u postgres psql -d mem0 -q -c "CREATE EXTENSION IF NOT EXISTS vector"

  [ -d "$MEM0_SRC/.git" ] || as_hermes git -c advice.detachedHead=false clone -q --depth 1 --branch "$MEM0_TAG" https://github.com/mem0ai/mem0.git "$MEM0_SRC"
  if ! grep -q fastembed "$MEM0_SRC/server/main.py"; then as_hermes git -C "$MEM0_SRC" apply "$KIT/vm/mem0/mem0-server-fastembed.patch"; fi
  [ -x "$MEM0_VENV/bin/python" ] || as_hermes python3 -m venv "$MEM0_VENV"
  say "  Installing the memory server (a few minutes)…"
  as_hermes "$MEM0_VENV/bin/pip" install -q --no-cache-dir "$MEM0_SRC" -r "$MEM0_SRC/server/requirements.txt" fastembed >/dev/null
  install -o root -g root -m 644 "$KIT/vm/mem0/mem0-server.service" /etc/systemd/system/mem0-server.service
  systemctl daemon-reload
  systemctl enable --quiet mem0-server
  systemctl restart mem0-server
  local i
  for i in $(seq 1 90); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:8888/docs)" = 200 ] && break; sleep 2
  done
  [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:8888/docs)" = 200 ] || { journalctl -u mem0-server -n 30 --no-pager; die "the memory server didn't start (log above)"; }
  ok "Memory server running (127.0.0.1:8888, this machine only)"

  # What is worth remembering: lasting facts only, never keys or phone numbers (Mem0's 'custom_instructions').
  local rule key
  rule="$(as_hermes "$HPY" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import crewlib; print(crewlib.render(open(sys.argv[2]).read(), crewlib.load_crew()).strip())' "$KIT/vm" "$KIT/vm/mem0/extraction-rule.md")"
  key="$(env_get "$MEM0_ENV" ADMIN_API_KEY)"
  jq -n --arg r "$rule" '{custom_instructions: $r}' | curl -s -o /dev/null -m 20 -K <(printf 'header = "X-API-Key: %s"\n' "$key") \
    -H 'Content-Type: application/json' -X POST --data-binary @- http://127.0.0.1:8888/configure || warn "couldn't set the memory rule; it will use Mem0's default"
  ok "Memory keeps lasting facts only (never keys or phone numbers)"

  # Connect the agents: every agent reads and writes the owner's one shared memory. The chief's settings go in mem0.json,
  # not its .env, because the chief's .env reaches every agent's shell.
  local owner role prof aid
  owner="$(cj .owner.id)"
  for role in $ROLES; do
    prof="$(profile_of "$role")"; aid="$(jq -r --arg r "$role" '.agents[] | select(.role==$r) | .id' "$CREW_JSON")"
    if [ "$prof" = default ]; then   # printf is a shell builtin: the key never appears on a command line
      printf '{"host": "http://127.0.0.1:8888", "api_key": "%s", "user_id": "%s", "agent_id": "%s"}\n' "$key" "$owner" "$aid" \
        | install -o hermes -g hermes -m 600 /dev/stdin "$HH/mem0.json"
    else
      local f; f="$(env_of "$role")"
      echo "http://127.0.0.1:8888" | env_set "$f" MEM0_HOST
      printf '%s\n' "$key" | env_set "$f" MEM0_API_KEY
      printf '%s\n' "$owner" | env_set "$f" MEM0_USER_ID
      printf '%s\n' "$aid" | env_set "$f" MEM0_AGENT_ID
    fi
  done
  key=""
  ok "All four agents share one memory"
}
