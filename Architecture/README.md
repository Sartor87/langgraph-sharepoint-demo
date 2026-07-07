# Architecture

C4 model (Structurizr DSL) for the SharePoint Audit Agent — `workspace.dsl`,
plus `DOCs/` (per-level documentation) and `ADRs/` (decision records),
embedded into the workspace via the `!docs`/`!adrs` directives at the top of
`workspace.dsl`.

## Rendering locally (Structurizr Lite, via Podman)

Structurizr Lite serves the rendered diagrams + embedded docs/ADRs as a local
web app, reading `workspace.dsl` from a mounted directory.

Run from this directory (`Architecture/`) — the mount must point at the
folder containing `workspace.dsl`:

```powershell
podman run -it --rm -p 9999:8080 -v "${PWD}:/usr/local/structurizr" docker.io/structurizr/structurizr local
```

Then open `http://localhost:9999`. Views live under the diagram tabs, the
`DOCs/` pages under "Documentation", the `ADRs/` under "Decisions".

Stop with `Ctrl+C` (container removes itself, `--rm`).

## Docker equivalent

Same image/mount, just swap the binary:

```bash
docker run -it --rm -p 9999:8080 -v "$(pwd):/usr/local/structurizr" docker.io/structurizr/structurizr local
```

## Notes

- Port `9999` is arbitrary — only the container-side `8080` is fixed by the
  image. Change the host side (`-p <port>:8080`) if `9999` is taken.
- `${PWD}` (PowerShell) / `$(pwd)` (bash) must resolve to `Architecture/`
  itself, not the repo root — Structurizr Lite expects `workspace.dsl`
  directly at the mount root.
- This confirms the image runs and serves the workspace; it does not by
  itself confirm the `!docs`/`!adrs` directive syntax in `workspace.dsl` is
  correct for the image's bundled Structurizr version — check the
  "Documentation"/"Decisions" tabs render with content once the container is
  up, and fix the directives if they don't.
