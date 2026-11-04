# Validation — Code Intelligence 0.2.1

Version 0.2.1 adds the plugin logo at `thumbnail.jpg` and `webui/thumbnail.jpg`, plus its README display. Both files are identical square 256px JPEGs below the community catalog's 20 KB thumbnail limit. Runtime behavior is unchanged from 0.2.0; the 39-test evidence below belongs to that tested implementation. Asset dimensions, file integrity, automatic Plugin Hub thumbnail path and archive contents were checked for this packaging update.

Validated November 4, 2026 against upstream `agent0ai/agent-zero` `ready` at [`ba9b67df0f54ac78106ae85c552ef5d2458f7c9a`](https://github.com/agent0ai/agent-zero/tree/ba9b67df0f54ac78106ae85c552ef5d2458f7c9a).

## Verified environment

Disposable Linux Docker containers used the pinned upstream source over the locally available Agent Zero image (`05d6ab347bd7`), framework Python 3.12.4, execution Python 3.13.14 and Node 22.22.0. Project files, servers and adapters shared that runtime. The user's active Agent Zero instance was not modified. No core source changes were needed.

Tool setup installed Pyright 1.1.414, TypeScript 5.9.3, typescript-language-server 6.0.3, debugpy 1.8.22 and vscode-js-debug 1.140.0. npm integrity is locked in `toolchain/package-lock.json`; downloaded Python/debug-adapter archives have SHA-256 checksums in `toolchain/downloads.json`. Setup is explicit, isolated and separate from plugin installation.

## 0.2.0 enhancement verification

The enhanced source passed 35 framework/protocol/real-tool tests plus four focused diagnostic-freshness tests (39 total). New coverage verifies idle server shutdown without losing monitoring, recovery with OS events deliberately removed, keep-warm behavior, passive status polling, disabled-language policy, TypeScript .mts/.cts and repeated clean edits, rejection of disk changes during requests, timeouts, malformed results and invalid unchanged pull responses.

TypeScript now returns correlated synchronous syntax/semantic results from the pinned real server. The existing Python/Node/TypeScript debugger and safe code-action fixtures remain green. No new dependencies were installed. The native panel adds one monitoring status line and the timeout setting now accepts 0; JavaScript syntax was checked. The earlier full visual acceptance below applies to the 0.1.0 layout; this update does not claim a new browser acceptance run.

## Original 0.1.0 acceptance evidence

| Layer | Result |
| --- | --- |
| Framing, process custody and edit contracts | 11 tests passed: fragmented UTF-8 framing, invalid/oversized frames, process exit, cancellation, lease EOF, UTF-16/UTF-8/CRLF offsets, overlapping edits, stale proposals, symlink/resource-operation rejection, mode preservation and conditional rollback |
| Native framework integration | 13 tests passed: discovery, six independent policy identities, typed native tool schemas, both Chat and Responses dispatch, real extension feedback, bounded completion deferral, policy enforcement in hooks/API, trust/topology rejection, context ownership, external edit refresh, secret-reference resolution/masking and cleanup |
| Real tools | 7 tests passed: Pyright diagnostics/references/cross-file rename; TypeScript diagnostics/import quick fix; Python and Node debugger values/stepping; TypeScript source maps; configured stdio debug adapter; stale pushed diagnostics |
| Clean archive installation | Agent Zero's actual `install_from_zip` installed the ZIP in a fresh pinned-source runtime. Installation did not download tools. Running the plugin's actual `execute.py` installed the pinned packages. All 31 tests then passed from the installed copy in 36.917 seconds |
| Real lifecycle integration | Actual `after_plugin_change(..., python_change=True)` purged/reimported the plugin namespace. Old manager/processes stopped; the new module restarted diagnostics. Scoped disable/re-enable and actual `uninstall_plugin` also stopped the owned manager/processes |
| Native WebUI | Real authenticated/CSRF-preserving Agent Zero routes and native surface in a synthetic UI fixture: diagnostic file opened in the editor, rename preview/applied file readback, stale-apply error notification, breakpoint/stack/locals, step from value 4 to 6, native light/dark themes, keyboard tab navigation and 390-pixel layout |

The real-tool tests verify semantic outcomes and debugger values. Dispatch tests exercise both actual core dispatch paths with the final service result replaced by a deterministic fixture; they do not claim a live provider/model conversation. The UI fixture runs Agent Zero's real WebUI server with a synthetic project and context, without embedding preload or a full production boot. Its source archive lacks `.git`, so the unrelated native self-update panel reports unavailable Git version metadata.

One measured tiny Python fixture took **463 ms** from server startup to a versioned diagnostic, followed by **270 / 267 / 262 ms** for three warm edits. This is one local fixture, not a performance guarantee. The default 750 ms post-edit budget and 5 s completion budget remain bounded; larger/cold projects can defer feedback.

## UI design and review

The panel uses Agent Zero's existing Rubik/Roboto Mono typography, semantic color variables, native Material `<x-icon>` elements, notifications, surface host and editor. No UI framework, font or icon dependency was added. File diagnostics show severity/location/freshness; edit previews retain unified-diff markers; debugger controls have accessible names and distinct enabled states. Stack/scopes/locals load automatically at a stop. Variable navigation supports returning from expanded values.

The legibility follow-up raised body copy to 14px and functional labels to at least 12px, verified through computed styles at desktop and 390px widths. The operation-only busy indicator remains; its empty pseudo-element is not scrolling content and reduced-motion disables it. A file-scoped Impeccable exception records that false positive.

The frontend-design review retained the host's visual identity, replaced default browser controls, reduced raw protocol data to expandable details and checked desktop, narrow, light, dark and keyboard states. Screenshots, when included in release evidence, use synthetic files only.

## Maintainer-history evidence (`frdel`)

This is an evidence-backed alignment judgment, not a claim of maintainer approval.

| Observed diff | Applied inference | Confidence |
| --- | --- | --- |
| [`7e1d9ad2`](https://github.com/agent0ai/agent-zero/commit/7e1d9ad2a4a3d186e337a89433ccc5128bdc754d): module/qualname extension paths | Use native editor and plugin-lifecycle extension seams | High |
| [`89d4b891`](https://github.com/agent0ai/agent-zero/commit/89d4b8913f400d92ac00e4d143c17d3e76ad9f25): module loading and plugin namespace purge | Own background resources explicitly and verify a real module reload | High |
| [`4ffcdf52`](https://github.com/agent0ai/agent-zero/commit/4ffcdf5246ba6f31bd27a44f41af41adf1c8cefd): definitive process exit and lazy shell restart | Treat process exit as failure/completion; restart language servers on demand | High |
| [`bebe6826`](https://github.com/agent0ai/agent-zero/commit/bebe6826cf8a654d1423a9aa0f1c118116a3bc0e): shared stop behavior and central WebUI discovery | Tools and UI share the same service and lifecycle owner | Medium |

## Boundaries

- Verified deployment: same-runtime Linux/Docker. Native-host, split RFC development and Connector remote projects are unsupported.
- Pyright diagnostics are version-correlated. TypeScript now uses fixed synchronous syntax/semantic requests checked against the saved revision. Unversioned push fallback remains explicitly unversioned and cannot supersede a correlated verdict.
- Semantic mutation supports existing-file text edits. Resource operations, arbitrary server commands and unsolicited apply-edit requests are rejected.
- Debugging supports owned launch targets. Arbitrary attach, evaluation, variable mutation, browser/child-process debugging and conditional/log breakpoints are not supported.
- Extra stdio servers/adapters are configurable. Only the named fixtures are acceptance evidence; a generic configuration does not certify another language.
- Per-file atomic replacement plus a recovery journal is not a global filesystem transaction. Conflicting external changes are preserved and require reconciliation.
- This document records local acceptance evidence. Source publication and community catalog acceptance are tracked separately through GitHub releases and pull requests. No production deployment or live-provider coding session is claimed.

Reproduce the current 39-test suite using the command in [README.md](README.md). Keep its synthetic projects in a disposable runtime. The installer and lifecycle acceptance script/receipts accompany the local delivery separately from runtime plugin contents.
