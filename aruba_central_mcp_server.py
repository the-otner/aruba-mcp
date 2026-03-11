#!/usr/bin/env python3
"""
HPE Aruba Networking Central MCP Server

Production-grade MCP server exposing the full HPE Aruba Networking Central REST API
as MCP tools. All API paths sourced from the official aruba/pycentral SDK.

Source: https://github.com/aruba/pycentral
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("aruba-central-mcp")

# Global configuration
BASE_URL = os.getenv("ARUBA_CENTRAL_BASE_URL", "https://apigw-uswest4.central.arubanetworks.com")
ACCESS_TOKEN = os.getenv("ARUBA_CENTRAL_TOKEN", "")
CLIENT_ID = os.getenv("ARUBA_CENTRAL_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("ARUBA_CENTRAL_CLIENT_SECRET", "")
REFRESH_TOKEN = os.getenv("ARUBA_CENTRAL_REFRESH_TOKEN", "")
TIMEOUT = int(os.getenv("ARUBA_CENTRAL_TIMEOUT", "30"))

# Initialize FastMCP server
mcp = FastMCP("aruba-central")

# HTTP client
http_client: Optional[httpx.AsyncClient] = None


async def get_http_client() -> httpx.AsyncClient:
    """Get or create the HTTP client."""
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=TIMEOUT)
    return http_client


def _clean_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Remove None values from parameters."""
    return {k: v for k, v in params.items() if v is not None}


async def _refresh_token() -> bool:
    """
    Refresh the OAuth2 access token.
    
    Returns:
        bool: True if refresh was successful
    """
    global ACCESS_TOKEN
    
    if not CLIENT_ID or not CLIENT_SECRET or not REFRESH_TOKEN:
        logger.error("Missing OAuth credentials for token refresh")
        return False
    
    try:
        client = await get_http_client()
        response = await client.post(
            f"{BASE_URL}/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": REFRESH_TOKEN
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code == 200:
            data = response.json()
            ACCESS_TOKEN = data.get("access_token", "")
            logger.info("Access token refreshed successfully")
            return True
        else:
            logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Token refresh exception: {str(e)}")
        return False


async def _request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    retry_on_401: bool = True
) -> Dict[str, Any]:
    """
    Core HTTP request function with auto-retry on 401.
    
    Args:
        method: HTTP method (GET, POST, PUT, PATCH, DELETE)
        path: API endpoint path
        params: Query parameters
        json_data: JSON body
        data: Form data
        retry_on_401: Whether to retry once on 401 with token refresh
        
    Returns:
        Dict containing response data or error structure
    """
    global ACCESS_TOKEN
    
    url = f"{BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Clean None values from params and json_data
    if params:
        params = _clean_params(params)
    if json_data:
        json_data = _clean_params(json_data)
    
    try:
        client = await get_http_client()
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
            data=data
        )
        
        # Handle 401 with token refresh and retry
        if response.status_code == 401 and retry_on_401:
            logger.warning("Received 401, attempting token refresh")
            if await _refresh_token():
                # Retry request with new token
                headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    data=data
                )
        
        # Handle successful responses
        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"success": True, "status_code": response.status_code, "data": response.text}
        
        # Handle error responses
        try:
            error_detail = response.json()
        except json.JSONDecodeError:
            error_detail = response.text
        
        return {
            "error": True,
            "status_code": response.status_code,
            "detail": error_detail
        }
        
    except Exception as e:
        logger.error(f"Request exception: {str(e)}")
        return {
            "error": True,
            "status_code": 0,
            "detail": str(e)
        }


async def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """HTTP GET request."""
    return await _request("GET", path, params=params)


