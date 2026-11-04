### debug_launch
Start one configured project debug target after project debugging is trusted in the UI.
Arguments: target (configured name), breakpoints (optional [{path, lines:[positive line numbers]}]).
Python and Node.js supported; TypeScript uses compiled JavaScript plus source maps. No arbitrary command, attach address, PID, evaluation or environment overrides.
Returns session_id, state and stop_generation. A running launch is not yet a verified breakpoint stop. Use debug_inspect status. Debuggee execution and variable rendering can have side effects.

Input schema for tool_args:
```json
{"type":"object","properties":{"target":{"type":"string"},"breakpoints":{"type":"array","maxItems":100,"items":{"type":"object","properties":{"path":{"type":"string"},"lines":{"type":"array","items":{"type":"integer","minimum":1}}},"required":["path","lines"],"additionalProperties":false}}},"required":["target"],"additionalProperties":false}
```
