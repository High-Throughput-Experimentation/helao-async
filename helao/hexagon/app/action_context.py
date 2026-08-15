"""Explicit per-request action context (spec D-B1.1).

Legacy reconstructs an ``Action`` from FastAPI's resolved kwargs inside
``wrap_action_endpoint`` and stashes it in a ``ContextVar`` (``ACTION_CTX``,
``base_api.py:92``); that is why ``Base.setup_and_contain_action()`` takes no
request argument and why an action handler cannot be called in a unit test.

B1 replaces the hidden state with a parameter. A handler declares
``ctx: ActionContext`` and calls ``await ctx.begin(...)`` to open the action's
session::

    @host.action()
    async def acquire_data(ctx: ActionContext, duration: float = -1):
        session = await ctx.begin(action_abbr="WsSim")
        ...

There is deliberately **no ContextVar and no ``setup_and_contain_action`` shim**.
A shim would have to be deleted in B7 and would let modules stay unported.

The action-construction behaviour below is ported from
``base_api._build_action_from_kwargs`` and the code-identity block of
``Base._get_action`` (``base.py:385-394``). Three of its rules are load-bearing
in ways the code does not advertise, and are commented at their site.
"""

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from helao.core.version import get_filehash
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = [
    "ACTION_VERSION_ATTR",
    "DEFAULT_ACTION_VERSION",
    "ActionContext",
    "action_version",
    "build_action",
    "collect_default_params",
]

#: Attribute carrying a per-endpoint action_version set via :func:`action_version`.
#: Same spelling as legacy ``base_api.ACTION_VERSION_ATTR`` -- D-B1.2 keeps the
#: decorator's meaning, so there is no reason for the marker to differ.
ACTION_VERSION_ATTR = "__helao_action_version__"

#: Injected when an endpoint declares no version.
DEFAULT_ACTION_VERSION = 1


def action_version(version: int) -> Callable:
    """Declare the schema version for an action endpoint.

    Applied below the route decorator on an endpoint whose schema version differs
    from :data:`DEFAULT_ACTION_VERSION`. The value is injected as the endpoint's
    ``action_version`` parameter, so it appears in the request schema and on the
    recorded action exactly as an inline ``action_version: int = N`` would.

    Args:
        version: The endpoint's action schema version.

    Returns:
        A decorator that marks the function and returns it unchanged.
    """

    def decorate(func: Callable) -> Callable:
        setattr(func, ACTION_VERSION_ATTR, version)
        return func

    return decorate


def collect_default_params(sig: inspect.Signature) -> dict:
    """Return ``{name: default}`` for parameters with usable Python defaults.

    Skips ``Action``-typed parameters (handled separately), the ``ActionContext``
    parameter (supplied by the host, not by the caller, and not an action
    param), and FastAPI's parameter markers -- ``Body``/``Query``/``Path``/
    ``Depends`` -- whose "default" is a sentinel rather than the value the
    endpoint actually sees.

    Args:
        sig: Signature of the endpoint function.

    Returns:
        Mapping of parameter name to its default value.
    """
    try:
        from fastapi.params import Depends as _FastAPIDepends
        from fastapi.params import Param as _FastAPIParam

        marker_types: tuple = (_FastAPIParam, _FastAPIDepends)
    except ImportError:  # pragma: no cover - fastapi is a hard dependency
        marker_types = ()

    defaults: dict = {}
    for name, param in sig.parameters.items():
        if param.default is inspect.Parameter.empty:
            continue
        if marker_types and isinstance(param.default, marker_types):
            continue
        ann = param.annotation
        if isinstance(ann, type) and issubclass(ann, Action):
            continue
        if isinstance(ann, type) and issubclass(ann, ActionContext):
            continue
        if name == "ctx":
            continue
        defaults[name] = param.default
    return defaults


def _apply_code_identity(action: Action, endpoint_func: Optional[Callable]) -> None:
    """Stamp the action with the endpoint's code identity.

    ``action_codehash`` / ``action_codepath`` / ``action_funcname`` are written
    into every action record and are **stripped by the golden normalizer**
    (``harness/yaml_pass.py`` lists those three suffixes in
    ``DROP_KEY_SUFFIXES``). No GM diff and no route-surface diff can therefore
    see a regression here -- ``test_action_code_identity`` is what watches them.

    Args:
        action: The action being built.
        endpoint_func: The endpoint whose code identity is recorded, or None.
    """
    if endpoint_func is None:
        return
    code = getattr(endpoint_func, "__code__", None)
    if code is None:
        return
    import os

    action.action_codehash = get_filehash(code.co_filename)
    action.action_codepath = "/".join(
        code.co_filename.replace(os.getcwd(), "").strip("\\").strip("/").split(os.sep)
    )
    action.action_funcname = code.co_name