async def _post(path: str, json_data: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """HTTP POST request."""
    return await _request("POST", path, json_data=json_data, data=data)


async def _put(path: str, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """HTTP PUT request."""
    return await _request("PUT", path, json_data=json_data)


async def _patch(path: str, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """HTTP PATCH request."""
    return await _request("PATCH", path, json_data=json_data)


async def _delete(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """HTTP DELETE request."""
    return await _request("DELETE", path, params=params)


# ============================================================================
# OAuth Tools (1)
# ============================================================================

@mcp.tool()
async def refresh_api_token() -> str:
    """
    Manually refresh the OAuth2 access token.
    
    Returns:
        Success message or error details
    """
    success = await _refresh_token()
    if success:
        return json.dumps({"success": True, "message": "Token refreshed successfully"})
    else:
        return json.dumps({"error": True, "message": "Token refresh failed"})


# ============================================================================
# Groups Tools (5)
# ============================================================================

@mcp.tool()
async def get_groups(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get list of configuration groups.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of groups to return
        
    Returns:
        JSON string containing groups list
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/configuration/v2/groups", params)
    return json.dumps(result)


@mcp.tool()
async def get_group_template_info(group_name: str) -> str:
    """
    Get template information for a specific group.
    
    Args:
        group_name: Name of the configuration group
        
    Returns:
        JSON string containing template info
    """
    params = {"group": group_name}
    result = await _get("/configuration/v2/groups/template_info", params)
    return json.dumps(result)


@mcp.tool()
async def create_group(
    group_name: str,
    group_password: str,
    wired_template_group: Optional[str] = None,
    wireless_template_group: Optional[str] = None
) -> str:
    """
    Create a new configuration group.
    
    Args:
        group_name: Name for the new group
        group_password: Password for the group
        wired_template_group: Template group for wired devices
        wireless_template_group: Template group for wireless devices
        
    Returns:
        JSON string containing creation result
    """
    json_data = {
        "group": group_name,
        "group_attributes": {
            "group_password": group_password,
            "template_info": {}
        }
    }
    
    if wired_template_group:
        json_data["group_attributes"]["template_info"]["Wired"] = wired_template_group
    if wireless_template_group:
        json_data["group_attributes"]["template_info"]["Wireless"] = wireless_template_group
    
    result = await _post("/configuration/v2/groups", json_data)
    return json.dumps(result)


@mcp.tool()
async def clone_group(
    group_name: str,
    clone_group_name: str
) -> str:
    """
    Clone an existing configuration group.
    
    Args:
        group_name: Name of the group to clone
        clone_group_name: Name for the cloned group
        
    Returns:
        JSON string containing clone result
    """
    json_data = {
        "group": group_name,
        "clone_group": clone_group_name
    }
    result = await _post("/configuration/v2/groups/clone", json_data)
    return json.dumps(result)


@mcp.tool()
async def delete_group(group_name: str) -> str:
    """
    Delete a configuration group.
    
    Args:
        group_name: Name of the group to delete
        
    Returns:
        JSON string containing deletion result
    """
    result = await _delete(f"/configuration/v1/groups/{group_name}")
    return json.dumps(result)


# ============================================================================
# Devices Config Tools (7)
# ============================================================================

@mcp.tool()
async def get_device_group(serial: str) -> str:
    """
    Get the group assignment for a device.
    
    Args:
        serial: Device serial number
        
    Returns:
        JSON string containing device group info
    """
    result = await _get(f"/configuration/v1/devices/{serial}/group")
    return json.dumps(result)


@mcp.tool()
async def get_device_configuration(serial: str) -> str:
    """
    Get the running configuration for a device.
    
    Args:
        serial: Device serial number
        
    Returns:
        JSON string containing device configuration
    """
    result = await _get(f"/configuration/v1/devices/{serial}/configuration")
    return json.dumps(result)


@mcp.tool()
async def get_device_config_details(serial: str) -> str:
    """
    Get configuration details for a device.
    
    Args:
        serial: Device serial number
        
    Returns:
        JSON string containing config details
    """
    result = await _get(f"/configuration/v1/devices/{serial}/config_details")
    return json.dumps(result)


@mcp.tool()
async def get_device_templates(
    device_type: Optional[str] = None,
    model: Optional[str] = None,
    version: Optional[str] = None
) -> str:
    """
    Get list of device templates.
    
    Args:
        device_type: Filter by device type (IAP, ArubaSwitch, MobilityController, etc.)
        model: Filter by device model
        version: Filter by firmware version
        
    Returns:
        JSON string containing templates list
    """
    params = {
        "device_type": device_type,
        "model": model,
        "version": version
    }
    result = await _get("/configuration/v1/devices/template", params)
    return json.dumps(result)


@mcp.tool()
async def get_group_device_templates(
    group_name: str,
    device_type: Optional[str] = None
) -> str:
    """
    Get device templates for a specific group.
    
    Args:
        group_name: Name of the configuration group
        device_type: Filter by device type
        
    Returns:
        JSON string containing group templates
    """
    params = {
        "group": group_name,
        "device_type": device_type
    }
    result = await _get("/configuration/v1/devices/groups/template", params)
    return json.dumps(result)


@mcp.tool()
async def set_switch_ssh_credentials(
    serial: str,
    username: str,
    password: str
) -> str:
    """
    Set SSH credentials for a switch device.
    
    Args:
        serial: Switch serial number
        username: SSH username
        password: SSH password
        
    Returns:
        JSON string containing result
    """
    json_data = {
        "username": username,
        "password": password
    }
    result = await _post(f"/configuration/v1/devices/{serial}/ssh_connection", json_data)
    return json.dumps(result)


@mcp.tool()
async def move_devices(
    group_name: str,
    serial_numbers: str
) -> str:
    """
    Move devices to a different group.
    
    Args:
        group_name: Target group name
        serial_numbers: Comma-separated list of device serial numbers
        
    Returns:
        JSON string containing move result
    """
    json_data = {
        "group": group_name,
        "serials": [s.strip() for s in serial_numbers.split(",")]
    }
    result = await _post("/configuration/v1/devices/move", json_data)
    return json.dumps(result)


# ============================================================================
# Templates Tools (3)
# ============================================================================

@mcp.tool()
async def get_templates(
    group_name: str,
    template_type: Optional[str] = None
) -> str:
    """
    Get templates in a configuration group.
    
    Args:
        group_name: Name of the configuration group
        template_type: Filter by template type
        
    Returns:
        JSON string containing templates list
    """
    params = {"template": template_type}
    result = await _get(f"/configuration/v1/groups/{group_name}/templates", params)
    return json.dumps(result)


@mcp.tool()
async def get_template_text(
    group_name: str,
    template_name: str
) -> str:
    """
    Get the text content of a template.
    
    Args:
        group_name: Name of the configuration group
        template_name: Name of the template
        
    Returns:
        JSON string containing template text
    """
    result = await _get(f"/configuration/v1/groups/{group_name}/templates/{template_name}")
    return json.dumps(result)


@mcp.tool()
async def delete_template(
    group_name: str,
    template_name: str
) -> str:
    """
    Delete a template from a group.
    
    Args:
        group_name: Name of the configuration group
        template_name: Name of the template to delete
        
    Returns:
        JSON string containing deletion result
    """
    result = await _delete(f"/configuration/v1/groups/{group_name}/templates/{template_name}")
    return json.dumps(result)


# ============================================================================
# Template Variables Tools (6)
# ============================================================================

@mcp.tool()
async def get_template_variables(serial: str) -> str:
    """
    Get template variables for a specific device.
    
    Args:
        serial: Device serial number
        
    Returns:
        JSON string containing template variables
    """
    result = await _get(f"/configuration/v1/devices/{serial}/template_variables")
    return json.dumps(result)


@mcp.tool()
async def get_all_template_variables(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get template variables for all devices.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing all template variables
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/configuration/v1/devices/template_variables", params)
    return json.dumps(result)


@mcp.tool()
async def create_template_variables(
    serial: str,
    variables: str
) -> str:
    """
    Create template variables for a device.
    
    Args:
        serial: Device serial number
        variables: JSON string of variables (e.g., '{"var1": "value1", "var2": "value2"}')
        
    Returns:
        JSON string containing creation result
    """
    try:
        vars_dict = json.loads(variables)
    except json.JSONDecodeError:
        return json.dumps({"error": True, "message": "Invalid JSON format for variables"})
    
    json_data = {"total": len(vars_dict), "variables": vars_dict}
    result = await _post(f"/configuration/v1/devices/{serial}/template_variables", json_data)
    return json.dumps(result)


@mcp.tool()
async def update_template_variables(
    serial: str,
    variables: str
) -> str:
    """
    Update template variables for a device.
    
    Args:
        serial: Device serial number
        variables: JSON string of variables to update
        
    Returns:
        JSON string containing update result
    """
    try:
        vars_dict = json.loads(variables)
    except json.JSONDecodeError:
        return json.dumps({"error": True, "message": "Invalid JSON format for variables"})
    
    json_data = {"total": len(vars_dict), "variables": vars_dict}
    result = await _patch(f"/configuration/v1/devices/{serial}/template_variables", json_data)
    return json.dumps(result)


@mcp.tool()
async def replace_template_variables(
    serial: str,
    variables: str
) -> str:
    """
    Replace all template variables for a device.
    
    Args:
        serial: Device serial number
        variables: JSON string of variables to set
        
    Returns:
        JSON string containing replacement result
    """
    try:
        vars_dict = json.loads(variables)
    except json.JSONDecodeError:
        return json.dumps({"error": True, "message": "Invalid JSON format for variables"})
    
    json_data = {"total": len(vars_dict), "variables": vars_dict}
    result = await _put(f"/configuration/v1/devices/{serial}/template_variables", json_data)
    return json.dumps(result)


@mcp.tool()
async def delete_template_variables(serial: str) -> str:
    """
    Delete all template variables for a device.
    
    Args:
        serial: Device serial number
        
    Returns:
        JSON string containing deletion result
    """
    result = await _delete(f"/configuration/v1/devices/{serial}/template_variables")
    return json.dumps(result)


# ============================================================================
# AP Settings Tools (2)
# ============================================================================

@mcp.tool()
async def get_ap_settings(serial: str) -> str:
    """
    Get settings for an Access Point.
    
    Args:
        serial: AP serial number
        
    Returns:
        JSON string containing AP settings
    """
    result = await _get(f"/configuration/v2/ap_settings/{serial}")
    return json.dumps(result)


@mcp.tool()
async def update_ap_settings(
    serial: str,
    settings: str
) -> str:
    """
    Update settings for an Access Point.
    
    Args:
        serial: AP serial number
        settings: JSON string of settings to update
        
    Returns:
        JSON string containing update result
    """
    try:
        settings_dict = json.loads(settings)
    except json.JSONDecodeError:
        return json.dumps({"error": True, "message": "Invalid JSON format for settings"})
    
    result = await _patch(f"/configuration/v2/ap_settings/{serial}", settings_dict)
    return json.dumps(result)


# ============================================================================
# AP CLI Config Tools (2)
# ============================================================================

@mcp.tool()
async def get_ap_cli_config(group_or_serial: str) -> str:
    """
    Get AP CLI configuration for a group or specific AP.
    
    Args:
        group_or_serial: Group name or AP serial number
        
    Returns:
        JSON string containing CLI configuration
    """
    result = await _get(f"/configuration/v1/ap_cli/{group_or_serial}")
    return json.dumps(result)


@mcp.tool()
async def replace_ap_cli_config(
    group_or_serial: str,
    cli_commands: str
) -> str:
    """
    Replace AP CLI configuration for a group or specific AP.
    
    Args:
        group_or_serial: Group name or AP serial number
        cli_commands: CLI commands as newline-separated string
        
    Returns:
        JSON string containing replacement result
    """
    json_data = {"clis": cli_commands.split("\n")}
    result = await _post(f"/configuration/v1/ap_cli/{group_or_serial}", json_data)
    return json.dumps(result)


# ============================================================================
# WLANs Tools (5)
# ============================================================================

@mcp.tool()
async def get_wlan(
    group_name: str,
    wlan_name: str
) -> str:
    """
    Get details of a specific WLAN.
    
    Args:
        group_name: Configuration group name
        wlan_name: WLAN name/SSID
        
    Returns:
        JSON string containing WLAN details
    """
    result = await _get(f"/configuration/full_wlan/{group_name}/{wlan_name}")
    return json.dumps(result)


@mcp.tool()
async def get_all_wlans(group_name: str) -> str:
    """
    Get all WLANs in a group.
    
    Args:
        group_name: Configuration group name (call get_groups first to retrieve valid names)
        
    Returns:
        JSON string containing all WLANs
    """
    result = await _get(f"/configuration/v1/wlan/{group_name}")
    return json.dumps(result)


@mcp.tool()
async def create_wlan(
    group_name: str,
    wlan_config: str
) -> str:
    """
    Create a new WLAN in a group.
    
    Args:
        group_name: Configuration group name
        wlan_config: JSON string of WLAN configuration
        
    Returns:
        JSON string containing creation result
    """
    try:
        config_dict = json.loads(wlan_config)
    except json.JSONDecodeError:
        return json.dumps({"error": True, "message": "Invalid JSON format for WLAN config"})
    
    result = await _post(f"/configuration/v2/wlan/{group_name}", config_dict)
    return json.dumps(result)


@mcp.tool()
async def update_wlan(
    group_name: str,
    wlan_name: str,
    wlan_config: str
) -> str:
    """
    Update an existing WLAN.
    
    Args:
        group_name: Configuration group name
        wlan_name: WLAN name/SSID to update
        wlan_config: JSON string of WLAN configuration
        
    Returns:
        JSON string containing update result
    """
    try:
        config_dict = json.loads(wlan_config)
    except json.JSONDecodeError:
        return json.dumps({"error": True, "message": "Invalid JSON format for WLAN config"})
    
    result = await _patch(f"/configuration/v2/wlan/{group_name}/{wlan_name}", config_dict)
    return json.dumps(result)


@mcp.tool()
async def delete_wlan(
    group_name: str,
    wlan_name: str
) -> str:
    """
    Delete a WLAN from a group.
    
    Args:
        group_name: Configuration group name
        wlan_name: WLAN name/SSID to delete
        
    Returns:
        JSON string containing deletion result
    """
    result = await _delete(f"/configuration/v1/wlan/{group_name}/{wlan_name}")
    return json.dumps(result)


# ============================================================================
# Device Inventory Tools (4)
# ============================================================================

@mcp.tool()
async def get_device_inventory(
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sku: Optional[str] = None
) -> str:
    """
    Get device inventory.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of devices
        sku: Filter by SKU
        
    Returns:
        JSON string containing device inventory
    """
    params = {"offset": offset, "limit": limit, "sku": sku}
    result = await _get("/platform/device_inventory/v1/devices", params)
    return json.dumps(result)


@mcp.tool()
async def add_device_to_inventory(
    mac_address: str,
    serial_number: str
) -> str:
    """
    Add a device to inventory.
    
    Args:
        mac_address: Device MAC address
        serial_number: Device serial number
        
    Returns:
        JSON string containing addition result
    """
    json_data = [{"mac": mac_address, "serial": serial_number}]
    result = await _post("/platform/device_inventory/v1/devices", json_data)
    return json.dumps(result)


@mcp.tool()
async def archive_devices(serial_numbers: str) -> str:
    """
    Archive devices from inventory.
    
    Args:
        serial_numbers: Comma-separated list of device serial numbers
        
    Returns:
        JSON string containing archive result
    """
    json_data = {"serials": [s.strip() for s in serial_numbers.split(",")]}
    result = await _post("/platform/device_inventory/v1/devices/archive", json_data)
    return json.dumps(result)


@mcp.tool()
async def unarchive_devices(serial_numbers: str) -> str:
    """
    Unarchive devices from inventory.
    
    Args:
        serial_numbers: Comma-separated list of device serial numbers
        
    Returns:
        JSON string containing unarchive result
    """
    json_data = {"serials": [s.strip() for s in serial_numbers.split(",")]}
    result = await _post("/platform/device_inventory/v1/devices/unarchive", json_data)
    return json.dumps(result)


# ============================================================================
# Licensing Tools (8)
# ============================================================================

@mcp.tool()
async def get_subscription_keys(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get subscription keys/licenses.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of keys
        
    Returns:
        JSON string containing subscription keys
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/platform/licensing/v1/subscriptions", params)
    return json.dumps(result)


@mcp.tool()
async def get_enabled_services() -> str:
    """
    Get enabled license services.
    
    Returns:
        JSON string containing enabled services
    """
    result = await _get("/platform/licensing/v1/services/enabled")
    return json.dumps(result)


@mcp.tool()
async def get_license_stats() -> str:
    """
    Get license statistics.
    
    Returns:
        JSON string containing license statistics
    """
    result = await _get("/platform/licensing/v1/subscriptions/stats")
    return json.dumps(result)


@mcp.tool()
async def get_license_service_config() -> str:
    """
    Get license service configuration.
    
    Returns:
        JSON string containing service configuration
    """
    result = await _get("/platform/licensing/v1/services/config")
    return json.dumps(result)


@mcp.tool()
async def assign_subscription(
    serials: str,
    services: str
) -> str:
    """
    Assign subscription/license to devices.
    
    Args:
        serials: Comma-separated list of device serial numbers
        services: Comma-separated list of service names
        
    Returns:
        JSON string containing assignment result
    """
    json_data = {
        "serials": [s.strip() for s in serials.split(",")],
        "services": [s.strip() for s in services.split(",")]
    }
    result = await _post("/platform/licensing/v1/subscriptions/assign", json_data)
    return json.dumps(result)


@mcp.tool()
async def unassign_subscription(
    serials: str,
    services: str
) -> str:
    """
    Unassign subscription/license from devices.
    
    Args:
        serials: Comma-separated list of device serial numbers
        services: Comma-separated list of service names
        
    Returns:
        JSON string containing unassignment result
    """
    json_data = {
        "serials": [s.strip() for s in serials.split(",")],
        "services": [s.strip() for s in services.split(",")]
    }
    result = await _post("/platform/licensing/v1/subscriptions/unassign", json_data)
    return json.dumps(result)


@mcp.tool()
async def get_auto_license_services() -> str:
    """
    Get auto-license service settings.
    
    Returns:
        JSON string containing auto-license settings
    """
    result = await _get("/platform/licensing/v1/customer/settings/autolicense")
    return json.dumps(result)


@mcp.tool()
async def assign_auto_license(services: str) -> str:
    """
    Assign auto-license services.
    
    Args:
        services: Comma-separated list of service names to auto-assign
        
    Returns:
        JSON string containing assignment result
    """
    json_data = {"services": [s.strip() for s in services.split(",")]}
    result = await _post("/platform/licensing/v1/customer/settings/autolicense", json_data)
    return json.dumps(result)


# ============================================================================
# Firmware Tools (5)
# ============================================================================

@mcp.tool()
async def get_firmware_swarms(
    group: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get firmware information for swarms.
    
    Args:
        group: Filter by group name
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing swarm firmware info
    """
    params = {"group": group, "offset": offset, "limit": limit}
    result = await _get("/firmware/v1/swarms", params)
    return json.dumps(result)


@mcp.tool()
async def get_firmware_versions(device_type: Optional[str] = None) -> str:
    """
    Get available firmware versions.
    
    Args:
        device_type: Filter by device type (IAP, MAS, HP, CONTROLLER, etc.)
        
    Returns:
        JSON string containing firmware versions
    """
    params = {"device_type": device_type}
    result = await _get("/firmware/v1/versions", params)
    return json.dumps(result)


@mcp.tool()
async def get_firmware_upgrade_status(
    group: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get firmware upgrade status.
    
    Args:
        group: Filter by group name
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing upgrade status
    """
    params = {"group": group, "offset": offset, "limit": limit}
    result = await _get("/firmware/v1/status", params)
    return json.dumps(result)


@mcp.tool()
async def upgrade_firmware(
    group: str,
    device_type: str,
    firmware_version: str,
    model: Optional[str] = None,
    reboot: Optional[bool] = None
) -> str:
    """
    Initiate firmware upgrade.
    
    Args:
        group: Group name
        device_type: Device type (IAP, MAS, HP, CONTROLLER, etc.)
        firmware_version: Target firmware version
        model: Device model (required for some device types)
        reboot: Whether to reboot after upgrade
        
    Returns:
        JSON string containing upgrade initiation result
    """
    json_data = {
        "group": group,
        "device_type": device_type,
        "firmware_version": firmware_version,
        "model": model,
        "reboot": reboot
    }
    result = await _post("/firmware/v1/upgrade", json_data)
    return json.dumps(result)


@mcp.tool()
async def cancel_firmware_upgrade(
    group: str,
    device_type: str
) -> str:
    """
    Cancel an ongoing firmware upgrade.
    
    Args:
        group: Group name
        device_type: Device type
        
    Returns:
        JSON string containing cancellation result
    """
    json_data = {"group": group, "device_type": device_type}
    result = await _post("/firmware/v1/upgrade/cancel", json_data)
    return json.dumps(result)


# ============================================================================
# Sites Tools (6)
# ============================================================================

@mcp.tool()
async def get_sites(
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    calculate_total: Optional[bool] = None
) -> str:
    """
    Get list of sites.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of sites
        calculate_total: Whether to calculate total count
        
    Returns:
        JSON string containing sites list
    """
    params = {"offset": offset, "limit": limit, "calculate_total": calculate_total}
    result = await _get("/central/v2/sites", params)
    return json.dumps(result)


@mcp.tool()
async def create_site(
    site_name: str,
    address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    country: Optional[str] = None,
    zipcode: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None
) -> str:
    """
    Create a new site.
    
    Args:
        site_name: Name for the new site
        address: Street address
        city: City name
        state: State/Province
        country: Country name
        zipcode: Postal/ZIP code
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        
    Returns:
        JSON string containing creation result
    """
    json_data = {
        "site_name": site_name,
        "site_address": {
            "address": address,
            "city": city,
            "state": state,
            "country": country,
            "zipcode": zipcode
        },
        "geolocation": {}
    }
    
    if latitude is not None:
        json_data["geolocation"]["latitude"] = latitude
    if longitude is not None:
        json_data["geolocation"]["longitude"] = longitude
    
    result = await _post("/central/v2/sites", json_data)
    return json.dumps(result)


@mcp.tool()
async def update_site(
    site_id: str,
    site_name: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    country: Optional[str] = None,
    zipcode: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None
) -> str:
    """
    Update an existing site.
    
    Args:
        site_id: Site ID to update
        site_name: Updated site name
        address: Updated street address
        city: Updated city name
        state: Updated state/Province
        country: Updated country name
        zipcode: Updated postal/ZIP code
        latitude: Updated latitude coordinate
        longitude: Updated longitude coordinate
        
    Returns:
        JSON string containing update result
    """
    json_data = {}
    
    if site_name:
        json_data["site_name"] = site_name
    
    if any([address, city, state, country, zipcode]):
        json_data["site_address"] = {
            "address": address,
            "city": city,
            "state": state,
            "country": country,
            "zipcode": zipcode
        }
    
    if latitude is not None or longitude is not None:
        json_data["geolocation"] = {}
        if latitude is not None:
            json_data["geolocation"]["latitude"] = latitude
        if longitude is not None:
            json_data["geolocation"]["longitude"] = longitude
    
    result = await _patch(f"/central/v2/sites/{site_id}", json_data)
    return json.dumps(result)


@mcp.tool()
async def delete_site(site_id: str) -> str:
    """
    Delete a site.
    
    Args:
        site_id: Site ID to delete
        
    Returns:
        JSON string containing deletion result
    """
    result = await _delete(f"/central/v2/sites/{site_id}")
    return json.dumps(result)


@mcp.tool()
async def associate_devices_to_site(
    site_id: str,
    serial_numbers: str
) -> str:
    """
    Associate devices to a site.
    
    Args:
        site_id: Site ID
        serial_numbers: Comma-separated list of device serial numbers
        
    Returns:
        JSON string containing association result
    """
    try:
        site_id_int = int(site_id)
    except ValueError:
        return json.dumps({"error": True, "message": f"Invalid site_id: {site_id} must be a valid integer"})
    
    json_data = {
        "site_id": site_id_int,
        "device_ids": [s.strip() for s in serial_numbers.split(",")]
    }
    result = await _post("/central/v2/sites/associations", json_data)
    return json.dumps(result)


@mcp.tool()
async def unassociate_devices_from_site(
    site_id: str,
    serial_numbers: str
) -> str:
    """
    Unassociate devices from a site.
    
    Args:
        site_id: Site ID
        serial_numbers: Comma-separated list of device serial numbers
        
    Returns:
        JSON string containing unassociation result
    """
    try:
        site_id_int = int(site_id)
    except ValueError:
        return json.dumps({"error": True, "message": f"Invalid site_id: {site_id} must be a valid integer"})
    
    json_data = {
        "site_id": site_id_int,
        "device_ids": [s.strip() for s in serial_numbers.split(",")]
    }
    result = await _delete("/central/v2/sites/associations", json_data)
    return json.dumps(result)


# ============================================================================
# Topology Tools (6)
# ============================================================================

@mcp.tool()
async def get_topology_site(site_id: Optional[str] = None) -> str:
    """
    Get topology information for a site.
    
    Args:
        site_id: Site ID (optional, returns all if not specified)
        
    Returns:
        JSON string containing site topology
    """
    params = {"site_id": site_id}
    result = await _get("/topology_external_api", params)
    return json.dumps(result)


@mcp.tool()
async def get_topology_devices() -> str:
    """
    Get topology device information.
    
    Returns:
        JSON string containing device topology
    """
    result = await _get("/topology_external_api/devices")
    return json.dumps(result)


@mcp.tool()
async def get_topology_edges() -> str:
    """
    Get topology edge connections.
    
    Returns:
        JSON string containing topology edges
    """
    result = await _get("/topology_external_api/v2/edges")
    return json.dumps(result)


@mcp.tool()
async def get_topology_uplinks() -> str:
    """
    Get uplink topology information.
    
    Returns:
        JSON string containing uplink topology
    """
    result = await _get("/topology_external_api/uplinks")
    return json.dumps(result)


@mcp.tool()
async def get_topology_tunnels() -> str:
    """
    Get tunnel topology information.
    
    Returns:
        JSON string containing tunnel topology
    """
    result = await _get("/topology_external_api/tunnels")
    return json.dumps(result)


@mcp.tool()
async def get_topology_ap_lldp_neighbors(serial: str) -> str:
    """
    Get LLDP neighbor information for an AP.
    
    Args:
        serial: AP serial number
        
    Returns:
        JSON string containing LLDP neighbors
    """
    params = {"serial": serial}
    result = await _get("/topology_external_api/apNeighbors", params)
    return json.dumps(result)


# ============================================================================
# RAPIDS/WIDS Tools (7)
# ============================================================================

@mcp.tool()
async def get_rogue_aps(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get detected rogue access points.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing rogue APs
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/rapids/v1/rogue_aps", params)
    return json.dumps(result)


@mcp.tool()
async def get_interfering_aps(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get detected interfering access points.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing interfering APs
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/rapids/v1/interfering_aps", params)
    return json.dumps(result)


@mcp.tool()
async def get_suspect_aps(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get detected suspect access points.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing suspect APs
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/rapids/v1/suspect_aps", params)
    return json.dumps(result)


@mcp.tool()
async def get_neighbor_aps(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get detected neighbor access points.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing neighbor APs
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/rapids/v1/neighbor_aps", params)
    return json.dumps(result)


@mcp.tool()
async def get_wids_infrastructure_attacks(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get WIDS infrastructure attack detections.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing infrastructure attacks
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/rapids/v1/wids/infrastructure_attacks", params)
    return json.dumps(result)


@mcp.tool()
async def get_wids_client_attacks(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get WIDS client attack detections.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing client attacks
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/rapids/v1/wids/client_attacks", params)
    return json.dumps(result)


@mcp.tool()
async def get_wids_events(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get WIDS event history.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of results
        
    Returns:
        JSON string containing WIDS events
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/rapids/v1/wids/events", params)
    return json.dumps(result)


# ============================================================================
# Audit Logs Tools (3)
# ============================================================================

@mcp.tool()
async def get_audit_trail_logs(
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None
) -> str:
    """
    Get audit trail logs.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of logs
        start_time: Start timestamp (Unix epoch)
        end_time: End timestamp (Unix epoch)
        
    Returns:
        JSON string containing audit logs
    """
    params = {
        "offset": offset,
        "limit": limit,
        "start_time": start_time,
        "end_time": end_time
    }
    result = await _get("/platform/auditlogs/v1/logs", params)
    return json.dumps(result)


@mcp.tool()
async def get_event_logs(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get event logs.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of logs
        
    Returns:
        JSON string containing event logs
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/auditlogs/v1/events", params)
    return json.dumps(result)


@mcp.tool()
async def get_event_details(event_id: str) -> str:
    """
    Get details of a specific event.
    
    Args:
        event_id: Event ID
        
    Returns:
        JSON string containing event details
    """
    result = await _get(f"/auditlogs/v1/event_details/{event_id}")
    return json.dumps(result)


# ============================================================================
# VisualRF Tools (8)
# ============================================================================

@mcp.tool()
async def get_visualrf_campus_list() -> str:
    """
    Get list of VisualRF campuses.
    
    Returns:
        JSON string containing campus list
    """
    result = await _get("/visualrf_api/v1/campus")
    return json.dumps(result)


@mcp.tool()
async def get_visualrf_campus_info(campus_id: str) -> str:
    """
    Get detailed information for a campus.
    
    Args:
        campus_id: Campus ID
        
    Returns:
        JSON string containing campus info
    """
    result = await _get(f"/visualrf_api/v1/campus/{campus_id}")
    return json.dumps(result)


@mcp.tool()
async def get_visualrf_building_info(building_id: str) -> str:
    """
    Get detailed information for a building.
    
    Args:
        building_id: Building ID
        
    Returns:
        JSON string containing building info
    """
    result = await _get(f"/visualrf_api/v1/building/{building_id}")
    return json.dumps(result)


@mcp.tool()
async def get_visualrf_floor_info(floor_id: str) -> str:
    """
    Get detailed information for a floor.
    
    Args:
        floor_id: Floor ID
        
    Returns:
        JSON string containing floor info
    """
    result = await _get(f"/visualrf_api/v1/floor/{floor_id}")
    return json.dumps(result)


@mcp.tool()
async def get_visualrf_floor_aps(floor_id: str) -> str:
    """
    Get Access Point locations on a floor.
    
    Args:
        floor_id: Floor ID
        
    Returns:
        JSON string containing AP locations
    """
    result = await _get(f"/visualrf_api/v1/floor/{floor_id}/access_point_location")
    return json.dumps(result)


@mcp.tool()
async def get_visualrf_floor_clients(floor_id: str) -> str:
    """
    Get client locations on a floor.
    
    Args:
        floor_id: Floor ID
        
    Returns:
        JSON string containing client locations
    """
    result = await _get(f"/visualrf_api/v1/floor/{floor_id}/client_location")
    return json.dumps(result)


@mcp.tool()
async def get_visualrf_client_location(client_mac: str) -> str:
    """
    Get location information for a specific client.
    
    Args:
        client_mac: Client MAC address
        
    Returns:
        JSON string containing client location
    """
    result = await _get(f"/visualrf_api/v1/client_location/{client_mac}")
    return json.dumps(result)


@mcp.tool()
async def get_visualrf_rogue_location(rogue_mac: str) -> str:
    """
    Get location information for a rogue AP.
    
    Args:
        rogue_mac: Rogue AP MAC address
        
    Returns:
        JSON string containing rogue location
    """
    result = await _get(f"/visualrf_api/v1/rogue_location/{rogue_mac}")
    return json.dumps(result)


# ============================================================================
# User Management Tools (6)
# ============================================================================

@mcp.tool()
async def list_users(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get list of users.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of users
        
    Returns:
        JSON string containing users list
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/platform/rbac/v1/users", params)
    return json.dumps(result)


@mcp.tool()
async def get_user(username: str) -> str:
    """
    Get details of a specific user.
    
    Args:
        username: Username
        
    Returns:
        JSON string containing user details
    """
    result = await _get(f"/platform/rbac/v1/users/{username}")
    return json.dumps(result)


@mcp.tool()
async def create_user(
    username: str,
    password: str,
    name: str,
    email: str
) -> str:
    """
    Create a new user.
    
    Args:
        username: Username for the new user
        password: Password for the new user
        name: Full name
        email: Email address
        
    Returns:
        JSON string containing creation result
    """
    json_data = {
        "username": username,
        "password": password,
        "name": name,
        "email": email
    }
    result = await _post("/platform/rbac/v1/users", json_data)
    return json.dumps(result)


@mcp.tool()
async def update_user(
    username: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Update an existing user.
    
    Args:
        username: Username to update
        name: Updated full name
        email: Updated email address
        password: Updated password
        
    Returns:
        JSON string containing update result
    """
    json_data = {
        "name": name,
        "email": email,
        "password": password
    }
    result = await _patch(f"/platform/rbac/v1/users/{username}", json_data)
    return json.dumps(result)


@mcp.tool()
async def delete_user(username: str) -> str:
    """
    Delete a user.
    
    Args:
        username: Username to delete
        
    Returns:
        JSON string containing deletion result
    """
    result = await _delete(f"/platform/rbac/v1/users/{username}")
    return json.dumps(result)


@mcp.tool()
async def get_roles() -> str:
    """
    Get list of available user roles.
    
    Returns:
        JSON string containing roles list
    """
    result = await _get("/platform/rbac/v1/roles")
    return json.dumps(result)


# ============================================================================
# MSP Tools (5)
# ============================================================================

@mcp.tool()
async def get_msp_customers(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get list of MSP customers.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of customers
        
    Returns:
        JSON string containing MSP customers
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/msp_api/v2/customers", params)
    return json.dumps(result)


@mcp.tool()
async def create_msp_customer(
    customer_name: str,
    description: Optional[str] = None
) -> str:
    """
    Create a new MSP customer.
    
    Args:
        customer_name: Name for the new customer
        description: Customer description
        
    Returns:
        JSON string containing creation result
    """
    json_data = {
        "customer_name": customer_name,
        "description": description
    }
    result = await _post("/msp_api/v1/customers", json_data)
    return json.dumps(result)


@mcp.tool()
async def get_msp_country_codes() -> str:
    """
    Get list of country codes for MSP.
    
    Returns:
        JSON string containing country codes
    """
    result = await _get("/msp_api/v2/get_country_code")
    return json.dumps(result)


@mcp.tool()
async def get_msp_devices(
    customer_id: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get MSP devices.
    
    Args:
        customer_id: Filter by customer ID
        offset: Pagination offset
        limit: Maximum number of devices
        
    Returns:
        JSON string containing MSP devices
    """
    params = {
        "customer_id": customer_id,
        "offset": offset,
        "limit": limit
    }
    result = await _get("/msp_api/v1/devices", params)
    return json.dumps(result)


@mcp.tool()
async def get_msp_groups(
    customer_id: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get MSP groups.
    
    Args:
        customer_id: Filter by customer ID
        offset: Pagination offset
        limit: Maximum number of groups
        
    Returns:
        JSON string containing MSP groups
    """
    params = {
        "customer_id": customer_id,
        "offset": offset,
        "limit": limit
    }
    result = await _get("/msp_api/v1/groups", params)
    return json.dumps(result)


# ============================================================================
# Telemetry Tools (1)
# ============================================================================

@mcp.tool()
async def get_all_reporting_radios(
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get telemetry data for all reporting radios.
    
    Args:
        offset: Pagination offset
        limit: Maximum number of radios
        
    Returns:
        JSON string containing radio telemetry data
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/telemetry/v1/reporting_radio_all", params)
    return json.dumps(result)

# ============================================================================
# NEW: Client Monitoring Tools (5)
# ============================================================================

@mcp.tool()
async def get_clients(
    offset: Optional[int] = None, limit: Optional[int] = None,
    group: Optional[str] = None, site: Optional[str] = None,
    network: Optional[str] = None, serial: Optional[str] = None,
    band: Optional[str] = None, swarm_id: Optional[str] = None
) -> str:
    """
    Get all connected clients (wired and wireless). Returns client details
    including MAC, IP, OS, SSID, signal strength, connection speed, and
    associated AP/switch. This is the primary tool for answering questions
    about who is connected to the network.
    """
    params = {
        "offset": offset, "limit": limit, "group": group, "site": site,
        "network": network, "serial": serial, "band": band, "swarm_id": swarm_id
    }
    result = await _get("/monitoring/v1/clients", params)
    return json.dumps(result)


@mcp.tool()
async def get_wireless_clients(
    offset: Optional[int] = None, limit: Optional[int] = None,
    group: Optional[str] = None, site: Optional[str] = None,
    network: Optional[str] = None, serial: Optional[str] = None,
    band: Optional[str] = None, swarm_id: Optional[str] = None
) -> str:
    """
    Get wireless clients. Returns details like SSID, signal, SNR, channel,
    band, speed, AP name for each wireless client.
    """
    params = {
        "offset": offset, "limit": limit, "group": group, "site": site,
        "network": network, "serial": serial, "band": band, "swarm_id": swarm_id
    }
    result = await _get("/monitoring/v1/clients/wireless", params)
    return json.dumps(result)


@mcp.tool()
async def get_wired_clients(
    offset: Optional[int] = None, limit: Optional[int] = None,
    group: Optional[str] = None, site: Optional[str] = None,
    serial: Optional[str] = None, stack_id: Optional[str] = None
) -> str:
    """
    Get wired clients. Returns details like switch port, VLAN, speed,
    and connected switch for each wired client.
    """
    params = {
        "offset": offset, "limit": limit, "group": group, "site": site,
        "serial": serial, "stack_id": stack_id
    }
    result = await _get("/monitoring/v1/clients/wired", params)
    return json.dumps(result)


@mcp.tool()
async def get_client_details(macaddr: str) -> str:
    """
    Get detailed information for a specific client by MAC address.
    Includes connection history, signal quality, throughput, OS type, VLAN.
    """
    result = await _get(f"/monitoring/v1/clients/{macaddr}")
    return json.dumps(result)


@mcp.tool()
async def get_client_count(
    group: Optional[str] = None, site: Optional[str] = None,
    network: Optional[str] = None, serial: Optional[str] = None,
    band: Optional[str] = None
) -> str:
    """
    Get client count with breakdown by band, SSID, or site.
    Quick way to see how many users are connected without fetching all records.
    """
    params = {"group": group, "site": site, "network": network, "serial": serial, "band": band}
    result = await _get("/monitoring/v2/clients/count", params)
    return json.dumps(result)


# ============================================================================
# NEW: Alerts & Notifications Tools (3)
# ============================================================================

@mcp.tool()
async def get_alerts(
    offset: Optional[int] = None, limit: Optional[int] = None,
    severity: Optional[str] = None, search: Optional[str] = None,
    group: Optional[str] = None, site: Optional[str] = None
) -> str:
    """
    Get active alerts and notifications. Returns alerts like AP down, rogue
    detected, high CPU, authentication failures. Use severity filter:
    critical, major, minor, warning, info.
    """
    params = {
        "offset": offset, "limit": limit, "severity": severity,
        "search": search, "group": group, "site": site
    }
    result = await _get("/central/v1/notifications", params)
    return json.dumps(result)


@mcp.tool()
async def get_alert_config() -> str:
    """
    Get alert/notification configuration and thresholds.
    Shows which alerts are enabled and their trigger conditions.
    """
    result = await _get("/central/v1/notifications/settings")
    return json.dumps(result)


@mcp.tool()
async def acknowledge_alert(alert_id: str) -> str:
    """Acknowledge/clear a specific alert by its ID."""
    result = await _post(f"/central/v1/notifications/{alert_id}", {"acknowledged": True})
    return json.dumps(result)


# ============================================================================
# NEW: Network Health / Device Monitoring Tools (7)
# ============================================================================

@mcp.tool()
async def get_aps(
    group: Optional[str] = None, site: Optional[str] = None,
    status: Optional[str] = None, fields: Optional[str] = None,
    offset: Optional[int] = None, limit: Optional[int] = None,
    swarm_id: Optional[str] = None, serial: Optional[str] = None
) -> str:
    """
    Get live AP monitoring data. Returns AP status (Up/Down), uptime,
    connected clients count, IP address, model, firmware version, channel,
    power, noise floor, and utilization. Primary tool for AP health monitoring.
    """
    params = {
        "group": group, "site": site, "status": status, "fields": fields,
        "offset": offset, "limit": limit, "swarm_id": swarm_id, "serial": serial
    }
    result = await _get("/monitoring/v2/aps", params)
    return json.dumps(result)


@mcp.tool()
async def get_ap_details(serial: str) -> str:
    """
    Get detailed live monitoring data for a specific AP by serial number.
    Includes radio details, channel, power, client count, mesh info, RF environment.
    """
    result = await _get(f"/monitoring/v1/aps/{serial}")
    return json.dumps(result)


@mcp.tool()
async def get_switches(
    group: Optional[str] = None, site: Optional[str] = None,
    status: Optional[str] = None, fields: Optional[str] = None,
    offset: Optional[int] = None, limit: Optional[int] = None,
    serial: Optional[str] = None
) -> str:
    """
    Get live switch monitoring data. Returns switch status (Up/Down), uptime,
    model, firmware, fan/PSU status, CPU and memory usage, and port count.
    """
    params = {
        "group": group, "site": site, "status": status, "fields": fields,
        "offset": offset, "limit": limit, "serial": serial
    }
    result = await _get("/monitoring/v1/switches", params)
    return json.dumps(result)


@mcp.tool()
async def get_switch_details(serial: str) -> str:
    """
    Get detailed live monitoring data for a specific switch by serial.
    Includes stack info, port details, PoE, VLAN, CPU/memory.
    """
    result = await _get(f"/monitoring/v1/switches/{serial}")
    return json.dumps(result)


@mcp.tool()
async def get_gateways(
    group: Optional[str] = None, site: Optional[str] = None,
    status: Optional[str] = None, fields: Optional[str] = None,
    offset: Optional[int] = None, limit: Optional[int] = None,
    serial: Optional[str] = None
) -> str:
    """
    Get live gateway/controller monitoring data. Returns gateway status,
    uptime, model, firmware, tunnel count, CPU/memory usage.
    """
    params = {
        "group": group, "site": site, "status": status, "fields": fields,
        "offset": offset, "limit": limit, "serial": serial
    }
    result = await _get("/monitoring/v1/gateways", params)
    return json.dumps(result)


@mcp.tool()
async def get_gateway_details(serial: str) -> str:
    """Get detailed live monitoring data for a specific gateway by serial."""
    result = await _get(f"/monitoring/v1/gateways/{serial}")
    return json.dumps(result)


@mcp.tool()
async def get_ap_rf_summary(
    group: Optional[str] = None, site: Optional[str] = None,
    band: Optional[str] = None, offset: Optional[int] = None,
    limit: Optional[int] = None
) -> str:
    """
    Get AP RF environment summary. Returns noise floor, channel utilization,
    interference, and neighbor count per AP. Essential for RF troubleshooting.
    """
    params = {"group": group, "site": site, "band": band, "offset": offset, "limit": limit}
    result = await _get("/monitoring/v1/aps/rf_summary", params)
    return json.dumps(result)


# ============================================================================
# NEW: Troubleshooting Tools (5)
# ============================================================================

@mcp.tool()
async def get_switch_ports(
    serial: str, offset: Optional[int] = None, limit: Optional[int] = None
) -> str:
    """
    Get port status for a switch. Returns per-port details: speed, duplex,
    PoE, VLAN, errors, in/out bytes, admin/oper status.
    """
    params = {"offset": offset, "limit": limit}
    result = await _get(f"/monitoring/v1/switches/{serial}/ports", params)
    return json.dumps(result)


@mcp.tool()
async def get_switch_port_details(serial: str, port: str) -> str:
    """
    Get detailed information for a specific switch port including
    traffic stats, errors, and connected device.
    """
    result = await _get(f"/monitoring/v1/switches/{serial}/ports/{port}")
    return json.dumps(result)


@mcp.tool()
async def get_device_tunnels(serial: str) -> str:
    """
    Get VPN/tunnel status for a device. Shows tunnel endpoints,
    status, uptime, and throughput.
    """
    result = await _get(f"/monitoring/v1/devices/{serial}/tunnels")
    return json.dumps(result)


@mcp.tool()
async def get_ap_neighbors(serial: str) -> str:
    """
    Get RF neighbor information for an AP. Shows nearby APs and their
    signal strength for RF planning.
    """
    result = await _get(f"/monitoring/v1/aps/{serial}/neighbors")
    return json.dumps(result)


@mcp.tool()
async def get_networks(
    offset: Optional[int] = None, limit: Optional[int] = None
) -> str:
    """
    Get list of networks. Returns all configured networks with client
    count and health metrics.
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/monitoring/v2/networks", params)
    return json.dumps(result)


# ============================================================================
# NEW: WAN Health Tools (3)
# ============================================================================

@mcp.tool()
async def get_wan_uplinks(
    group: Optional[str] = None, site: Optional[str] = None,
    offset: Optional[int] = None, limit: Optional[int] = None
) -> str:
    """
    Get WAN uplink status and health. Returns uplink bandwidth usage,
    latency, jitter, packet loss per WAN interface.
    """
    params = {"group": group, "site": site, "offset": offset, "limit": limit}
    result = await _get("/monitoring/v1/wan/uplinks", params)
    return json.dumps(result)


@mcp.tool()
async def get_wan_uplink_bandwidth(
    serial: str, uplink_id: Optional[str] = None
) -> str:
    """Get WAN uplink bandwidth utilization for a specific device."""
    params = {"uplink_id": uplink_id}
    result = await _get(f"/monitoring/v1/wan/uplinks/bandwidth/{serial}", params)
    return json.dumps(result)


@mcp.tool()
async def get_wan_tunnels(
    group: Optional[str] = None, site: Optional[str] = None,
    offset: Optional[int] = None, limit: Optional[int] = None
) -> str:
    """
    Get WAN VPN tunnel status. Shows all SD-WAN/VPN tunnels, their health,
    latency, and throughput.
    """
    params = {"group": group, "site": site, "offset": offset, "limit": limit}
    result = await _get("/monitoring/v1/wan/tunnels", params)
    return json.dumps(result)


# ============================================================================
# NEW: Presence Analytics Tools (2)
# ============================================================================

@mcp.tool()
async def get_presence_analytics(
    site_id: str, duration: Optional[str] = None
) -> str:
    """
    Get presence analytics for a site. Returns visitor count, dwell time,
    and engagement metrics.
    """
    params = {"site_id": site_id, "duration": duration}
    result = await _get("/presence/v1/analytics/sites", params)
    return json.dumps(result)


@mcp.tool()
async def get_presence_trend(
    site_id: str, duration: Optional[str] = None, interval: Optional[str] = None
) -> str:
    """
    Get presence trend data over time for a site. Shows visitor traffic
    patterns and peak hours.
    """
    params = {"site_id": site_id, "duration": duration, "interval": interval}
    result = await _get("/presence/v1/analytics/trend", params)
    return json.dumps(result)


# ============================================================================
# NEW: Guest Portal Tools (3)
# ============================================================================

@mcp.tool()
async def get_guest_portals(
    offset: Optional[int] = None, limit: Optional[int] = None
) -> str:
    """
    Get list of configured guest portals. Returns portal names, URLs,
    authentication methods.
    """
    params = {"offset": offset, "limit": limit}
    result = await _get("/guest/v1/portals", params)
    return json.dumps(result)


@mcp.tool()
async def get_guest_visitors(
    portal_id: str, offset: Optional[int] = None, limit: Optional[int] = None
) -> str:
    """
    Get guest visitors for a portal. Returns visitor details, registration
    time, and status.
    """
    params = {"offset": offset, "limit": limit}
    result = await _get(f"/guest/v1/portals/{portal_id}/visitors", params)
    return json.dumps(result)


@mcp.tool()
async def create_guest_visitor(
    portal_id: str, name: str, email: Optional[str] = None,
    phone: Optional[str] = None, company: Optional[str] = None
) -> str:
    """Create a guest visitor/voucher for a portal."""
    json_data = {
        "name": name, "email": email,
        "phone": phone, "company_name": company
    }
    result = await _post(f"/guest/v1/portals/{portal_id}/visitors", json_data)
    return json.dumps(result)

# ============================================================================
# Main Entry Point
# ============================================================================

async def cleanup():
    """Cleanup resources on shutdown."""
    global http_client
    if http_client is not None:
        await http_client.aclose()
        http_client = None
        logger.info("HTTP client closed")


if __name__ == "__main__":
    import argparse
    import asyncio
    import signal
    
    parser = argparse.ArgumentParser(description="Aruba Central MCP Server")
    parser.add_argument("--sse", action="store_true", help="Run with SSE transport instead of stdio")
    args = parser.parse_args()
    
    # Log startup
    logger.info("=" * 60)
    logger.info("HPE Aruba Networking Central MCP Server")
    logger.info("=" * 60)
    logger.info(f"Base URL: {BASE_URL}")
    logger.info(f"Transport: {'SSE' if args.sse else 'stdio'}")
    logger.info(f"Timeout: {TIMEOUT}s")
    logger.info("=" * 60)
    
    # Setup cleanup on shutdown
    def handle_shutdown(signum, frame):
        """Handle shutdown signals."""
        logger.info("Shutdown signal received, cleaning up...")
        asyncio.create_task(cleanup())
    
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        # Run the MCP server
        if args.sse:
            mcp.run(transport="sse")
        else:
            mcp.run(transport="stdio")
    finally:
        # Ensure cleanup happens
        asyncio.run(cleanup())
