# Demo scenario_02: cart keeps crashing (out of memory)

Hand-written and synthetic, for the PP1 demo: not recorded from a cluster.

- `telemetry.json`: a contract v1 telemetry batch, namespace `shop`. Requests flow frontend → checkout → cart, and cart fails. Cart's pods are OOMKilled and crash-looping, and its log names `CART_ADDR=redis-cart:6379` (correctly set). There is noise for M1 to prune: a product-catalog CPU spike off the failing path, and metrics-server errors in kube-system.
- `reads.json`: canned output for the three reads M2 runs on cart:
  - the deployment shows `CART_ADDR` set correctly, so it isn't a configuration fault;
  - the endpoints list a ready address, so it isn't a networking fault;
  - the pods show OOMKilled and CrashLoopBackOff, so it is a resources fault.

M3's cluster facts for `shop` are in `data/fixtures/m3/kubectl/shop/`. Cart has 2 replicas, `maxUnavailable: 1` and a PodDisruptionBudget with `minAvailable: 2`, so the rolling restart M2 proposes is blocked.
