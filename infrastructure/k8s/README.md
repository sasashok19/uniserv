# k8s

Phase 1 baseline Kubernetes manifests. These are intentionally minimal —
the full deployment story (image registry, ConfigMaps/Secrets, HPA, Ingress,
backup sidecar, GKE Autopilot specifics) is finalised in **16_DEPLOYMENT**.

## Apply order
```bash
kubectl apply -f namespace.yaml
kubectl apply -f valkey.yaml
kubectl apply -f db-writer.yaml
kubectl apply -f ai-core.yaml
kubectl apply -f api-gateway.yaml
kubectl apply -f dashboard.yaml
```

## Notes
- `db-writer` runs exactly **one** replica (single-writer pattern) with a PVC
  and `Recreate` strategy so two writers never overlap.
- Images are tagged `uniserve/<service>:dev` — build/push via the per-service
  Dockerfiles before applying.
- All probes hit the same health endpoints used in local dev.
