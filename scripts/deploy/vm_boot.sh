#!/usr/bin/env bash
# Hands-off deploy for a Google Compute Engine VM (Ubuntu 24.04): pass this file as the instance's
# startup-script metadata. It clones the repository, writes .env from instance metadata and runs
# vm_setup.sh, so no SSH session is needed. Progress is printed to the serial console as MUNDUS-SETUP lines.
#
# Keys are read from metadata attributes named mundus-<KEY>, for example mundus-ANTHROPIC_API_KEY.
# Delete those attributes once the console shows "MUNDUS-SETUP env-written": instance metadata is
# readable by anyone with viewer access to the project. Optional attribute mundus-branch picks the branch.
set -uo pipefail
DONE=/var/lib/mundus-setup-done
[ -f "$DONE" ] && exit 0
exec > >(tee -a /var/log/mundus-setup.log) 2>&1
echo "MUNDUS-SETUP start $(date -u +%FT%TZ)"
md() { curl -sf -H 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1" || true; }

id mundus >/dev/null 2>&1 || useradd -m -s /bin/bash mundus
echo 'mundus ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/mundus && chmod 440 /etc/sudoers.d/mundus
apt-get update -qq && apt-get install -y -qq git openssl

R=/home/mundus/mundus
BR="$(md mundus-branch)"; BR="${BR:-main}"
[ -d "$R/.git" ] || sudo -u mundus git clone -q https://github.com/siddhak711/mundus "$R" \
  || { echo "MUNDUS-SETUP FAILED clone"; exit 0; }
sudo -u mundus -H bash -c "cd '$R' && git fetch -q origin '$BR' && git checkout -q -B '$BR' FETCH_HEAD" \
  || { echo "MUNDUS-SETUP FAILED checkout $BR"; exit 0; }

touch "$R/.env"; chmod 600 "$R/.env"; chown mundus:mundus "$R/.env"
for k in MATTERPORT_API_KEY MATTERPORT_API_TOKEN VEXCEL_API_KEY COSTAR_KIT_URL COSTAR_ZIP_PASSWORD ANTHROPIC_API_KEY LANGSMITH_API_KEY; do
  if ! grep -q "^${k}=." "$R/.env"; then
    v="$(md "mundus-$k")"
    [ -n "$v" ] && printf "%s='%s'\n" "$k" "$v" >> "$R/.env"
  fi
done
echo "MUNDUS-SETUP env-written keys: $(cut -d= -f1 "$R/.env" | tr '\n' ' ')"
if ! grep -q "^ANTHROPIC_API_KEY=." "$R/.env"; then echo "MUNDUS-SETUP FAILED no Anthropic key"; exit 0; fi

# Empty lines answer the prompt for any optional key that was not supplied.
if { yes '' || true; } | sudo -u mundus -H bash -c "cd '$R' && bash scripts/deploy/vm_setup.sh"; then
  touch "$DONE"; echo "MUNDUS-SETUP DONE $(date -u +%FT%TZ)"
else
  echo "MUNDUS-SETUP FAILED vm_setup rc=$? $(date -u +%FT%TZ)"
fi
