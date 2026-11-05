# Code Intelligence for Agent Zero

<img src="thumbnail.jpg" alt="Code Intelligence logo" width="128" height="128">

Language-server diagnostics, semantic navigation and edits, and a debugger in Agent Zero's normal coding loop. This is a standalone community plugin. It requires no changes to Agent Zero core.

Target: upstream `ready` at `ba9b67df0f54ac78106ae85c552ef5d2458f7c9a`. Framework Python 3.12+; Linux/Docker with workspace files and tools in the same runtime. See [VALIDATION.md](VALIDATION.md) for actual acceptance evidence.

## Install and enable

1. Install the [latest release ZIP](https://github.com/TerminallyLazy/a0-code-intelligence/releases/latest) through Agent Zero's Plugin Hub ZIP installer, or install from `https://github.com/TerminallyLazy/a0-code-intelligence`. Installation automatically prepares the pinned language servers and debug adapters through `hooks.py`. No Execute action is needed.
2. Open any chat and enable Code Intelligence for its agent/profile. **No project is required.**
3. In plugin settings, select the Python and Node executables. Defaults are `/opt/venv/bin/python` and `/usr/bin/node`; choose the workspace's virtual environment when appropriate. Use global/profile settings for ordinary chats and project settings for a selected project.
4. Open **Code Intelligence → Setup**, review the displayed folder/environment configuration and grant semantic access. Grant debugging separately when needed. A configuration, executable or workspace change requires a new review.

## Workspaces with or without projects

With a project selected, Code Intelligence uses that project's directory and scoped settings. Otherwise it uses Agent Zero's configured **Working directory** (`workdir_path`, normally `/a0/usr/workdir`), matching native code execution and the chat file browser. Diagnostics, semantic navigation/edits, automatic edit feedback and configured debug targets work in either mode. A shell's later `cd` does not change this root; relative file and program paths resolve inside the displayed workspace.

The panel displays the resolved folder before access is granted. If a new working directory does not exist, granting access creates it; status reads do not create folders. Changing the working directory invalidates the old grant and closes its servers/debuggers. Switching between project and non-project mode also requires the matching workspace grant, even if both point at the same folder. Ordinary chats using the same folder/profile/configuration share the reviewed access, while sessions and edit proposals remain owned by their originating chat/agent. Files outside the active root are rejected, including symlink escapes.

## Tool installation and maintenance

Downloads are pinned and checksum-verified in `.runtime/tools/`; no global or project dependencies are installed. Node.js and npm must already exist in the Agent Zero runtime. Initial installation and changed tool pins require internet access. Git updates run the same installation hook and reuse an intact toolchain when its pins match. A failed installation is reported by Plugin Hub; a failed tool refresh preserves the previous tools. Importing or enabling the plugin does not download tools or grant project access.

**Repair tools** in the Setup tab reruns the same lifecycle hook if plugin-owned tool files are damaged. Repair stops active sessions before replacing tools. For development, keep the repository at `usr/plugins/code_intelligence/` and run the framework's `helpers.plugins.call_plugin_hook("code_intelligence", "install")` after copying it; copying a directory bypasses Plugin Hub's installation lifecycle.

When upgrading from 0.2.1 or earlier on the pinned Agent Zero build, existing tools carry over. If you never completed that older version's setup, use **Repair tools** once: the framework can retain the old installation hook during that first update. Version 0.2.2 clears its hook cache before subsequent updates.

## Coding tools

| Tool | Operations |
| --- | --- |
| `code_inspect` | status, diagnostics, definition, references, hover, document/workspace symbols |
| `code_propose` | rename; list code actions; resolve an action to a preview |
| `code_apply` | apply a specific reviewed proposal |
| `debug_launch` | launch a named configured target with source breakpoints |
| `debug_control` | breakpoint replacement, pause, continue, next, step in/out, stop |
| `debug_inspect` | status, output, threads, stack, scopes, variables |

These are separate policy identities. Blocking a tool also blocks its API and automatic-hook use. Debug sessions and edit proposals belong to their originating chat/agent; another chat cannot take them over. A server/process is not a security sandbox: trusted project code and configured executables can execute with the runtime's operating-system authority.

After a successful native write or patch, the plugin synchronizes the saved file and appends bounded diagnostics. Saved file-browser edits use the same invalidation path. OS watchers detect external edits; open documents also receive a bounded one-second metadata reconciliation because mounted filesystems can miss events. Unopened new files rely on file events or an explicit inspection. Scans exclude `.git`, `node_modules`, virtual environments and plugin runtime storage.

Reports distinguish `current`, `unversioned`, `pending`, `stale` and `unavailable`. Pyright publishes correlated document versions. TypeScript uses fixed synchronous syntax and semantic diagnostic requests through the pinned server, fenced by the synchronized document version and saved-file digest. A clean response can therefore confirm that file's checked revision. Unsupported servers fall back to push/pull; unversioned pushes never confirm a clean edit or replace a correlated verdict. Timeouts and missing tools never count as passing diagnostics. Warm writes wait up to 750 ms by default; completion waits up to five seconds. New errors can return control to the model once for that edit generation. Pending checks remain explicitly pending.

The default setup provides **Pyright 1.1.414** for `.py`/`.pyi` and **typescript-language-server 6.0.3 with TypeScript 5.9.3** for `.ts`/`.tsx`/`.mts`/`.cts` and `.js`/`.jsx`/`.mjs`/`.cjs`. Servers start only when a matching file is edited or inspected, after setup and workspace access review. Enabling the plugin does not start every server or check every file. See [HARNESS_DEFAULTS.md](HARNESS_DEFAULTS.md) for the current competitor comparison and remaining expansion work.

Line/column tool inputs are one-based; columns use the negotiated server encoding (normally UTF-16). Project/server output is untrusted data, not instructions. Core secret masking is applied to tool and UI output; raw protocol streams are not logged.

## Semantic edits

`code_propose` returns file diffs and a proposal ID. Use `code_apply` within the authorized editing task or review/apply it in the UI. Proposals expire after ten minutes. A changed file, mismatched document version or restarted server invalidates the proposal.

Supported edits affect existing UTF-8 workspace files. Resource create/delete/rename operations, snippets, annotated edits and overlapping ranges are rejected. A rename concerns a language symbol, not a filesystem rename. Code actions must produce text edits. The pinned TypeScript server's `_typescript.applyCodeActionCommand` follow-up is omitted only when its `action.commands` list is absent/empty; arbitrary server commands and unsolicited `workspace/applyEdit` are never executed.

All files are preflighted and original content is journaled before mutation. Each replacement preserves file mode/ownership and is atomic per file. A multi-file edit is not atomic against external writers or power loss. Rollback only restores a file if it still contains this operation's output. Conflicts retain a private recovery journal under `.runtime/recovery/`; inspect it and reconcile the named files manually. Update/uninstall refuses to discard unresolved journals. Successful operations delete their journals.

Limits: 2 MiB per file; 5,000 files / 64 MiB for a semantic-edit snapshot; 100 edited files; 20 outstanding proposals; 100 diagnostics per report; bounded query output.

## Debug targets

Set the plugin's **Debug targets** JSON in global/profile or project settings, for example:

```json
{
  "python-example": {"type": "python", "program": "main.py", "args": []},
  "node-example": {"type": "node", "program": "dist/main.js", "args": []}
}
```

Programs resolve inside the active workspace. Compile TypeScript with source maps before debugging. The Node adapter briefly holds program entry while source-map breakpoints bind, then continues unless `stop_on_entry` is true or entry itself is a requested breakpoint.

Optional `env_secrets` maps environment variables to Agent Zero secret names, for example `"env_secrets": {"API_TOKEN": "PROJECT_API_TOKEN"}`. Values resolve from the selected chat's secret store only at launch; configuration and access reviews contain names, not secret values. Missing references fail before launch.

Read `session_id`, state and `stop_generation` from launch/status. Stack, scopes, variables and stepping require the current stopped generation. Handles become invalid on resume. Variable rendering is debugger-mediated and may have side effects. Output is capped at 32,768 characters, stacks at 50 frames per page and variables at 100 per page.

Python and Node fixtures verify breakpoint → stack → variables → step → changed value → continue → exit. TypeScript has a separate source-map fixture. Only one active debug session per workspace is allowed.

Not supported: arbitrary process/network attach; evaluation; variable mutation; memory/disassembly; conditional breakpoints/logpoints; browser debug targets; child-process auto-debugging. The standalone Node adapter's single owned-target bootstrap is supported; requests to launch additional targets are rejected.

## Other servers and adapters

Additional stdio implementations are configurable, not advertised as tested language support. Server overrides can replace `python` or `typescript`; a new server requires extensions, language ID and an absolute argv command:

```json
{
  "rust": {
    "extensions": [".rs"],
    "language_id": "rust",
    "command": ["/usr/local/bin/rust-analyzer"],
    "settings": {}
  }
}
```

Set `"python": {"disabled": true}` or `"typescript": {"disabled": true}` to disable one default server. Custom entries also accept `disabled`; `initialization` supplies a server-specific initialization-options object, while `settings` supplies workspace configuration. Configuration changes require a fresh workspace access review.

Custom **adapters** map a target type to `command` (stdio argv) and optional `launch_arguments`. A debug target of that type still supplies a workspace-contained `program`. Adapters requiring terminal reverse requests, attach or child sessions are unsupported. The plugin advertises only its implemented LSP/DAP capabilities. Unknown capabilities do not become guaranteed support.

## Process ownership and cleanup

Each process has a private parent-liveness lease and an owned process group. Parent exit, context removal, scope disablement, module reload and uninstall release owned services; normal cleanup completes within seconds. Idle language servers sleep after five minutes (configurable 30–3,600 seconds; `idle_seconds: 0` keeps them warm). The authorized workspace watcher and metadata checks for the most recent 200 opened files remain active, and a saved change wakes its server. Status polling does not keep servers artificially busy. The panel displays monitoring separately from running servers. Pending work is not reaped. Sleeping invalidates outstanding server-bound edit proposals.

Monitoring begins when the trusted context first enters the model/tool loop or opens the panel, and ends with context removal, revocation, disablement or process shutdown. It is not a machine-wide service. Unopened files require OS events or explicit inspection; there is no periodic whole-project scan. Up to four contexts/workspaces and four running language servers per workspace are allowed. Debug sessions retain idle cleanup (five minutes when language servers are set to stay warm). Debugger launches are never replayed automatically. Failed language servers restart on demand.

Split-host RFC development and Agent Zero Connector remote files return **unsupported execution location**. Configure the plugin inside the Docker runtime where the workspace actually lives. There is no silent path translation, remote install or host-process attachment.

## Development and tests

Run inside the framework environment from the Agent Zero root:

```sh
/opt/venv-a0/bin/python -m unittest discover -s usr/plugins/code_intelligence/tests -v
node usr/plugins/code_intelligence/tests/test_store.mjs
```

The suite includes real-tool acceptance and requires the pinned tool setup. It creates synthetic project fixtures and removes them; use a disposable runtime. `CI_TEST_NODE` and `CI_TEST_PYTHON` select fixture runtimes when defaults differ. No model/provider call is required. The execution Python is used for debuggees, not backend/hook tests.

Packaging excludes `.runtime`, caches, bytecode and private project data. Runtime `plugin.yaml` and Plugin Index metadata are different files. Source and versioned archives are published in this repository. The plugin is listed in the Agent Zero community catalog through [the accepted submission](https://github.com/agent0ai/a0-plugins/pull/682).

## Design sources

The plugin follows Agent Zero's native extension, settings, tool-policy and WebUI contracts. The design was informed by [OMP LSP/DAP](https://github.com/can1357/oh-my-pi/tree/33ea58aa7dfd696c1ac419ba51fb915660740ab2/packages/coding-agent/src), [Hermes post-write feedback](https://github.com/NousResearch/hermes-agent/blob/71736c9f32597bbca9d89cede5aa136e55946b2f/website/docs/user-guide/features/lsp.md), and the [LSP](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/) / [DAP](https://microsoft.github.io/debug-adapter-protocol/overview) specifications. Implementations here are plugin-local. Maintainer evidence and acceptance details are recorded in `VALIDATION.md`.
