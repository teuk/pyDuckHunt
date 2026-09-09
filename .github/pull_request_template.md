## Summary

Describe the observable change and its bounded scope.

Link a related issue if applicable. Explain any configuration or update step.

## Validation

- [ ] Public-tree policy passes.
- [ ] Relevant targeted tests pass.
- [ ] Fast lane passes with `--progress`.
- [ ] Full lane passes when the change is ready to merge.

State which languages and environments were checked, and what remains untested.
For message changes, confirm that formatting fields and private routing still work.

## Safety

- [ ] No credential, private configuration, runtime state, log or real identity is included.
- [ ] Randomness, clocks, network I/O and persistence remain outside deterministic transitions.
- [ ] Operational changes remain disabled by default and explicitly authorized.
