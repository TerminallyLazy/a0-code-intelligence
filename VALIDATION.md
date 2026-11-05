# Validation — Code Intelligence 0.3.0

Version 0.3.0 supports ordinary chats without an Agent Zero project. It uses the configured working directory, retaining project roots when selected. Automatic lifecycle installation and the thumbnails are unchanged.

Validated November 4, 2026 against upstream `agent0ai/agent-zero` `ready` at [`ba9b67df0f54ac78106ae85c552ef5d2458f7c9a`](https://github.com/agent0ai/agent-zero/tree/ba9b67df0f54ac78106ae85c552ef5d2458f7c9a).

## Verified environment

Disposable Linux Docker containers used the pinned upstream source over the locally available Agent Zero image (`05d6ab347bd7`), framework Python 3.12.4, execution Python 3.13.14 and Node 22.22.0. Project files, servers and adapters shared that runtime. The user's active Agent Zero instance was not modified. No core source changes were needed.

Tool setup installed Pyright 1.1.414, TypeScript 5.9.3, typescript-language-server 6.0.3, debugpy 1.8.22 and vscode-js-debug 1.140.0. npm integrity is locked in `toolchain/package-lock.json`; downloaded Python/debug-adapter archives have SHA-256 checksums in `toolchain/downloads.json`. Setup now runs automatically during installation and updates, inside plugin-owned storage.

## 0.3.0 non-project workspace verification

Seven added framework tests cover ordinary chats with no project: actual status/grant API calls, read-only resolution of an absent working directory and its creation on grant, native edit-hook diagnostics, real Python references/rename/apply, real TypeScript type errors, configured Python debugging with breakpoint/stack inspection, separate debug authorization and chat ownership, root changes with server cleanup, project precedence, and path/symlink escape rejection. These synthetic fixtures use the native `workdir_path` setting and create no Agent Zero project for non-project operations.

The complete suite has 57 Python tests, including an installation test for namespace refresh. The existing API policy test now supplies the handler's actual context lock and asserts the blocked-tool error. A Node store test checks that folder/context changes clear old query results, breakpoint inputs and debugger navigation, while an unchanged workspace preserves inputs. JavaScript syntax and source/package checks accompany it. No new browser acceptance or live-provider coding session is claimed.

The final Python suite passed in 49.794 seconds. A separate real `update_from_git` acceptance fixture started with installed 0.2.2 code and imported its project-only access module, then updated to 0.3.0 through the native installer. With tool downloads blocked, it reused the existing toolchain, imported the new access module, completed status/grant API calls without a project, and returned real Python diagnostics without restarting. Installation now releases the stopped plugin namespace; the repair API retains the modules used by its active request.

## 0.2.2 installation verification

The existing 39 framework/protocol/freshness/real-tool tests and ten installation tests pass. The installation tests cover matching-pin reuse, changed pins, missing entrypoints, corrupt receipts, checksum failure, npm failure, absent prerequisites, replacement rollback, shutdown before setup, recovery-journal protection, hook-cache invalidation and bounded cleanup retries. They use synthetic archives and do not replace real installation acceptance.

Agent Zero's actual `install_from_zip` installed a candidate ZIP in a fresh disposable runtime with no tool cache. Its installation hook downloaded all pinned tools automatically; no Execute or setup API call was made. All 48 tests present at that point passed from the installed copy in 43.005 seconds, followed by a real Python diagnostic and an uninstall that stopped the owned server. The final cleanup test was added after the Git update check exposed a host-mounted filesystem metadata race. JavaScript syntax and package contents were checked; this change does not claim a new browser acceptance run.

The pinned framework caches hooks between `pre_update` and `install`. From 0.2.2 onward, `pre_update` invalidates this plugin's hook entry, and `install` reads setup implementation from the installed source so updates use current code. Earlier releases retain their legacy hook during their first update: an already installed matching toolchain stays usable; if a legacy installation never prepared its tools, the Setup tab's repair control completes that one-time migration. No automatic download is added to ordinary activation or model/tool execution.

Actual Git installation and `update_from_git` passed against a local synthetic remote. A code-only update reused tools with download access blocked; a subsequent update restored a deleted Pyright entrypoint automatically. Injecting an npm failure into the native ZIP installer raised the failure and removed the failed installation. Checksum and replacement-failure tests preserved the previous toolchain and recovery data.

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

Reproduce the current 57-test Python suite and the Node store test using the commands in [README.md](README.md). Keep synthetic fixtures in a disposable runtime. The installer and lifecycle acceptance script/receipts accompany the local delivery separately from runtime plugin contents.
