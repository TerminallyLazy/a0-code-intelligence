### code_propose
Prepare semantic edits without changing files. Uses the same workspace trust as code_inspect.
Rename: action=rename, path, line, column, new_name.
Quick fixes: action=actions, path, line, column. Then action=resolve_action, path, action_id to preview a supported action.
Returns proposal ID, affected files, digests and diffs. Review correctness before applying. Proposals expire after 10 minutes and reject changed files. Existing-file text edits only; executable commands and file resource operations are unsupported.

Input schema for tool_args:
```json
{"type":"object","properties":{"path":{"type":"string"},"line":{"type":"integer","minimum":1},"column":{"type":"integer","minimum":1},"new_name":{"type":"string"},"action_id":{"type":"string"},"action":{"type":"string","enum":["rename","actions","resolve_action"]}},"required":["action","path"],"additionalProperties":false}
```
