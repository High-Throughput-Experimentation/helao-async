"""Lightweight dynamic HTTP clients driven by an OpenAPI JSON spec.

``OpenAPIClient`` (sync) and ``AsyncOpenAPIClient`` (async) fetch an
``openapi.json`` document at construction time and, for each GET/POST
operation, attach an instance method whose name is derived from the
operation's ``summary`` (or its ``operationId``). Path, query and request
body parameters declared by the spec are taken as keyword arguments.

Both clients share ``_BaseOpenAPIClient``, which owns spec fetching, server
base-URL resolution, request building, response/error handling, docstring
generation and the per-operation method binding. Each subclass only supplies
the transport-specific pieces: how the spec is fetched and how a single
request is dispatched (synchronously vs. via a short-lived ``AsyncClient``).
"""

import httpx
import json
from urllib.parse import urljoin, quote


class _BaseOpenAPIClient:
    """Shared machinery for the sync and async OpenAPI clients.

    Subclasses must implement ``_fetch_spec`` (return the parsed spec dict)
    and ``_make_method`` (return a callable taking ``(self_instance, **kwargs)``
    that performs a single API call).
    """

    def __init__(self, openapi_json_url: str, api_key: str = ""):
        """Fetch the OpenAPI spec and bind dynamic methods.

        Args:
            openapi_json_url: URL of the ``openapi.json`` document.
            api_key: Optional value sent as the ``X-Api-Key`` header.

        Raises:
            RuntimeError: If the spec cannot be fetched or parsed.
        """
        self.openapi_json_url = openapi_json_url
        self.api_key = api_key
        self.headers = {"X-Api-Key": self.api_key} if self.api_key else None
        self._client = None

        # Derive a base URL from the openapi_json_url. This serves as the base for resolving
        # relative server URLs specified in the OpenAPI spec, or as the direct API base
        # if no 'servers' are specified. It's the directory containing openapi.json.
        self.derived_base_url = urljoin(self.openapi_json_url, ".")
        if not self.derived_base_url.endswith("/"):
            self.derived_base_url += "/"

        try:
            self.spec = self._fetch_spec()
        except httpx.RequestError as e:
            self.close()
            raise RuntimeError(
                f"Failed to fetch OpenAPI spec from {self.openapi_json_url}: {e}"
            )
        except json.JSONDecodeError as e:
            self.close()
            raise RuntimeError(
                f"Failed to parse OpenAPI spec JSON from {self.openapi_json_url}: {e}"
            )
        except Exception as e:
            self.close()
            raise e

        self._create_methods()

    # --- transport-specific hooks ------------------------------------------

    def _fetch_spec(self) -> dict:
        """Download and parse the OpenAPI spec. Implemented by subclasses."""
        raise NotImplementedError

    def _make_method(
        self, op_id, http_method, path_template, params_spec, req_body_spec, base_url, op_details
    ):
        """Return a ``(self_instance, **kwargs)`` callable. Implemented by subclasses."""
        raise NotImplementedError

    # --- shared logic -------------------------------------------------------

    def _get_api_server_base_url(self) -> str:
        """Return the absolute base URL to use for API calls.

        Honours the spec's ``servers`` array, resolving relative entries
        against the URL containing ``openapi.json``. When ``servers`` is
        omitted entirely, the OpenAPI default of ``/`` is applied.
        """
        final_server_url = self.derived_base_url  # Default to derived_base_url

        if "servers" in self.spec and self.spec["servers"]:
            server_url_from_spec = self.spec["servers"][0]["url"]
            # Resolve the server_url_from_spec against derived_base_url.
            # This handles cases where server_url_from_spec is relative (e.g., "/v1", "v1")
            # or absolute. If server_url_from_spec is absolute, urljoin effectively returns it.
            final_server_url = urljoin(self.derived_base_url, server_url_from_spec)
        elif (
            "servers" not in self.spec
        ):  # OpenAPI spec implies default server URL of "/" if not present
            final_server_url = urljoin(self.derived_base_url, "/")

        if not final_server_url.endswith("/"):
            final_server_url += "/"
        return final_server_url

    def _build_request(
        self, op_id, http_method, path_template, params_spec, req_body_spec, base_url, kwargs
    ):
        """Resolve path/query params and request body into call arguments.

        Returns:
            (full_url, quoted_query_params, request_body_data)

        Raises:
            ValueError: If a required path/query parameter or request body is missing.
        """
        resolved_path_template = path_template
        query_params = {}
        request_body_data = {}

        # Process path and query parameters
        for param_spec in params_spec:
            param_name = param_spec["name"]
            param_in = param_spec["in"]
            is_required = param_spec.get("required", False)

            if is_required and param_name not in kwargs:
                raise ValueError(
                    f"Missing required parameter '{param_name}' for operation '{op_id}'."
                )

            param_value = kwargs.get(param_name)

            if param_value is not None:
                if param_in == "path":
                    resolved_path_template = resolved_path_template.replace(
                        f"{{{param_name}}}", quote(str(param_value), safe="")
                    )
                elif param_in == "query":
                    query_params[param_name] = param_value

        # Process request body for POST requests
        if http_method == "post" and req_body_spec:
            if req_body_spec.get("required", False) and "request_body" not in kwargs:
                raise ValueError(
                    f"Missing required 'request_body' for POST operation '{op_id}'."
                )
            request_body_data = kwargs.get("request_body", {})

        relative_path_for_join = resolved_path_template.lstrip("/")
        full_url = urljoin(base_url, relative_path_for_join)

        quoted_query_params = {}
        for _key, value in query_params.items():
            key = quote(_key, safe="") if isinstance(_key, str) else _key
            quoted_query_params[key] = (
                quote(value, safe="") if isinstance(value, str) else value
            )

        return full_url, quoted_query_params, request_body_data

    def _handle_response(self, op_id, response):
        """Raise for HTTP errors and decode a successful response.

        Returns parsed JSON when the content type is JSON (falling back to
        text on decode failure), otherwise the raw text.

        Raises:
            RuntimeError: On any 4xx/5xx response, wrapping the status and body.
        """
        try:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    return response.json()
                except json.JSONDecodeError:  # Handle empty or invalid JSON response
                    return response.text  # Fallback to text if JSON parsing fails
            return response.text
        except httpx.HTTPStatusError as e:
            error_message = f"API call to '{op_id}' ({e.request.method} {e.request.url}) failed: {e.response.status_code}"
            try:
                error_details = e.response.json()
                error_message += f" - Details: {error_details}"
            except json.JSONDecodeError:
                error_message += f" - Response: {e.response.text[:200]}"
            raise RuntimeError(error_message) from e

    def _build_docstring(self, op_id, http_method, params_spec, req_body_spec, op_details):
        """Build a method docstring from the operation's summary/params/responses."""
        docstring_parts = []
        if "summary" in op_details:
            docstring_parts.append(op_details["summary"])
        if "description" in op_details:
            docstring_parts.append(f"\n{op_details['description']}")

        param_docs_list = []
        for param_spec in params_spec:
            p_name, p_schema = param_spec["name"], param_spec.get("schema", {})
            p_type = p_schema.get("type", "any") + (
                f" ({p_schema['format']})" if "format" in p_schema else ""
            )
            p_desc = param_spec.get("description", "").split("\n")[0]
            p_req = "required" if param_spec.get("required", False) else "optional"
            param_docs_list.append(f"    {p_name} ({p_type}, {p_req}): {p_desc}")

        if http_method == "post" and req_body_spec:
            rb_desc = req_body_spec.get(
                "description", "Request body content."
            ).split("\n")[0]
            rb_req = "required" if req_body_spec.get("required", False) else "optional"
            rb_type = "any"
            if (
                "content" in req_body_spec
                and "application/json" in req_body_spec["content"]
            ):
                rb_schema = req_body_spec["content"]["application/json"].get(
                    "schema", {}
                )
                if "$ref" in rb_schema:
                    rb_type = f"Schema({rb_schema['$ref'].split('/')[-1]})"
                else:
                    rb_type = rb_schema.get("type", "object")
            param_docs_list.append(f"    request_body ({rb_type}, {rb_req}): {rb_desc}")

        docstring_parts.append(
            "\n\nArgs:\n"
            + ("\n".join(param_docs_list) if param_docs_list else "    None")
        )

        if "responses" in op_details:
            success_code = "201" if http_method == "post" else "200"
            success_resp = op_details["responses"].get(success_code, {})
            if not success_resp:  # fallback to any 2xx
                for code, resp_details_loop in op_details["responses"].items():
                    if code.startswith("2"):
                        success_resp = resp_details_loop
                        break
            if success_resp and "description" in success_resp:
                docstring_parts.append(
                    f"\n\nReturns:\n    {success_resp['description']}"
                )

        return (
            "\n".join(docstring_parts).strip()
            or f"Dynamically generated {http_method.upper()} method for operationId '{op_id}'."
        )

    def _create_methods(self):
        """Bind one instance method per GET/POST operation in the spec.

        Each generated method's name is derived from the operation's
        ``summary`` (lower-cased with spaces replaced) or ``operationId``.
        """
        if "paths" not in self.spec:
            return

        api_call_base_url = self._get_api_server_base_url()

        for path_template, path_item_spec in self.spec["paths"].items():
            for http_method_type in ["get", "post"]:
                if http_method_type not in path_item_spec:
                    continue

                operation_spec = path_item_spec[http_method_type]
                operation_id = operation_spec.get("operationId")
                if not operation_id:
                    continue

                parameters_spec_list = operation_spec.get("parameters", [])
                # Get requestBody spec only if it's a POST request
                current_req_body_spec = (
                    operation_spec.get("requestBody", {})
                    if http_method_type == "post"
                    else None
                )

                method_function = self._make_method(
                    operation_id,
                    http_method_type,
                    path_template,
                    parameters_spec_list,
                    current_req_body_spec,
                    api_call_base_url,
                    operation_spec,
                )
                method_function.__name__ = operation_id
                method_function.__doc__ = self._build_docstring(
                    operation_id,
                    http_method_type,
                    parameters_spec_list,
                    current_req_body_spec,
                    operation_spec,
                )

                method_name = (
                    operation_spec.get("summary", operation_id.lower())
                    .lower()
                    .replace(" ", "_")
                )
                setattr(
                    self, method_name, method_function.__get__(self, self.__class__)
                )

    def close(self):
        """Close the underlying ``httpx.Client`` if one is held open."""
        if hasattr(self, "_client") and self._client and not self._client.is_closed:
            self._client.close()

    def __enter__(self):
        """Return ``self`` for use as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close any underlying ``httpx.Client``."""
        self.close()


