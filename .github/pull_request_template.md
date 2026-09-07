## Summary

Describe the observable change and its bounded scope.

## Validation

- [ ] Public-tree policy passes.
- [ ] Relevant targeted tests pass.
- [ ] Fast lane passes with `--progress`.
- [ ] Full lane passes when the change is ready to merge.

## Safety

- [ ] No credential, private configuration, runtime state, log or real identity is included.
- [ ] Randomness, clocks, network I/O and persistence remain outside deterministic transitions.
- [ ] Operational changes remain disabled by default and explicitly authorized.
