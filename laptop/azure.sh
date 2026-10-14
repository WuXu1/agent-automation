# shellcheck shell=bash
# Step 2: the server on Azure (the same size as the original setup), and Step 3: putting it on your Tailscale network.
# Nothing on the server is reachable from the internet: there are no inbound firewall rules at all. The first contact goes
# through Azure's own "run command" (no SSH needed), which installs Tailscale on it; after that we use SSH over Tailscale.

RG_DEFAULT=crew-rg
VM_DEFAULT=crew-vm
VM_SIZE=Standard_B2als_v2            # 2 vCPU, 4 GB RAM: about $31.50 a month of credit
IMAGE=Canonical:ubuntu-24_04-lts:server:latest
PREFERRED_REGIONS="belgiumcentral francecentral switzerlandnorth norwayeast denmarkeast swedencentral polandcentral italynorth spaincentral germanywestcentral northeurope westeurope uksouth ukwest"

azure_login() {
  step "Step 2 of 4: your server on Azure"
  if ! az account show >/dev/null 2>&1; then
    say "  Sign in to Azure with your student account. A code appears below: open the link, type the code, sign in."
    az login --use-device-code -o none || die "Azure sign-in did not finish. Run ./install.sh again."
  fi
  local subs n
  subs="$(az account list --query "[?state=='Enabled'].[id,name]" -o tsv)"
  n="$(printf '%s\n' "$subs" | grep -c . || true)"
  [ "$n" -gt 0 ] || die "This Azure account has no active subscription. Activate Azure for Students first: https://azure.microsoft.com/free/students"
  local sid sname
  if [ -n "$(get AZ_SUB)" ] && printf '%s\n' "$subs" | grep -q "^$(get AZ_SUB)"; then sid="$(get AZ_SUB)"
  elif [ "$n" -eq 1 ]; then sid="$(printf '%s\n' "$subs" | cut -f1)"
  else
    say "  You have more than one Azure subscription:"
    printf '%s\n' "$subs" | awk -F'\t' '{printf "    %d) %s\n", NR, $2}'
    local pick; pick="$(ask "Which one should pay for the server? (number)" "1")"
    sid="$(printf '%s\n' "$subs" | sed -n "${pick}p" | cut -f1)"
    [ -n "$sid" ] || die "No subscription number $pick."
  fi
  az account set --subscription "$sid"
  sname="$(az account show --query name -o tsv)"
  put AZ_SUB "$sid"
  ok "Subscription: $sname"
  case "$sname" in *Student*) ;; *) warn "This isn't an 'Azure for Students' subscription: the server will be billed to it (about \$1.25 a day)." ;; esac
}

# Regions this subscription may use (student subscriptions are limited by a policy), best first.
allowed_regions() {
  local allowed r out=""
  allowed="$(az policy assignment list --disable-scope-strict-match \
              --query "[].parameters.listOfAllowedLocations.value[]" -o tsv 2>/dev/null | tr 'A-Z' 'a-z' | sort -u)"
  if [ -z "$allowed" ]; then echo "$PREFERRED_REGIONS"; return; fi
  for r in $PREFERRED_REGIONS; do printf '%s\n' "$allowed" | grep -qx "$r" && out="$out $r"; done
  for r in $allowed; do case " $out " in *" $r "*) ;; *) out="$out $r" ;; esac; done
  echo $out
}

create_vm() {
  local rg vm admin region
  rg="$(get AZ_RG)"; rg="${rg:-$RG_DEFAULT}"
  vm="$(get AZ_VM)"; vm="${vm:-$VM_DEFAULT}"
  admin="$(get VM_ADMIN)"; admin="${admin:-crew}"
  put AZ_RG "$rg"; put AZ_VM "$vm"; put VM_ADMIN "$admin"

  if az vm show -g "$rg" -n "$vm" -o none 2>/dev/null; then
    ok "Your server '$vm' already exists ($(az vm show -g "$rg" -n "$vm" --query location -o tsv))"
    put STEP_VM "done"; return
  fi

  say "  This makes one small Linux server: $VM_SIZE (2 processors, 4 GB memory), a 32 GB disk and an internet address"
  say "  for its outgoing traffic. Cost from your Azure credit: about ${B}\$1.25 a day${N} (\$37 a month), so \$100 of"
  say "  student credit lasts about 80 days. Nothing is charged to a card. README → 'Money' says what to do after."
  confirm "Create it now?" y || die "Stopped before creating anything."

  local regions; regions="$(allowed_regions)"
  note "Regions this subscription allows, best first: $regions"
  for region in $regions; do
    say "  Trying ${region}…"
    az group create -n "$rg" -l "$region" --tags project=agent-automation -o none 2>/dev/null || true
    local err
    if err="$(az vm create -g "$rg" -n "$vm" -l "$region" --image "$IMAGE" --size "$VM_SIZE" \
          --admin-username "$admin" --authentication-type ssh --ssh-key-values "$SSH_KEY.pub" \
          --os-disk-name "$vm-osdisk" --os-disk-size-gb 32 --storage-sku StandardSSD_LRS \
          --public-ip-address "$vm-ip" --public-ip-sku Standard --nsg "$vm-nsg" --nsg-rule NONE \
          --tags project=agent-automation -o none 2>&1)"; then
      put AZ_REGION "$region"; put STEP_VM "done"
      ok "Server created in $region"
      return
    fi
    case "$err" in
      *SkuNotAvailable*|*AllocationFailed*|*OverconstrainedAllocationRequest*|*QuotaExceeded*|*RequestDisallowedByPolicy*|*NotAvailableForSubscription*|*LocationNotAvailableForResourceType*|*capacity*)
        note "No room for this size in $region: $(printf '%s' "$err" | grep -oE '(SkuNotAvailable|AllocationFailed|QuotaExceeded|RequestDisallowedByPolicy|[A-Za-z]*Allocation[A-Za-z]*)' | head -n1)"
        az group delete -n "$rg" --yes -o none 2>/dev/null || true ;;
      *) printf '%s\n' "$err" >&2; die "Azure refused to create the server (message above). Nothing else was changed; run ./install.sh again to retry." ;;
    esac
  done
  die "None of your allowed regions has room for a $VM_SIZE right now. Try again in an hour (student capacity comes and goes)."
}

