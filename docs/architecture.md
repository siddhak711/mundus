# Architecture: one-way layers

Code depends in one direction only. The order is defined in `architecture/layers.txt` and is:

```
types -> config -> repo -> service -> runtime -> ui
```

A layer may import from any layer to its left and from nothing to its right.

| Layer | Holds | May import |
|---|---|---|
| `types` | data shapes, schemas, constants | nothing internal |
| `config` | typed configuration and its loading | types |
| `repo` | data access and persistence | config, types |
| `service` | business logic | repo, config, types |
| `runtime` | wiring, servers, jobs, entry points | service, repo, config, types |
| `ui` | presentation | runtime, service, repo, config, types |

## Providers

Cross-cutting concerns (auth, telemetry, feature flags, external connectors) live in `providers/` and are the only way such concerns enter the layers. `providers/` may import `types` and `config`. Layers from `repo` onward may import `providers/`. Nothing reaches an external system except through a provider.

## Layout

```
src/
  domains/<domain>/{types,config,repo,service,runtime,ui}/
  providers/
```

Start with one domain. Add a second only when a second business area exists. Code in one domain reaches another domain only through that domain's `service` layer.

## Enforcement

Status: **not enforced yet**. No stack has been chosen, and an import checker is language-specific.

The first `/build` chooses the stack. That build must add a checker that reads `architecture/layers.txt`, fails on any backward or cross-domain import, runs from `scripts/verify.d/`, and has a test proving a backward import fails. When that lands, update this section.
