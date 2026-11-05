### code_apply
Apply a reviewed code_propose result within the authorized editing task.
Arguments: proposal_id. No direct text/code input. Rejects stale content, expired proposals, restarted servers, unsupported edits and workspace escapes.
After applying, inspect diagnostics and run relevant tests. Partial failure returns a recovery journal; preserve it and inspect conflicts rather than retrying blindly.

Input schema for tool_args:
```json
{"type":"object","properties":{"proposal_id":{"type":"string"}},"required":["proposal_id"],"additionalProperties":false}
```