# Run a shell script on the VM through Azure (no SSH). Prints only the script's own output.
vm_run() {
  az vm run-command invoke -g "$(get AZ_RG)" -n "$(get AZ_VM)" --command-id RunShellScript --scripts "$1" \
     --query "value[0].message" -o tsv 2>/dev/null | sed -n '/^\[stdout\]/,/^\[stderr\]/p' | sed '1d;$d'
}

join_tailnet() {
  step "Step 3 of 4: connect the server to your Tailscale network"
  if [ -n "$(get VM_TS_IP)" ] && vm_reachable; then ok "Already connected: $(get VM_TS_IP)"; put STEP_TAILNET "done"; return; fi

  say "  Installing Tailscale on the server (through Azure, about a minute)…"
  local out url ip
  out="$(vm_run '
set -e
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh >/dev/null 2>&1
systemctl enable --now tailscaled >/dev/null 2>&1
ip=$(tailscale ip -4 2>/dev/null | head -n1 || true)
if [ -n "$ip" ]; then echo "TS_IP=$ip"; exit 0; fi
systemctl stop crew-ts-up 2>/dev/null || true; systemctl reset-failed crew-ts-up 2>/dev/null || true
systemd-run --unit=crew-ts-up --collect tailscale up --hostname='"$(get AZ_VM)"' >/dev/null
for i in $(seq 1 40); do
  url=$(journalctl -u crew-ts-up --no-pager 2>/dev/null | grep -oE "https://login.tailscale.com/[A-Za-z0-9/._-]+" | tail -n1)
  [ -n "$url" ] && { echo "TS_URL=$url"; exit 0; }
  ip=$(tailscale ip -4 2>/dev/null | head -n1 || true); [ -n "$ip" ] && { echo "TS_IP=$ip"; exit 0; }
  sleep 1
done
echo "TS_FAIL"')"
  ip="$(printf '%s\n' "$out" | sed -n 's/^TS_IP=//p' | head -n1)"
  url="$(printf '%s\n' "$out" | sed -n 's/^TS_URL=//p' | head -n1)"
  if [ -z "$ip" ]; then
    [ -n "$url" ] || { printf '%s\n' "$out" >&2; die "Tailscale did not start on the server (above). Run ./install.sh again."; }
    say
    say "  ${B}Open this link and approve the server${N}, signed in to the SAME Tailscale account as this computer:"
    say "    ${C}$url${N}"
    (open "$url" 2>/dev/null || xdg-open "$url" 2>/dev/null || true) &
    pause "When the page says the server is connected"
    for _ in 1 2 3 4 5 6; do
      ip="$(vm_run 'tailscale ip -4 2>/dev/null | head -n1')"
      ip="$(printf '%s' "$ip" | grep -oE '^100\.[0-9.]+' | head -n1)"
      [ -n "$ip" ] && break
      note "Not connected yet; checking again…"; sleep 10
    done
    [ -n "$ip" ] || die "The server didn't join Tailscale. Open the link again (run ./install.sh again for a fresh one)."
  fi
  put VM_TS_IP "$ip"
  ok "Server is on your Tailscale network at $ip"

  say
  say "  ${B}One setting to change now${N}, or the server drops off your network in 6 months:"
  say "  open https://login.tailscale.com/admin/machines , click the ••• next to '$(get AZ_VM)' and choose ${B}Disable key expiry${N}."
  say "  While you're there, open the DNS page and make sure ${B}MagicDNS${N} and ${B}HTTPS Certificates${N} are on (the dashboard needs them)."
  pause "Done"

  local tries=0
  until vm_reachable; do
    tries=$((tries+1))
    [ $tries -le 12 ] || die "I can't reach the server at $ip over Tailscale. Is Tailscale on and signed in on this computer (same account)? Then run ./install.sh again."
    note "Waiting for the server to answer over Tailscale…"; sleep 5
  done
  ok "This computer can reach the server privately"
  put STEP_TAILNET "done"
}
