# File Zip

Create ZIP archive from files or dir.

## Parameters
- `source` (string or array, required): Path(s) to compress
- `output` (string, required): Output ZIP file path
- `base_dir` (string, optional): Strip prefix from paths inside archive

## Returns
```json
{ "output": "/tmp/export.zip", "files_added": 15, "size_bytes": 40960 }
```