class OpenAPIClient(_BaseOpenAPIClient):
    """Synchronous httpx client that mirrors an OpenAPI spec's operations.

    On construction the spec is downloaded and an instance method is
    generated for every GET/POST operation. The generated methods accept
    path/query parameters and an optional ``request_body`` keyword. A single
    ``httpx.Client`` is held open for the lifetime of this object.
    """

    def _fetch_spec(self) -> dict:
        self._client = httpx.Client(headers=self.headers, timeout=30.0)
        response = self._client.get(self.openapi_json_url)
        response.raise_for_status()
        return response.json()

    def _make_method(
        self, op_id, http_method, path_template, params_spec, req_body_spec, base_url, op_details
    ):
        def dynamic_method(self_instance, **kwargs):
            """Generated method that dispatches a single API call."""
            full_url, query_params, request_body_data = self_instance._build_request(
                op_id, http_method, path_template, params_spec, req_body_spec, base_url, kwargs
            )
            try:
                if http_method == "get":
                    response = self_instance._client.get(full_url, params=query_params)
                else:
                    response = self_instance._client.post(
                        full_url, params=query_params, json=request_body_data
                    )
            except httpx.RequestError as e:
                raise RuntimeError(
                    f"Request failed for operation '{op_id}' to {e.request.url}: {e}"
                )
            return self_instance._handle_response(op_id, response)

        return dynamic_method


