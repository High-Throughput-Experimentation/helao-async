"""HTTP client for the GCLD data-requests API.

Defines the pydantic settings and request/response models used to read,
create, update, and acknowledge ``DataRequest`` objects, and the
``DataRequestsClient`` wrapper around ``httpx`` that exposes them.
"""

import os
import datetime
from enum import Enum
from typing import List, Optional, Dict
from uuid import UUID

import httpx
from pydantic import BaseModel, BaseSettings


# initialize the client with the settings
class ClientSettings(BaseSettings):
    """Credentials and target URL for the data-requests API client.

    Attributes:
        BASE_URL: Base URL of the API.
        API_KEY: API key sent as the ``x-api-key`` header.
    """

    BASE_URL: Optional[str] = None
    API_KEY: Optional[str] = None

    class Config:
        env_file = os.environ.get("DATA_REQ_CRED", ".env")


settings = ClientSettings()


class Status(str, Enum):
    """Lifecycle status of a data request."""

    pending = "pending"
    acknowledged = "acknowledged"
    rejected = "rejected"
    completed = "completed"


class BaseDataRequestModel(BaseModel):
    """Common fields shared by read/write data-request models.

    Attributes:
        status: Current status of the data request.
        composition: Composition payload associated with the request.
        score: Optional score associated with the request.
        sample_label: Optional sample label.
        analysis: Optional analysis dictionary.
    """

    status: Status
    composition: dict
    score: Optional[float] = None
    sample_label: Optional[str] = None
    analysis: Optional[dict] = None


class ReadDataRequest(BaseDataRequestModel):
    """Read-side representation of a data request returned by the API.

    Attributes:
        id: Server-assigned unique identifier.
        created_at: Timestamp when the request was created.
        updated_at: Timestamp of the last update.
    """

    id: UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime


class CreateDataRequestModel(BaseModel):
    """Payload accepted by the API when creating a new data request.

    Attributes:
        composition: Mapping of element symbols to fractional amounts.
        score: Optional initial score.
        sample_label: Optional sample label.
        analysis: Optional analysis dictionary.
    """

    composition: Dict[str, float]
    score: Optional[float] = None
    sample_label: Optional[str] = None
    analysis: Optional[dict] = None


class UpdateDataRequestModel(BaseModel):
    """Payload accepted by the API when updating an existing data request.

    Attributes:
        id: Identifier of the request to update.
        sample_label: Updated sample label, if any.
        score: Updated score, if any.
        composition: Updated composition, if any.
    """

    id: UUID
    sample_label: Optional[str] = None
    score: Optional[float] = None
    composition: Optional[dict] = None


class DataRequestsClient:
    """Synchronous httpx-backed client for the DataRequests REST API.

    Intended to be used as a context manager so the underlying ``httpx.Client``
    is opened on ``__enter__`` and released on ``__exit__``.
    """

    def __init__(self, base_url: Optional[None] = None, api_key: Optional[None] = None):
        """Store the base URL and API key for later use.

        Args:
            base_url: Overrides ``settings.BASE_URL`` if provided.
            api_key: Overrides ``settings.API_KEY`` if provided.
        """
        self.base_url = base_url or settings.BASE_URL
        self.api_key = api_key or settings.API_KEY
        self.client = None

    def __enter__(self) -> "DataRequestsClient":
        """Open the underlying ``httpx.Client`` and return self."""
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"x-api-key": self.api_key},
            timeout=30.0,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the underlying ``httpx.Client``."""
        self.close()

    def _ensure_client_open(self):
        """Raise ``RuntimeError`` if the underlying client has not been opened."""
        if self.client is None:
            raise RuntimeError(
                "Client is not open. Ensure you're using this within a 'with' context or have manually opened the client."
            )

    def create_data_request(self, item: CreateDataRequestModel) -> ReadDataRequest:
        """Create a new data request.

        Args:
            item: Payload describing the request to create.

        Returns:
            The newly created data request as returned by the API.
        """
        self._ensure_client_open()
        response = self.client.post("/data-requests/", json=item.model_dump())
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def update_data_request(self, item: UpdateDataRequestModel) -> ReadDataRequest:
        """Update an existing data request.

        Args:
            item: Payload describing the fields to update.

        Returns:
            The updated data request as returned by the API.
        """
        self._ensure_client_open()
        # convert UUID to string
        payload = item.model_dump()
        payload["id"] = str(payload["id"])
        response = self.client.put("/data-requests/", json=payload)
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def read_data_request(self, data_request_id: UUID) -> ReadDataRequest:
        """Retrieve a single data request by id.

        Args:
            data_request_id: Identifier of the data request to fetch.

        Returns:
            The requested data request.
        """
        self._ensure_client_open()
        response = self.client.get(f"/data-requests/id/{data_request_id}")
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def delete_data_request(self, data_request_id: UUID):
        """Delete a data request by id.

        Args:
            data_request_id: Identifier of the data request to delete.
        """
        self._ensure_client_open()
        response = self.client.delete(f"/data-requests/id/{data_request_id}")
        response.raise_for_status()

    def acknowledge_data_request(self, data_request_id: str) -> ReadDataRequest:
        """Mark a data request as acknowledged.

        Args:
            data_request_id: Identifier of the data request to acknowledge.

        Returns:
            The acknowledged data request as returned by the API.
        """
        self._ensure_client_open()
        response = self.client.post(f"/data-requests/acknowledge/{data_request_id}")
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def set_status(self, status: Status, data_request_id: str) -> ReadDataRequest:
        """Set the status of a data request.

        Args:
            status: New status value to assign.
            data_request_id: Identifier of the data request to update.

        Returns:
            The data request with the updated status.
        """
        self._ensure_client_open()
        response = self.client.post(f"/data-requests/status/{status}/{data_request_id}")
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def read_data_requests(
        self, status: Optional[Status] = None
    ) -> List[ReadDataRequest]:
        """Retrieve all data requests, optionally filtered by status.

        Args:
            status: Optional status used to filter the result list.

        Returns:
            List of data requests matching the filter (or all requests when
            ``status`` is ``None``).
        """
        self._ensure_client_open()
        params = {"status": status} if status else {}
        response = self.client.get("/data-requests/", params=params)
        response.raise_for_status()
        return [ReadDataRequest(**item) for item in response.json()]

    def close(self):
        """Close the underlying ``httpx.Client`` if it has been opened."""
        if self.client:
            self.client.close()
