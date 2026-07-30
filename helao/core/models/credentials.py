"""Credential settings loaded from a `.env` file for AWS, DB, and plate APIs."""

import urllib
from pathlib import Path
from textwrap import dedent
from typing import ClassVar

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings


class HelaoCredentials(BaseSettings):
    """Environment-backed credentials for AWS, the API DB, and plate services.

    Loads from the `.env` file passed at construction. Secret-typed fields
    keep their values out of standard `repr`/`str`.

    Attributes:
        AWS_ACCESS_KEY_ID (SecretStr): AWS access key id.
        AWS_SECRET_ACCESS_KEY (SecretStr): AWS secret access key.
        AWS_REGION (SecretStr): AWS region.
        AWS_BUCKET (SecretStr): Default S3 bucket name.
        API_USER (str): Postgres user.
        API_PASSWORD (SecretStr): Postgres password.
        API_HOST (str): Postgres host.
        API_PORT (int): Postgres port.
        API_DB (str): Postgres database name.
        API_SCHEMA (str): Postgres schema used for search_path.
        JUMPBOX_HOST (str): SSH jumpbox host.
        JUMPBOX_USER (str): SSH jumpbox user.
        JUMPBOX_KEYFILE (str): SSH private key file.
        OPENAPI_JSON (str): Path/URL of an OpenAPI JSON definition.
        PLATE_API_JSON (str): Path/URL of the plate API definition.
        PLATE_API_KEY (str): API key for the plate service.
        PLATE_API (str): Base URL for the plate service.
    """

    AWS_ACCESS_KEY_ID: SecretStr = SecretStr("")
    AWS_SECRET_ACCESS_KEY: SecretStr = SecretStr("")
    AWS_REGION: SecretStr = SecretStr("")
    AWS_BUCKET: SecretStr = SecretStr("")
    API_USER: str = "postgres"
    API_PASSWORD: SecretStr = SecretStr("")
    API_HOST: str = "localhost"
    API_PORT: int = 5432
    API_DB: str = ""
    API_SCHEMA: str = "production"
    JUMPBOX_HOST: str = ""
    JUMPBOX_USER: str = ""
    JUMPBOX_KEYFILE: str = ""
    OPENAPI_JSON: str = ""
    PLATE_API_JSON: str = ""
    PLATE_API_KEY: str = ""
    PLATE_API: str = ""

    # Keys shown when ``display(simple=True)`` and keys always rendered
    # uncommented regardless of whether they were explicitly set. Empty by
    # default; populate to opt specific fields into those views.
    _simple_params: ClassVar[set[str]] = set()
    _always_set: ClassVar[set[str]] = set()

    def __init__(self, _env_file: str | Path, **kwargs):
        """Load settings from `_env_file`.

        Args:
            _env_file: Path (string or `Path`) to the `.env` file to read.
            **kwargs: Forwarded to `BaseSettings.__init__`.
        """
        if not isinstance(_env_file, Path):
            _env_file = Path(_env_file)
        super().__init__(_env_file=_env_file, **kwargs)

    def set_api_port(self, port: int):
        """Override the API port (e.g. when tunneling)."""
        self.API_PORT = port

    @property
    def api_dsn(self) -> str:
        """Return a Postgres DSN string for the API DB with the schema set on search_path."""
        pgdsn = PostgresDsn.build(
            scheme="postgresql",
            username=self.API_USER,
            password=(
                urllib.parse.quote(self.API_PASSWORD.get_secret_value())
                if self.API_PASSWORD
                else ""
            ),
            host="127.0.0.1",
            port=self.API_PORT,
            path=self.API_DB,
        )
        pgdsn_schema = f"{pgdsn}?options=--search_path%3d{self.API_SCHEMA}"
        return pgdsn_schema

    def display(
        self,
        show_defaults: bool = False,
        show_passwords: bool = False,
        simple: bool = False,
    ) -> str:
        """Render the credentials as an MPS-style config block.

        Args:
            show_defaults: If True, include fields left at their defaults.
            show_passwords: If True, unmask `*PASSWORD*`/`*KEY*` fields.
            simple: If True, restrict the output to `_simple_params` keys.

        Returns:
            Multiline configuration text.
        """
        params = []
        for key, val in self.model_dump().items():
            if simple and key not in self._simple_params:
                continue
            if val is not None:
                str_val = (
                    f"{val.get_secret_value()}"
                    if show_passwords and ("PASSWORD" in key or "KEY" in key)
                    else val
                )
                if (
                    show_defaults or key in self.__fields_set__
                ) or key in self._always_set:
                    params.append(f"{key} = {str_val}")
                else:
                    params.append(f"# {key} = {str_val}")

        params_str = "\n".join(params)
        output = f"""# MPS Client Settings\n{params_str}"""
        return dedent(output)

    def __str__(self) -> str:
        """Return the default `display()` rendering."""
        return self.display()

    class Config:
        """Pydantic settings config: default env file location."""

        env_file = ".env"