class AsyncOpenAPIClient(_BaseOpenAPIClient):
    """Async variant of ``OpenAPIClient`` whose generated methods are coroutines.

    A short-lived ``httpx.AsyncClient`` is opened per call rather than held
    open for the lifetime of this object. The spec is still fetched
    synchronously at construction time.
    """

    def _fetch_spec(self) -> dict:
        with httpx.Client(headers=self.headers, timeout=30.0) as client:
            response = client.get(self.openapi_json_url)
        response.raise_for_status()
        return response.json()

    def _make_method(
        self, op_id, http_method, path_template, params_spec, req_body_spec, base_url, op_details
    ):
        async def dynamic_method(self_instance, **kwargs):
            """Generated async method that dispatches a single API call."""
            full_url, query_params, request_body_data = self_instance._build_request(
                op_id, http_method, path_template, params_spec, req_body_spec, base_url, kwargs
            )
            try:
                async with httpx.AsyncClient(
                    headers=self_instance.headers, timeout=30
                ) as client:
                    if http_method == "get":
                        response = await client.get(full_url, params=query_params)
                    else:
                        response = await client.post(
                            full_url, params=query_params, json=request_body_data
                        )
            except httpx.RequestError as e:
                raise RuntimeError(
                    f"Request failed for operation '{op_id}' to {e.request.url}: {e}"
                )
            return self_instance._handle_response(op_id, response)

        return dynamic_method
