# Third-party tools

Tools are downloaded only through explicit setup and are excluded from this plugin's release archive. Their license and notice files remain in the installed distributions.

| Tool | Pin | Upstream license |
| --- | --- | --- |
| Pyright | 1.1.414 | MIT |
| TypeScript | 5.9.3 | Apache-2.0 |
| typescript-language-server | 6.0.3 | MIT |
| debugpy | 1.8.22 | MIT, with vendored pydevd notices |
| vscode-js-debug | 1.140.0 | MIT, with bundled dependency notices |

Exact npm transitive dependency versions and integrity values are in `toolchain/package-lock.json`. Download URLs and SHA-256 values for the debugger packages are in `toolchain/downloads.json`. The installed receipt records the verified inputs. No OMP or Hermes code is bundled.