def _apply_host_context(action: Action, endpoint_func, host) -> None:
    """Apply the processing legacy does in ``Base._get_action`` (base.py:355-394).

    Ported after a golden-master run showed its absence: without the
    ``run_type is None`` branch below, a manually dispatched action never gets
    ``orchestrator = MANUAL`` and therefore never lands in ``RUNS_DIAG`` -- GM-3
    diffed as an entire missing tree. ``build_action`` originally ported only
    ``_build_action_from_kwargs`` plus the code-identity tail, and
    ``ActionSession.__init__`` happened to cover ``action_server``, so the gap
    looked closed.
    """
    from socket import gethostname

    from helao.core.models.machine import MachineModel
    from helao.core.models.sample import object_to_sample

    if host is None:
        return

    # The route's own name, not the function's, so a route registered under a
    # different path records the dispatched name.
    if endpoint_func is not None:
        try:
            urlname = host.url_path_for(endpoint_func.__name__)
            action_name = urlname.strip("/").split("/")[-1]
        except Exception:
            action_name = endpoint_func.__name__
    else:
        action_name = action.action_name or ""

    server_key = host.server.server_name
    action.action_server = MachineModel(
        server_name=server_key, machine_name=gethostname().lower()
    )
    action.action_name = action_name

    if action.action_params is not None and "fast_samples_in" in action.action_params:
        tmp_fast_samples_in = action.action_params.get("fast_samples_in", [])
        del action.action_params["fast_samples_in"]
        for sample in tmp_fast_samples_in:
            sample_obj = object_to_sample(sample)
            if not getattr(sample_obj, "action_uuid", []):
                sample_obj.action_uuid = [action.action_uuid]
            action.samples_in.append(sample_obj)

    if action.action_abbr is None:
        action.action_abbr = action.action_name

    if action.run_type is None:
        action.run_type = getattr(host, "run_type", None)
        action.orchestrator = MachineModel(
            server_name="MANUAL", machine_name=gethostname().lower()
        )


def build_action(
    kwargs: dict,
    default_params: Optional[dict] = None,
    endpoint_func: Optional[Callable] = None,
    host: Any = None,
) -> Action:
    """Build the ``Action`` for one action-endpoint invocation.

    Args:
        kwargs: Parameter name to value, as resolved by FastAPI (or by the RPC
            fast path).
        default_params: Signature defaults the caller did not supply.
        endpoint_func: The endpoint function, for code identity.

    Returns:
        The action this invocation runs under.
    """
    action: Optional[Action] = None
    seen_action_param: Optional[str] = None
    for name, val in kwargs.items():
        if isinstance(val, Action):
            if action is None:
                action = val
                seen_action_param = name
            else:
                LOGGER.error(
                    f"critical error: found another Action BaseModel under "
                    f"parameter '{name}', skipping it"
                )

    if action is None:
        if "action" in kwargs:
            # An 'action' value was supplied but did not rehydrate into an
            # Action -- a malformed envelope, worth flagging loudly.
            LOGGER.error(
                "critical error: 'action' kwarg present but is not an Action "
                "BaseModel, using blank Action."
            )
        else:
            # No envelope at all. Expected for a tags=["action"] *query*
            # endpoint (e.g. PAL 'list_new_samples') invoked over the ZMQ-RPC
            # fast path, which does not synthesize FastAPI's Body({}) default.
            # Such endpoints do not use the action machinery, so a blank Action
            # is the correct benign fallback -- debug, not error.
            LOGGER.debug(
                "no Action supplied to action-tagged endpoint; using blank Action."
            )
        action = Action()
    elif seen_action_param is not None:
        LOGGER.debug(f"found Action BaseModel under parameter '{seen_action_param}'")

    # Loose kwargs fold in, but never overwrite: the orchestrator's dispatcher
    # already resolved these, and its value is the authoritative one.
    for name, val in kwargs.items():
        if isinstance(val, Action):
            continue
        if name not in action.action_params:
            action.action_params[name] = val

    # Defaults the caller omitted. The RPC fast path does not synthesize
    # FastAPI's defaults, so without this the record would omit parameters the
    # endpoint actually ran with -- a silent artifact difference, not an error.
    for name, val in (default_params or {}).items():
        if name in kwargs or name in action.action_params:
            continue
        action.action_params[name] = val

    _apply_host_context(action, endpoint_func, host)
    _apply_code_identity(action, endpoint_func)
    return action


@dataclass
class ActionContext:
    """One action-endpoint invocation, handed to the handler as a parameter.

    Attributes:
        action: The action this request runs under.
        endpoint_func: The endpoint being invoked.
        host: The :class:`ActionHost` serving the request.
    """

    action: Action
    endpoint_func: Optional[Callable] = None
    host: Any = None
    _extra: dict = field(default_factory=dict)

    async def begin(self, **kwargs):
        """Open the action's session (the ``Active`` equivalent).

        Args:
            **kwargs: Forwarded to the host's session factory --
                ``json_data_keys``, ``action_abbr``, ``file_type``, ``hloheader``.

        Returns:
            The :class:`~helao.hexagon.app.action_session.ActionSession` now
            tracking this action.
        """
        if self.host is None:
            raise RuntimeError(
                "ActionContext.begin() requires a host; the context was built "
                "outside an ActionHost request."
            )
        return await self.host.begin_session(self.action, **kwargs)
