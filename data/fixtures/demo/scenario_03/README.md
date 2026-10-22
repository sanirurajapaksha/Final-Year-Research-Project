# Demo scenario_03: hotel search fails (MongoDB disk full)

Hand-written and synthetic, for the PP1 demo: not recorded from a cluster.

- `telemetry.json`: a contract v1 telemetry batch, namespace `hotel-reservation` (DeathStarBench hotel
  reservation). Requests flow frontend → search → geo, and geo fails because its database, `mongodb-geo`,
  is crash-looping: its `/data/db` volume is full (`filesystem_utilization` 0.99, WiredTiger "No space left
  on device", then a WT_PANIC). MongoDB sends no spans, so it is missing from M1's call graph; geo's error
  names it (`Addr: mongodb-geo:27017`). Noise for M1 to prune: a profile CPU spike, a full memcached-profile,
  kube-proxy iptables errors and dropped Jaeger spans.
- `reads.json`: canned output for the reads M2 runs on mongodb-geo, and the two lookups for its fix note:
  - `kubectl logs deployment/mongodb-geo --previous` shows the ENOSPC write error, so it is a storage fault;
  - `kubectl describe pods -l app=mongodb-geo` shows CrashLoopBackOff, but the last run ended with
    `Reason: Error`, exit code 14, not OOMKilled, so it isn't a resources fault;
  - the deployment mounts PVC `geo-pvc`, and the PVC holds 1Gi on storage class `standard`.
  The geo reads (ready endpoint, Running pod) are there for runs that test geo too.

M2 confirms "mongodb-geo [storage] data volume full" and proposes no write: a restart crashes again on the same
full disk, and deleting the PVC loses the data. Its note gives a person the expansion command
(`kubectl patch pvc geo-pvc ... "storage":"2Gi"`), which M3 has no rule to check yet.
