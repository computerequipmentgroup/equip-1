# Equip-1 mechanical CAD

FreeCAD (`.FCStd`) is the source of truth. Each version lives in its own frozen folder under
`designs/`. Do not edit a published version; create the next one from its saved file. The STEP
files in `hw/` (`shell-top`, `shell-bot`, `buttons`, `screencover`) are reference inputs, not source.

## Versions

- **V0.1.0** — parametric rebuild of the reference enclosure (resin print, external USB-C). [README](designs/V0.1.0/README.md) · [validation](designs/V0.1.0/reports/validation.md)

## Running scripts

Headless: `FreeCADCmd designs/V0.1.0/scripts/verify.py`. In the FreeCAD GUI Python console:

```python
from pathlib import Path
root = Path('/path/to/equip-1/hw/cad/designs/V0.1.0')
s = root / 'scripts/verify.py'
exec(compile(s.read_text(), str(s), 'exec'), {'__file__': str(s), '__name__': '__main__'})
```

Scripts open their own copy of the document and never touch other open documents. Only
`build.py` saves.
