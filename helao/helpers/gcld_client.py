import datetime
from enum import Enum
from typing import List, Optional, Dict
from uuid import UUID

import httpx
from pydantic import BaseModel, BaseSettings


# initialize the client with the settings
class ClientSettings(BaseSettings):
    """
    Settings model for the client.

    Attributes:
        BASE_URL (str): The base URL of the API.
        API_KEY (str): The API key for authentication.
    """

    BASE_URL: Optional[str]
    API_KEY: Optional[str]

    class Config:
        env_file = ".env"


settings = ClientSettings()


class Status(str, Enum):
    """
    Enum representing the status of a data request.
    """

    pending = "pending"
    acknowledged = "acknowledged"
    rejected = "rejected"
    completed = "completed"


class BaseDataRequestModel(BaseModel):
    """
    Base model for a DataRequest.

    Attributes:
        id (UUID): Unique identifier for the data request.
        status (Status): The current status of the data request.
        composition (dict): Data composition.
        score (Optional[float]): Score associated with the data request.
        sample_label (Optional[str]): Sample label.
        analysis (Optional[dict]): Analysis data.
    """

    status: Status
    composition: dict
    score: Optional[float]
    sample_label: Optional[str]
    analysis: Optional[dict]


class ReadDataRequest(BaseDataRequestModel):
    """
    Model for reading DataRequests.
    Used to differentiate the models if any additional fields are required for reading.
    """

    id: UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime


class CreateDataRequestModel(BaseModel):
    """
    Model for creating DataRequests.
    """

    composition: Dict[str, float]
    score: Optional[float]
    sample_label: Optional[str]
    analysis: Optional[dict]


class UpdateDataRequestModel(BaseModel):
    """
    Model for updating DataRequests.

    Attributes:
        id (UUID): Unique identifier for the data request.
        sample_label (Optional[str]): Updated sample label.
        score (Optional[float]): Updated score.
        composition (Optional[dict]): Updated composition.
    """

    id: UUID
    sample_label: Optional[str]
    score: Optional[float]
    composition: Optional[dict]


class DataRequestsClient:
    """
    Client to interact with the DataRequests API.

    Usage:
    with DataRequestsClient(settings=settings) as client:
        client.create_data_request(some_data)
    """

    def __init__(self, base_url: Optional[None] = None, api_key: Optional[None] = None):
        """
        Initialize the client with the given settings.

        Parameters:
            settings (ClientSettings): The client settings containing API base URL and API key.
        """
        self.base_url = base_url or settings.BASE_URL
        self.api_key = api_key or settings.API_KEY
        self.client = None

    def __enter__(self):
        """
        Context manager enter method. Initializes the httpx client.
        """
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"x-api-key": self.api_key},
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit method. Closes the httpx client.
        """
        self.close()

    def _ensure_client_open(self):
        """
        Private helper method to ensure that the client is open before making a request.
        Raises a RuntimeError if the client is not open.
        """
        if self.client is None:
            raise RuntimeError(
                "Client is not open. Ensure you're using this within a 'with' context or have manually opened the client."
            )

    def create_data_request(self, item: CreateDataRequestModel) -> ReadDataRequest:
        """
        Create a new data request.

        Parameters:
            item (CreateDataRequestModel): Data request details to be created.

        Returns:
            ReadDataRequest: Details of the created data request.
        """
        self._ensure_client_open()
        response = self.client.post("/data-requests/", json=item.dict())
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def update_data_request(self, item: UpdateDataRequestModel) -> ReadDataRequest:
        """
        Update an existing data request.

        Parameters:
            item (UpdateDataRequestModel): Data request details to be updated.

        Returns:
            ReadDataRequest: Details of the updated data request.
        """
        self._ensure_client_open()
        # convert UUID to string
        payload = item.dict()
        payload["id"] = str(payload["id"])
        response = self.client.put("/data-requests/", json=payload)
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def read_data_request(self, data_request_id: UUID) -> ReadDataRequest:
        """
        Retrieve details of a specific data request by its ID.

        Parameters:
            data_request_id (UUID): Unique identifier of the data request.

        Returns:
            ReadDataRequest: Details of the retrieved data request.
        """
        self._ensure_client_open()
        response = self.client.get(f"/data-requests/id/{data_request_id}")
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def delete_data_request(self, data_request_id: UUID):
        """
        Delete a specific data request by its ID.

        Parameters:
            data_request_id (UUID): Unique identifier of the data request to be deleted.

        Returns:
            None
        """
        self._ensure_client_open()
        response = self.client.delete(f"/data-requests/id/{data_request_id}")
        response.raise_for_status()

    def acknowledge_data_request(self, data_request_id: str) -> ReadDataRequest:
        """
        Acknowledge a data request.

        Parameters:
            data_request_id (str): Identifier of the data request to be acknowledged.

        Returns:
            ReadDataRequest: Details of the acknowledged data request.
        """
        self._ensure_client_open()
        response = self.client.post(f"/data-requests/acknowledge/{data_request_id}")
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def set_status(self, status: Status, data_request_id: str) -> ReadDataRequest:
        """
        Set the status for a specific data request.

        Parameters:
            status (Status): The new status to be set.
            data_request_id (str): Identifier of the data request to be updated.

        Returns:
            ReadDataRequest: Details of the data request with the updated status.
        """
        self._ensure_client_open()
        response = self.client.post(f"/data-requests/status/{status}/{data_request_id}")
        response.raise_for_status()
        return ReadDataRequest(**response.json())

    def read_data_requests(
        self, status: Optional[Status] = None
    ) -> List[ReadDataRequest]:
        """
        Retrieve a list of data requests. Optionally, filter by status.

        Parameters:
            status (Optional[Status]): The status to filter by. If not provided, retrieves all data requests.

        Returns:
            List[ReadDataRequest]: List of retrieved data requests.
        """
        self._ensure_client_open()
        params = {"status": status} if status else {}
        response = self.client.get("/data-requests/", params=params)
        response.raise_for_status()
        return [ReadDataRequest(**item) for item in response.json()]

    def close(self):
        """
        Close the client connection.
        """
        if self.client:
            self.client.close()