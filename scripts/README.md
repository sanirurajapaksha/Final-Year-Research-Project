# Scripts

Helper scripts for development, e.g. setting up the local dev cluster or exporting cluster snapshots as fixtures.

Any script that changes a cluster must:
1. print the current kube context first, and
2. refuse to run unless that context matches `SRE_AGENT_KUBE_CONTEXT`, the disposable dev cluster.
