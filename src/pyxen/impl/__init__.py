"""Per-primitive implementations.

Each sub-package here corresponds to one primitive. Within a sub-package,
each module is a single implementation that exposes a ``build(config)``
function returning an instance that satisfies the primitive's interface
protocol in ``pyxen.core``.

The OpenAI Agents SDK (or any other source) is consumed as individual
imports inside the implementation modules that need it. There is no
top-level ``impl/openai`` wrapper.
"""
