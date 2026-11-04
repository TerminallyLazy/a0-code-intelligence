### debug_control
Control an owned debug session. Arguments: session_id, action.
Actions: breakpoints (path, lines; replaces all breakpoints for that file), pause, continue, next, step_in, step_out, stop.
Continue/steps require current stop_generation from debug_inspect; optional thread_id and wait_seconds (max 10).
Only source breakpoints supported. Stop ends only this plugin's owned adapter/debuggee. Never infer that a timed-out control request did not execute: inspect session status before deciding the next action.

Input schema for tool_args:
```json
{"type":"object","properties":{"session_id":{"type":"string"},"path":{"type":"string"},"lines":{"type":"array","items":{"type":"integer","minimum":1}},"stop_generation":{"type":"integer","minimum":0},"thread_id":{"type":"integer","minimum":0},"wait_seconds":{"type":"number","minimum":0,"maximum":10},"action":{"type":"string","enum":["breakpoints","pause","continue","next","step_in","step_out","stop"]}},"required":["action","session_id"],"additionalProperties":false}
```
