# Third-party assets & adapted code

Parts of `diagram_mcp` are adapted from the community **drawio-skill** project
(https://github.com/Agents365-ai/drawio-skill, MIT — Copyright (c) 2026
Agents365-ai). The following modules and data files originate there and are
redistributed under their respective licenses:

| File in this repo | Source | License |
|---|---|---|
| `aiicons.py` | drawio-skill `scripts/aiicons.py` | MIT |
| `shapesearch.py` | drawio-skill `scripts/shapesearch.py` | MIT |
| `validate_drawio.py` | drawio-skill `scripts/validate.py` | MIT |
| `codevis/pyimports.py`, `codevis/pyclasses.py` | drawio-skill `scripts/pyimports.py`, `scripts/pyclasses.py` | MIT |
| `data/lobe-icons.json` | [lobehub/lobe-icons](https://github.com/lobehub/lobe-icons) manifest | MIT |
| `data/shape-index.json.gz` | [jgraph/drawio-mcp](https://github.com/jgraph/drawio-mcp) shape index | Apache-2.0 (see `SHAPE-INDEX-NOTICE.md`) |

`aiicons.py` additionally resolves brand logos at runtime from:

- **lobe-icons** (https://github.com/lobehub/lobe-icons) — MIT
- **simple-icons** (https://github.com/simple-icons/simple-icons) — CC0-1.0
  (fallback for RAG/LLM data stores not in lobe-icons)

The MIT-licensed sources above permit reuse provided this notice and the
copyright/permission notice are retained. The Apache-2.0 shape index requires
the accompanying `SHAPE-INDEX-NOTICE.md`.
