# Saved kubectl output for M3's extractor

Hand-written, not recorded from a cluster: there is no dev cluster yet (W2-11 is deferred). Each file has the shape `kubectl get <resource> -n <namespace> -o json` returns, trimmed to the fields M3 reads. `index.json` maps every command the extractor sends to the file that answers it.

It describes the same test cluster as `../snapshot_hotel_reservation.json`. These are the differences, and each comes from what real kubectl output contains:

- `search` has no PodDisruptionBudget, so its minimum is unknown. Its rolling-update limits are the Kubernetes defaults, 25% / 25%.
- `mongodb-geo` (the pod that uses `geo-pvc`) is included, with the `Recreate` strategy.
- There is no PVC with an unknown "in use" value. kubectl output always lists the pods, so the extractor can always tell.

Use it by setting `ARGUS_M3_KUBECTL_OUTPUT=data/fixtures/m3/kubectl` (run from the repo root).
