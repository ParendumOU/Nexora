# Run Python

Execute Python code in sandboxed env.

## Parameters
- `code` (string, required): Python code to execute
- `timeout` (integer, optional): timeout in seconds (default: 30)
- `packages` (array, optional): pip packages to install before running

## Returns
```json
{
  "stdout": "Hello world\n",
  "stderr": "",
  "return_value": null,
  "exit_code": 0
}
```
