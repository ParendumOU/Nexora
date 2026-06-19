# Browser Screenshot

Screenshot web page via headless browser.

## Parameters
- `url` (string, required): URL to screenshot
- `full_page` (boolean, optional): Capture full scrollable page (default: false)
- `selector` (string, optional): Screenshot specific element by CSS selector
- `width` (integer, optional): Viewport width px (default: 1280)
- `height` (integer, optional): Viewport height px (default: 720)

## Returns
```json
{
  "image_base64": "iVBORw0KGgo...",
  "width": 1280,
  "height": 720
}
```
