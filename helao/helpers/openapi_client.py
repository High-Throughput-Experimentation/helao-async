import httpx
import json
from urllib.parse import urljoin


class OpenAPIClient:
    """
    A client for interacting with an API described by an OpenAPI (JSON) specification.
    Dynamically creates methods for GET and POST operations based on the 'operationId'.
    """

    def __init__(self, openapi_json_url: str):
        """
        Initializes the OpenAPIClient.

        Args:
            openapi_json_url: The URL to the openapi.json file.
        """
        self.openapi_json_url = openapi_json_url
        self._client = None

        # Derive a base URL from the openapi_json_url. This serves as the base for resolving
        # relative server URLs specified in the OpenAPI spec, or as the direct API base
        # if no 'servers' are specified. It's the directory containing openapi.json.
        self.derived_base_url = urljoin(self.openapi_json_url, ".")
        if not self.derived_base_url.endswith("/"):
            self.derived_base_url += "/"

        try:
            self._client = httpx.Client()
            response = self._client.get(self.openapi_json_url)
            response.raise_for_status()
            self.spec = response.json()
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

    def _get_api_server_base_url(self) -> str:
        """
        Determines the absolute base URL for API calls.
        It prioritizes the 'servers' array in the OpenAPI spec.
        If a server URL is relative, it's resolved against the derived_base_url.
        If 'servers' is not found or empty, it uses the derived_base_url,
        or resolves "/" against derived_base_url if spec implies default server.
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

    def _create_methods(self):
        """
        Dynamically creates methods on the client instance for each GET or POST operation
        defined in the OpenAPI specification.
        """
        if "paths" not in self.spec:
            return

        api_call_base_url = self._get_api_server_base_url()

        for path_template, path_item_spec in self.spec["paths"].items():
            for http_method_type in ["get", "post"]:
                if http_method_type in path_item_spec:
                    operation_spec = path_item_spec[http_method_type]
                    operation_id = operation_spec.get("operationId")

                    if not operation_id:
                        # print(f"Warning: Skipping {http_method_type.upper()} operation for path {path_template} due to missing operationId.")
                        continue

                    parameters_spec_list = operation_spec.get("parameters", [])
                    # Get requestBody spec only if it's a POST request
                    current_req_body_spec = (
                        operation_spec.get("requestBody", {})
                        if http_method_type == "post"
                        else None
                    )

                    def _api_method_factory(
                        op_id,
                        current_http_method,
                        current_path_template,
                        current_params_spec,
                        req_body_spec,
                        base_url_for_calls,
                        op_details,
                    ):

                        def dynamic_method(self_instance, **kwargs):
                            """Dynamically generated API method."""
                            resolved_path_template = current_path_template
                            query_params = {}
                            request_body_data = {}

                            # Process path and query parameters
                            for param_spec in current_params_spec:
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
                                        resolved_path_template = (
                                            resolved_path_template.replace(
                                                f"{{{param_name}}}", str(param_value)
                                            )
                                        )
                                    elif param_in == "query":
                                        query_params[param_name] = param_value

                            # Process request body for POST requests
                            if current_http_method == "post" and req_body_spec:
                                if (
                                    req_body_spec.get("required", False)
                                    and "request_body" not in kwargs
                                ):
                                    raise ValueError(
                                        f"Missing required 'request_body' for POST operation '{op_id}'."
                                    )
                                request_body_data = kwargs.get("request_body", {})

                            relative_path_for_join = resolved_path_template.lstrip("/")
                            full_url = urljoin(
                                base_url_for_calls, relative_path_for_join
                            )

                            try:
                                if current_http_method == "get":
                                    response = self_instance._client.get(
                                        full_url, params=query_params
                                    )
                                elif current_http_method == "post":
                                    response = self_instance._client.post(
                                        full_url,
                                        params=query_params,
                                        json=request_body_data,
                                    )
                                else:
                                    raise NotImplementedError(
                                        f"HTTP method {current_http_method} not supported by client."
                                    )

                                response.raise_for_status()
                                content_type = response.headers.get("content-type", "")
                                if "application/json" in content_type:
                                    try:
                                        return response.json()
                                    except (
                                        json.JSONDecodeError
                                    ):  # Handle empty or invalid JSON response
                                        return (
                                            response.text
                                        )  # Fallback to text if JSON parsing fails
                                return response.text
                            except httpx.HTTPStatusError as e:
                                error_message = f"API call to '{op_id}' ({e.request.method} {e.request.url}) failed: {e.response.status_code}"
                                try:
                                    error_details = e.response.json()
                                    error_message += f" - Details: {error_details}"
                                except json.JSONDecodeError:
                                    error_message += (
                                        f" - Response: {e.response.text[:200]}"
                                    )
                                raise RuntimeError(error_message) from e
                            except httpx.RequestError as e:
                                raise RuntimeError(
                                    f"Request failed for operation '{op_id}' to {e.request.url}: {e}"
                                )

                        # Generate docstring
                        docstring_parts = []
                        if "summary" in op_details:
                            docstring_parts.append(op_details["summary"])
                        if "description" in op_details:
                            docstring_parts.append(f"\n{op_details['description']}")

                        param_docs_list = []
                        for param_spec in current_params_spec:
                            p_name, p_schema = param_spec["name"], param_spec.get(
                                "schema", {}
                            )
                            p_type = p_schema.get("type", "any") + (
                                f" ({p_schema['format']})"
                                if "format" in p_schema
                                else ""
                            )
                            p_desc = param_spec.get("description", "").split("\n")[0]
                            p_req = (
                                "required"
                                if param_spec.get("required", False)
                                else "optional"
                            )
                            param_docs_list.append(
                                f"    {p_name} ({p_type}, {p_req}): {p_desc}"
                            )

                        if current_http_method == "post" and req_body_spec:
                            rb_desc = req_body_spec.get(
                                "description", "Request body content."
                            ).split("\n")[0]
                            rb_req = (
                                "required"
                                if req_body_spec.get("required", False)
                                else "optional"
                            )
                            rb_type = "any"
                            if (
                                "content" in req_body_spec
                                and "application/json" in req_body_spec["content"]
                            ):
                                rb_schema = req_body_spec["content"][
                                    "application/json"
                                ].get("schema", {})
                                if "$ref" in rb_schema:
                                    rb_type = (
                                        f"Schema({rb_schema['$ref'].split('/')[-1]})"
                                    )
                                else:
                                    rb_type = rb_schema.get("type", "object")
                            param_docs_list.append(
                                f"    request_body ({rb_type}, {rb_req}): {rb_desc}"
                            )

                        docstring_parts.append(
                            "\n\nArgs:\n"
                            + (
                                "\n".join(param_docs_list)
                                if param_docs_list
                                else "    None"
                            )
                        )

                        if "responses" in op_details:
                            success_code = (
                                "201" if current_http_method == "post" else "200"
                            )
                            success_resp = op_details["responses"].get(
                                success_code,
                                op_details["responses"].get(
                                    str(int(success_code) + 0), {}
                                ),
                            )  # check 200 or 201
                            if not success_resp:  # fallback to any 2xx
                                for code, resp_details_loop in op_details[
                                    "responses"
                                ].items():
                                    if code.startswith("2"):
                                        success_resp = resp_details_loop
                                        break
                            if success_resp and "description" in success_resp:
                                docstring_parts.append(
                                    f"\n\nReturns:\n    {success_resp['description']}"
                                )

                        dynamic_method.__doc__ = (
                            "\n".join(docstring_parts).strip()
                            or f"Dynamically generated {current_http_method.upper()} method for operationId '{op_id}'."
                        )
                        dynamic_method.__name__ = op_id
                        return dynamic_method

                    method_function = _api_method_factory(
                        op_id=operation_id,
                        current_http_method=http_method_type,
                        current_path_template=path_template,
                        current_params_spec=parameters_spec_list,
                        req_body_spec=current_req_body_spec,
                        base_url_for_calls=api_call_base_url,
                        op_details=operation_spec,
                    )

                    method_name = operation_spec.get(
                        "summary", operation_id.lower()
                    ).lower().replace(" ", "_")
                    setattr(
                        self, method_name, method_function.__get__(self, self.__class__)
                    )

    def close(self):
        """
        Closes the underlying httpx client.
        It's good practice to call this when the client is no longer needed,
        or use the client as a context manager.
        """
        if hasattr(self, "_client") and self._client and not self._client.is_closed:
            self._client.close()

    def __enter__(self):
        """Enter the runtime context related to this object."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context related to this object."""
        self.close()
