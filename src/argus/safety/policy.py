"""M3's own safety policy: values M3 decides, not facts read from the cluster."""

# Invariant I2: a write command must not change anything in these namespaces.
# Kubernetes creates them for its own components (kubernetes.io docs, "Namespaces").
# "default" is also created by Kubernetes, but it is meant for user workloads, so it is not protected.
PROTECTED_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}
