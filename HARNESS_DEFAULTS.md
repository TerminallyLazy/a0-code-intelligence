# Default LSP behavior across harnesses

Reviewed November 4, 2026. “Ships a definition” does not mean “bundles a binary” or “starts a process at launch.” This is source/documentation review; the competitors were not runtime-tested here.

| Harness | Default activation | Servers available through its default configuration | Installation and startup |
| --- | --- | --- | --- |
| OMP | LSP on; lazy startup on | 55 registry entries, including alternative servers and linters; Python, TS/JS, Go, Rust, C/C++, Swift, web/config languages and more | Auto-detection requires project markers and an available binary. Starts on first matching use. Write diagnostics on; edit diagnostics off; deduplication on. |
| Hermes | LSP on; git workspace required | 28 registry entries: Pyright, TypeScript, web frameworks, Go, Rust, C/C++, shell, YAML and more | Default install strategy is auto for supported recipes; others require a supplied toolchain. First relevant use starts a server. Idle timeout 600 seconds; 0 keeps it warm. |
| OpenCode | LSP off in current documentation | Broad built-in catalog including Pyright, TypeScript, gopls, rust-analyzer, clangd, SourceKit, web frameworks and config languages | Enable with lsp: true. Matching file opens start servers when requirements are met; several servers auto-download. Downloads can be disabled. |
| Claude Code | Requires a language plugin and server binary | Official marketplace covers C/C++, C#, Go, Java, Kotlin, Lua, PHP, Python, Ruby, Rust, Swift, TS/JS; also Shopify's Liquid plugin | Plugin contains configuration, not the binary. First matching edit starts the server. Current docs exclude plugin LSP startup in cloud sessions. |
| Pi | No LSP in the base coding-tool set inspected | Extensions provide their own catalogs | For example arcdev-llc/pi-lsp uses installed PATH binaries, warms detected languages at session start and defaults to agent-end diagnostics. This is extension behavior. |
| DeepSeek Harness | Deployment supplies LSP configuration | No language servers shipped by the LSP package group | Configured stdio providers expose definition, references, implementation and hover. This subsystem is navigation, not an automatic type-check loop. |
| Agent Zero Code Intelligence 0.2.0 | Automatic diagnostics on once plugin setup and project access are complete | Two pinned server families: Pyright and typescript-language-server; custom stdio configuration supported | Explicit isolated setup, then lazy per-language startup. Idle servers sleep after 300 seconds while monitoring continues; 0 keeps indexes warm. |

## Source receipts

- OMP [settings](https://github.com/can1357/oh-my-pi/blob/60250b666ea10999dc38060db0f697d8ba224e88/packages/coding-agent/src/lsp/settings.ts), [registry](https://github.com/can1357/oh-my-pi/blob/60250b666ea10999dc38060db0f697d8ba224e88/packages/coding-agent/src/lsp/defaults.json), [detection/configuration](https://github.com/can1357/oh-my-pi/blob/60250b666ea10999dc38060db0f697d8ba224e88/docs/lsp-config.md).
- Hermes [registry](https://github.com/NousResearch/hermes-agent/blob/785c2e5110eb3fbfc5346fd8370ca96910aaa1f3/agent/lsp/servers.py), [direct TypeScript diagnostics](https://github.com/NousResearch/hermes-agent/blob/785c2e5110eb3fbfc5346fd8370ca96910aaa1f3/agent/lsp/sync_diagnostics.py), [documented defaults and lifecycle](https://hermes-agent.nousresearch.com/docs/user-guide/features/lsp).
- OpenCode [current official LSP documentation](https://opencode.ai/docs/lsp/) (page updated November 2, 2026).
- Claude Code [official code-intelligence documentation](https://code.claude.com/docs/en/plugins/code-intelligence).
- Pi [base tool definitions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/index.ts); [arcdev-llc LSP extension](https://github.com/arcdev-llc/pi-lsp). The Pi repository has moved from badlogic/pi-mono to earendil-works/pi.
- DeepSeek Harness [LSP package group](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/lsp/README.md).

## Exact OMP registry IDs

`rust-analyzer`, `tlaplus`, `clangd`, `zls`, `gopls`, `typescript-language-server`, `typescript-native`, `biome`, `eslint`, `denols`, `vscode-html-language-server`, `vscode-css-language-server`, `vscode-json-language-server`, `tailwindcss`, `svelte`, `vue-language-server`, `astro`, `pyright`, `basedpyright`, `pylsp`, `ty`, `ruff`, `jdtls`, `kotlin-lsp`, `metals`, `hls`, `ocamllsp`, `elixirls`, `expert`, `erlangls`, `gleam`, `solargraph`, `ruby-lsp`, `rubocop`, `bashls`, `lua-language-server`, `intelephense`, `phpactor`, `omnisharp`, `yamlls`, `terraformls`, `dockerls`, `helm-ls`, `nixd`, `nil`, `ols`, `dartls`, `marksman`, `texlab`, `graphql`, `prismals`, `vimls`, `emmet-language-server`, `sourcekit-lsp`, `swiftlint`.

These 55 entries are not 55 simultaneously running processes or 55 distinct languages. They include alternatives, lint-only definitions and a TypeScript native/server selection policy. OMP selects the native TypeScript LSP for a compatible TypeScript 7 installation; earlier TypeScript uses typescript-language-server.

## Exact Hermes registry IDs

`pyright`, `typescript`, `vue-language-server`, `svelte-language-server`, `astro-language-server`, `gopls`, `rust-analyzer`, `clangd`, `bash-language-server`, `yaml-language-server`, `lua-language-server`, `laravel-lsp`, `intelephense`, `ocaml-lsp`, `dockerfile-ls`, `terraform-ls`, `dart`, `haskell-language-server`, `julia`, `clojure-lsp`, `nixd`, `zls`, `gleam`, `elixir-ls`, `prisma`, `kotlin-language-server`, `jdtls`, `powershell`.

A registry match is not proof that the binary or its diagnostic backend exists. For example bash-language-server needs shellcheck for useful diagnostics. Hermes distinguishes recipes it can install from servers requiring manual setup.

## Changes applied to this plugin

1. Preserve the authorized project monitor when idle language servers close. Watched changes restart the matching server, and up to 200 tracked files retain metadata reconciliation even when OS events are missed.
2. Offer idle_seconds: 0 for warm language-server indexes. UI status polling no longer extends server activity.
3. Use fixed TypeScript syntax/semantic requests with a bounded total wait and saved-revision checks. Late unversioned pushes cannot overwrite correlated results. Invalid or timed-out responses never prove clean.
4. Cover .mts and .cts, per-language disablement and server initialization options.
5. Display monitoring separately from running server processes in the native panel.

## Remaining expansion

This update does not claim the competitors' language breadth. Go, Rust, C/C++, Swift, HTML/CSS/JSON/YAML and framework servers remain custom configurations, not installed or certified default support. A next language pack should provide pinned installation recipes, availability/backend checks and real diagnostic fixtures before being advertised as included.

Other useful work remains: project-wide checks, nested package roots, complete dropped-event recovery for unopened files, exact introduced-error deltas and semantic-server sharing across contexts with matching authority. The current monitor starts through an authorized project context and does not scan the whole machine.

Codex, T3 Code, Cursor and the ambiguously named j-code are not assigned a default-LSP verdict in this review. Provider/editor capabilities and community extensions must be traced separately before making such a claim.
