"""Native declarative layout engine ported from drawio-ai-kit (Node).

Computes every x/y/w/h from a declared node tree (flexbox-style measure/place),
emits ground-truth mxgraph.aws4 stencils, and routes edges with hard obstacle
avoidance — deterministic, no Graphviz. See prettygraph/native/README notes and
the plan `concurrent-wishing-avalanche.md`.
"""

from .theme import THEME, stage_fill, stage_stroke  # noqa: F401
from .layout_engine import (  # noqa: F401
    icon,
    box,
    group,
    frame,
    phantom,
    grid,
    render_tree,
)
from .builder import Diagram  # noqa: F401

# Typed-diagram foundation: importing these registers their kind into
# registry.RENDERERS as a side effect (see each module's `_register()`).
# Side-effect-only import — no names re-exported, since callers reach the
# renderer through the registry (topology.build_tree), never this module.
from . import sequence as _sequence  # noqa: F401
from . import erd as _erd  # noqa: F401
from . import state_machine as _state_machine  # noqa: F401
