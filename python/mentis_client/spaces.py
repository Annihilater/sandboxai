# mentis_client/spaces.py
import logging
import time
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

import httpx
from pydantic import ValidationError

from .api import (
    Space,
    CreateSpaceRequest,
    UpdateSpaceRequest,
    Sandbox,
    CreateSandboxRequest,
    Error,
    SandboxSpec,
    SandboxStatus
)
from .error import (
    MentisError,
    MentisAPIError,
    MentisValidationError,
    MentisConnectionError,
    MentisTimeoutError,
    MentisResourceError
)

logger = logging.getLogger(__name__)


class SpaceManager:
    """Manager for space and sandbox operations"""
    
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        """Initialize the space manager
        
        Args:
            base_url: Base URL of the Mentis API
            api_key: Optional API key for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self._client = self._create_client()
        
    def _create_client(self) -> httpx.Client:
        """Create an HTTP client with proper configuration"""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=30.0,
            follow_redirects=True
        )
        
    def _handle_response(self, response: httpx.Response) -> Any:
        """Handle API response and raise appropriate errors
        
        Args:
            response: HTTP response to handle
            
        Returns:
            Parsed response data
            
        Raises:
            MentisAPIError: If the API returns an error
            MentisValidationError: If response validation fails
        """
        try:
            response.raise_for_status()
            if response.status_code == 204:  # No Content
                return None
            return response.json()
        except httpx.HTTPStatusError as e:
            try:
                error_data = response.json()
                error = Error(**error_data)
                raise MentisAPIError(
                    error.message,
                    status_code=e.response.status_code,
                    error_detail=error.detail
                )
            except Exception:
                raise MentisAPIError(
                    str(e),
                    status_code=e.response.status_code
                )
        except (ValidationError, ValueError) as e:
            raise MentisValidationError(f"Failed to parse response: {str(e)}")
            
    def _retry_request(self, func, max_retries: int = 3, delay: float = 1.0) -> Any:
        """Retry a request with exponential backoff
        
        Args:
            func: Function to retry
            max_retries: Maximum number of retry attempts
            delay: Initial delay between retries in seconds
            
        Returns:
            Result of the function call
            
        Raises:
            MentisError: If all retry attempts fail
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                return func()
            except MentisError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = delay * (2 ** attempt)
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{max_retries}): {str(e)}. "
                        f"Retrying in {wait_time:.1f} seconds..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"All retry attempts failed: {str(e)}")
                    raise last_error
                    
    def create_space(self, request: CreateSpaceRequest) -> Space:
        """Create a new space
        
        Args:
            request: Space creation request
            
        Returns:
            Created space
            
        Raises:
            MentisError: If space creation fails
        """
        logger.info(f"Creating space: {request.name}")
        try:
            response = self._client.post("/v1/spaces", json=request.model_dump(exclude_none=True))
            data = self._handle_response(response)
            return Space(**data)
        except httpx.RequestError as e:
            raise MentisConnectionError(f"Failed to connect to server: {str(e)}", original_error=e)
        except httpx.TimeoutException as e:
            raise MentisTimeoutError(f"Request timed out: {str(e)}", timeout=30.0)
        except Exception as e:
            raise MentisResourceError(
                f"Failed to create space: {str(e)}",
                resource_type="space",
                resource_id=request.name
            )
            
    def get_space(self, space_id: str) -> Space:
        """Get space details
        
        Args:
            space_id: ID of the space to retrieve
            
        Returns:
            Space details
            
        Raises:
            MentisError: If space retrieval fails
        """
        logger.debug(f"Retrieving space: {space_id}")
        try:
            response = self._client.get(f"/v1/spaces/{space_id}")
            data = self._handle_response(response)
            # 转换字段名
            if "ID" in data:
                data["space_id"] = data.pop("ID")
            if "Name" in data:
                data["name"] = data.pop("Name")
            if "Description" in data:
                data["description"] = data.pop("Description")
            if "CreatedAt" in data:
                data["created_at"] = data.pop("CreatedAt")
            if "UpdatedAt" in data:
                data["updated_at"] = data.pop("UpdatedAt")
            if "Metadata" in data:
                data["metadata"] = data.pop("Metadata")
            return Space(**data)
        except httpx.RequestError as e:
            raise MentisConnectionError(f"Failed to connect to server: {str(e)}", original_error=e)
        except httpx.TimeoutException as e:
            raise MentisTimeoutError(f"Request timed out: {str(e)}", timeout=30.0)
        except Exception as e:
            raise MentisResourceError(
                f"Failed to retrieve space: {str(e)}",
                resource_type="space",
                resource_id=space_id
            )
            
    def list_spaces(self) -> List[Space]:
        """List all available spaces
        
        Returns:
            List of spaces
            
        Raises:
            MentisError: If space listing fails
        """
        logger.debug("Listing all spaces")
        try:
            response = self._client.get("/v1/spaces")
            data = self._handle_response(response)
            # 转换字段名
            spaces = []
            for item in data:
                if "ID" in item:
                    item["space_id"] = item.pop("ID")
                if "Name" in item:
                    name = item.pop("Name")
                    # 转换 name 为符合要求的格式
                    if name == "Default Space":
                        name = "default"
                    item["name"] = name
                if "Description" in item:
                    item["description"] = item.pop("Description")
                if "CreatedAt" in item:
                    item["created_at"] = item.pop("CreatedAt")
                if "UpdatedAt" in item:
                    item["updated_at"] = item.pop("UpdatedAt")
                if "Metadata" in item:
                    item["metadata"] = item.pop("Metadata")
                spaces.append(Space(**item))
            return spaces
        except httpx.RequestError as e:
            raise MentisConnectionError(f"Failed to connect to server: {str(e)}", original_error=e)
        except httpx.TimeoutException as e:
            raise MentisTimeoutError(f"Request timed out: {str(e)}", timeout=30.0)
        except Exception as e:
            raise MentisResourceError(f"Failed to list spaces: {str(e)}", resource_type="space")
            
    def update_space(self, space_id: str, request: UpdateSpaceRequest) -> Space:
        """Update space information
        
        Args:
            space_id: ID of the space to update
            request: Update request
            
        Returns:
            Updated space
            
        Raises:
            MentisError: If space update fails
        """
        logger.info(f"Updating space: {space_id}")
        try:
            response = self._client.put(
                f"/v1/spaces/{space_id}",
                json=request.dict(exclude_none=True)
            )
            self._handle_response(response)  # Just check for errors
            # Get the updated space
            return self.get_space(space_id)
        except httpx.RequestError as e:
            raise MentisConnectionError(f"Failed to connect to server: {str(e)}", original_error=e)
        except httpx.TimeoutException as e:
            raise MentisTimeoutError(f"Request timed out: {str(e)}", timeout=30.0)
        except Exception as e:
            raise MentisResourceError(
                f"Failed to update space: {str(e)}",
                resource_type="space",
                resource_id=space_id
            )
            
    def delete_space(self, space_id: str) -> None:
        """Delete a space
        
        Args:
            space_id: ID of the space to delete
            
        Raises:
            MentisError: If space deletion fails
        """
        logger.info(f"Deleting space: {space_id}")
        try:
            response = self._client.delete(f"/v1/spaces/{space_id}")
            self._handle_response(response)
        except httpx.RequestError as e:
            raise MentisConnectionError(f"Failed to connect to server: {str(e)}", original_error=e)
        except httpx.TimeoutException as e:
            raise MentisTimeoutError(f"Request timed out: {str(e)}", timeout=30.0)
        except Exception as e:
            raise MentisResourceError(
                f"Failed to delete space: {str(e)}",
                resource_type="space",
                resource_id=space_id
            )
            
    def create_sandbox(self, space_id: str, request: CreateSandboxRequest) -> Sandbox:
        """Create a sandbox in a space
        
        Args:
            space_id: ID of the space to create sandbox in
            request: Sandbox creation request
            
        Returns:
            Created sandbox
            
        Raises:
            MentisError: If sandbox creation fails
        """
        logger.info(f"Creating sandbox in space: {space_id}")
        try:
            # Add space to the request
            data = request.dict(exclude_none=True)
            data["space"] = space_id
            response = self._client.post("/v1/sandboxes", json=data)
            data = self._handle_response(response)
            return Sandbox(**data)
        except httpx.RequestError as e:
            raise MentisConnectionError(f"Failed to connect to server: {str(e)}", original_error=e)
        except httpx.TimeoutException as e:
            raise MentisTimeoutError(f"Request timed out: {str(e)}", timeout=30.0)
        except Exception as e:
            raise MentisResourceError(
                f"Failed to create sandbox: {str(e)}",
                resource_type="sandbox",
                resource_id=request.name
            )
            
    def get_sandbox(self, space_id: str, sandbox_id: str) -> Sandbox:
        """Get sandbox details
        
        Args:
            space_id: ID of the space containing the sandbox
            sandbox_id: ID of the sandbox to retrieve
            
        Returns:
            Sandbox details
            
        Raises:
            MentisError: If sandbox retrieval fails
        """
        logger.debug(f"Retrieving sandbox: {sandbox_id} in space: {space_id}")
        try:
            response = self._client.get(f"/v1/spaces/{space_id}/sandboxes/{sandbox_id}")
            data = self._handle_response(response)
            return Sandbox(**data)
        except httpx.RequestError as e:
            raise MentisConnectionError(f"Failed to connect to server: {str(e)}", original_error=e)
        except httpx.TimeoutException as e:
            raise MentisTimeoutError(f"Request timed out: {str(e)}", timeout=30.0)
        except Exception as e:
            raise MentisResourceError(
                f"Failed to retrieve sandbox: {str(e)}",
                resource_type="sandbox",
                resource_id=sandbox_id
            )
            
    def list_sandboxes(self, space_id: str) -> List[Sandbox]:
        """List sandboxes in a space
        
        Args:
            space_id: ID of the space to list sandboxes from
            
        Returns:
            List of sandboxes
            
        Raises:
            MentisError: If sandbox listing fails
        """
        logger.debug(f"Listing sandboxes in space: {space_id}")
        try:
            response = self._client.get(f"/v1/spaces/{space_id}/sandboxes")
            data = self._handle_response(response)
            return [Sandbox(**item) for item in data]
        except httpx.RequestError as e:
            raise MentisConnectionError(f"Failed to connect to server: {str(e)}", original_error=e)
        except httpx.TimeoutException as e:
            raise MentisTimeoutError(f"Request timed out: {str(e)}", timeout=30.0)
        except Exception as e:
            raise MentisResourceError(
                f"Failed to list sandboxes: {str(e)}",
                resource_type="sandbox",
                resource_id=space_id
            )
            
    def delete_sandbox(self, space_id: str, sandbox_id: str) -> None:
        """Delete a sandbox
        
        Args:
            space_id: ID of the space containing the sandbox
            sandbox_id: ID of the sandbox to delete
            
        Raises:
            MentisError: If sandbox deletion fails
        """
        logger.info(f"Deleting sandbox: {sandbox_id} in space: {space_id}")
        try:
            response = self._client.delete(f"/v1/spaces/{space_id}/sandboxes/{sandbox_id}")
            self._handle_response(response)
        except httpx.RequestError as e:
            raise MentisConnectionError(f"Failed to connect to server: {str(e)}", original_error=e)
        except httpx.TimeoutException as e:
            raise MentisTimeoutError(f"Request timed out: {str(e)}", timeout=30.0)
        except Exception as e:
            raise MentisResourceError(
                f"Failed to delete sandbox: {str(e)}",
                resource_type="sandbox",
                resource_id=sandbox_id
            )
            
    def close(self) -> None:
        """Close the HTTP client"""
        self._client.close()