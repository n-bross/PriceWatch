#!/usr/bin/env bash
# Install only the recurring expanded price imports. Existing API timers stay active.
set -euo pipefail
api_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for job in bulk-globus bulk-combi mytime recovered-offers edeka rossmann; do
  for kind in service timer; do
    sed "s|@API_DIR@|${api_dir}|g" \
      "${api_dir}/deploy/pricewatch-${job}.${kind}" \
      > "/etc/systemd/system/pricewatch-${job}-e70d379d.${kind}"
  done
done
systemctl daemon-reload
for job in bulk-globus bulk-combi mytime recovered-offers edeka rossmann; do
  systemctl enable --now "pricewatch-${job}-e70d379d.timer"
done
