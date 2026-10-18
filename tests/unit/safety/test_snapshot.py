from argus.safety.snapshot import facts_for


def test_deployment_facts(snapshot):
    geo = {"replicas": 3, "min_replicas": 2, "max_unavailable": 1, "max_surge": None}
    assert facts_for(snapshot, "deployment", "hotel-reservation", "geo") == geo
    profile = facts_for(snapshot, "deployment", "hotel-reservation", "profile")
    assert profile["max_unavailable"] == "50%"


def test_pvc_facts(snapshot):
    assert facts_for(snapshot, "pvc", "hotel-reservation", "geo-pvc") == {"in_use": True}
    assert facts_for(snapshot, "pvc", "hotel-reservation", "old-pvc") == {"in_use": False}


def test_missing_field_is_none(snapshot):
    assert facts_for(snapshot, "pvc", "hotel-reservation", "mystery-pvc") == {"in_use": None}


def test_target_not_in_the_snapshot_is_none(snapshot):
    assert facts_for(snapshot, "deployment", "hotel-reservation", "ghost") is None
    assert facts_for(snapshot, "pvc", "hotel-reservation", "ghost-pvc") is None
    assert facts_for(snapshot, "pvc", "other-namespace", "geo-pvc") is None


def test_pods_and_namespaces_need_no_facts(snapshot):
    assert facts_for(snapshot, "pod", "hotel-reservation", "geo-1") == {}
    assert facts_for(snapshot, "namespace", "kube-system", "kube-system") == {}
