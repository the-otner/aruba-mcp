"""
LangGraph ReAct Agent v2 for Aruba Central + SSH MCP Server

Phase 1: Direct Aruba Central API calls with httpx (118 tools)
Phase 2: SSH/CLI via Netmiko MCP server (31 tools)

Features:
- Semantic tool filtering + keyword boosting
- Auto token refresh on startup and 401
- Smart blocked-tools list
- Detailed system prompt
- Empty response retry logic
- Multi-source: API + SSH tools
"""

import os
import sys
import asyncio
import json
from typing import TypedDict, Annotated, Sequence, Optional
from datetime import datetime

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END
from langchain_core.tools import tool as langchain_tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

from tool_filter import SemanticToolFilter

load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
TOP_K_TOOLS = int(os.getenv("TOP_K_TOOLS", "10"))

# Maximum times the same (tool, args) pair may fail before being suppressed
MAX_TOOL_FAILURES = 3


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: Aruba Central REST API endpoint mapping
# "params"      = default query parameters (merged with caller-supplied values)
# "param_hints" = actionable guidance shown when a required path param is missing
# NOTE: get_wlan intentionally uses the unversioned /configuration/full_wlan/
#       path — this is the canonical GET endpoint per the pycentral SDK
#       (ConfigurationUrl.WLAN["GET"]) and differs from the v1/v2 write paths.
# ══════════════════════════════════════════════════════════════════════════════

API_ENDPOINTS = {
    # OAuth
    "refresh_api_token": {"method": "POST", "path": "/oauth2/token", "type": "form"},

    # Groups
    "get_groups": {"method": "GET", "path": "/configuration/v2/groups", "params": {"offset": 0, "limit": 20}},
    "get_group_template_info": {"method": "GET", "path": "/configuration/v2/groups/template_info"},
    "create_group": {"method": "POST", "path": "/configuration/v2/groups"},
    "clone_group": {"method": "POST", "path": "/configuration/v2/groups/clone"},
    "delete_group": {"method": "DELETE", "path": "/configuration/v1/groups/{group_name}",
                     "param_hints": {"group_name": "Call get_groups to retrieve valid group names."}},

    # Devices Config
    "get_device_group": {"method": "GET", "path": "/configuration/v1/devices/{serial}/group",
                         "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},
    "get_device_configuration": {"method": "GET", "path": "/configuration/v1/devices/{serial}/configuration",
                                  "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},
    "get_device_config_details": {"method": "GET", "path": "/configuration/v1/devices/{serial}/config_details",
                                   "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},
    "get_device_templates": {"method": "GET", "path": "/configuration/v1/devices/{serial}/templates",
                              "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},
    "get_group_device_templates": {"method": "GET", "path": "/configuration/v1/groups/{group_name}/templates",
                                    "param_hints": {"group_name": "Call get_groups to retrieve valid group names."}},
    "set_switch_ssh_credentials": {"method": "POST", "path": "/configuration/v1/devices/{serial}/ssh_credentials",
                                    "param_hints": {"serial": "Call get_switches to retrieve switch serial numbers."}},
    "move_devices": {"method": "POST", "path": "/configuration/v1/devices/move"},

    # Templates
    "get_templates": {"method": "GET", "path": "/configuration/v1/groups/{group_name}/templates",
                      "param_hints": {"group_name": "Call get_groups to retrieve valid group names."}},
    "get_template_text": {"method": "GET", "path": "/configuration/v1/groups/{group_name}/templates/{template_name}",
                           "param_hints": {"group_name": "Call get_groups to retrieve valid group names.", "template_name": "Call get_templates(group_name=<name>) to retrieve template names."}},
    "delete_template": {"method": "DELETE", "path": "/configuration/v1/groups/{group_name}/templates/{template_name}",
                         "param_hints": {"group_name": "Call get_groups to retrieve valid group names.", "template_name": "Call get_templates(group_name=<name>) to retrieve template names."}},

    # Template Variables
    "get_template_variables": {"method": "GET", "path": "/configuration/v1/devices/{serial}/template_variables",
                                "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},
    "get_all_template_variables": {"method": "GET", "path": "/configuration/v1/devices/template_variables"},
    "create_template_variables": {"method": "POST", "path": "/configuration/v1/devices/{serial}/template_variables",
                                   "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},
    "update_template_variables": {"method": "PATCH", "path": "/configuration/v1/devices/{serial}/template_variables",
                                   "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},
    "replace_template_variables": {"method": "PUT", "path": "/configuration/v1/devices/{serial}/template_variables",
                                    "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},
    "delete_template_variables": {"method": "DELETE", "path": "/configuration/v1/devices/{serial}/template_variables",
                                   "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},

    # AP Settings
    "get_ap_settings": {"method": "GET", "path": "/configuration/v2/ap_settings/{serial}",
                         "param_hints": {"serial": "Call get_aps or get_device_inventory(sku_type='IAP') to retrieve AP serial numbers."}},
    "update_ap_settings": {"method": "PATCH", "path": "/configuration/v2/ap_settings/{serial}",
                             "param_hints": {"serial": "Call get_aps or get_device_inventory(sku_type='IAP') to retrieve AP serial numbers."}},
    "get_ap_cli_config": {"method": "GET", "path": "/configuration/v1/ap_cli/{group_or_serial}",
                           "param_hints": {"group_or_serial": "Pass a group name (from get_groups) or an AP serial number (from get_aps)."}},
    "replace_ap_cli_config": {"method": "POST", "path": "/configuration/v1/ap_cli/{group_or_serial}",
                               "param_hints": {"group_or_serial": "Pass a group name (from get_groups) or an AP serial number (from get_aps)."}},

    # WLANs — GET uses /configuration/full_wlan, GET_ALL uses v1, CREATE/UPDATE use v2, DELETE uses v1
    "get_wlan": {"method": "GET", "path": "/configuration/full_wlan/{group_name}/{wlan_name}",
                  "param_hints": {"group_name": "Call get_groups to retrieve valid group names.", "wlan_name": "Call get_all_wlans(group_name=<name>) to retrieve WLAN names."}},
    "get_all_wlans": {"method": "GET", "path": "/configuration/v1/wlan/{group_name}",
                       "param_hints": {"group_name": "Call get_groups to retrieve valid group names. A 404 response means the group has no WLANs (switch-only group) — skip it and try the next group."}},
    "create_wlan": {"method": "POST", "path": "/configuration/v2/wlan/{group_name}",
                     "param_hints": {"group_name": "Call get_groups to retrieve valid group names."}},
    "update_wlan": {"method": "PATCH", "path": "/configuration/v2/wlan/{group_name}/{wlan_name}",
                     "param_hints": {"group_name": "Call get_groups to retrieve valid group names.", "wlan_name": "Call get_all_wlans(group_name=<name>) to retrieve WLAN names."}},
    "delete_wlan": {"method": "DELETE", "path": "/configuration/v1/wlan/{group_name}/{wlan_name}",
                     "param_hints": {"group_name": "Call get_groups to retrieve valid group names.", "wlan_name": "Call get_all_wlans(group_name=<name>) to retrieve WLAN names."}},

    # Device Inventory / Monitoring
    "get_device_inventory": {"method": "GET", "path": "/monitoring/v2/aps", "params": {"offset": 0, "limit": 50}},
    "get_aps": {"method": "GET", "path": "/monitoring/v2/aps", "params": {"offset": 0, "limit": 50}},
    "add_device_to_inventory": {"method": "POST", "path": "/platform/device_inventory/v1/devices"},
    "archive_devices": {"method": "POST", "path": "/platform/device_inventory/v1/devices/archive"},
    "unarchive_devices": {"method": "POST", "path": "/platform/device_inventory/v1/devices/unarchive"},

    # Licensing
    "get_subscription_keys": {"method": "GET", "path": "/platform/licensing/v1/subscriptions"},
    "get_enabled_services": {"method": "GET", "path": "/platform/licensing/v1/services/enabled"},
    "get_license_stats": {"method": "GET", "path": "/platform/licensing/v1/subscriptions/stats"},
    "get_license_service_config": {"method": "GET", "path": "/platform/licensing/v1/services/config"},
    "assign_subscription": {"method": "POST", "path": "/platform/licensing/v1/subscriptions/assign"},
    "unassign_subscription": {"method": "POST", "path": "/platform/licensing/v1/subscriptions/unassign"},
    "get_auto_license_services": {"method": "GET", "path": "/platform/licensing/v1/customer/settings/autolicense"},
    "assign_auto_license": {"method": "POST", "path": "/platform/licensing/v1/customer/settings/autolicense"},

    # Firmware
    "get_firmware_swarms": {"method": "GET", "path": "/firmware/v1/swarms"},
    "get_firmware_versions": {"method": "GET", "path": "/firmware/v1/versions"},
    "get_firmware_upgrade_status": {"method": "GET", "path": "/firmware/v1/status"},
    "upgrade_firmware": {"method": "POST", "path": "/firmware/v1/upgrade"},
    "cancel_firmware_upgrade": {"method": "POST", "path": "/firmware/v1/upgrade/cancel"},

    # Sites
    "get_sites": {"method": "GET", "path": "/central/v2/sites", "params": {"offset": 0, "limit": 20}},
    "create_site": {"method": "POST", "path": "/central/v2/sites"},
    "update_site": {"method": "PATCH", "path": "/central/v2/sites/{site_id}",
                     "param_hints": {"site_id": "Call get_sites to retrieve valid site IDs."}},
    "delete_site": {"method": "DELETE", "path": "/central/v2/sites/{site_id}",
                     "param_hints": {"site_id": "Call get_sites to retrieve valid site IDs."}},
    "associate_devices_to_site": {"method": "POST", "path": "/central/v2/sites/{site_id}/associate",
                                   "param_hints": {"site_id": "Call get_sites to retrieve valid site IDs."}},
    "unassociate_devices_from_site": {"method": "POST", "path": "/central/v2/sites/{site_id}/unassociate",
                                       "param_hints": {"site_id": "Call get_sites to retrieve valid site IDs."}},

    # Topology
    "get_topology_site": {"method": "GET", "path": "/topology_external_api/v1/sites"},
    "get_topology_devices": {"method": "GET", "path": "/topology_external_api/v1/devices"},
    "get_topology_edges": {"method": "GET", "path": "/topology_external_api/v1/edges"},
    "get_topology_uplinks": {"method": "GET", "path": "/topology_external_api/v1/uplinks"},
    "get_topology_tunnels": {"method": "GET", "path": "/topology_external_api/v1/tunnels"},
    "get_topology_ap_lldp_neighbors": {"method": "GET", "path": "/topology_external_api/v1/ap_lldp_neighbors"},

    # RAPIDS/WIDS
    "get_rogue_aps": {"method": "GET", "path": "/rapids/v1/rogue_aps"},
    "get_interfering_aps": {"method": "GET", "path": "/rapids/v1/interfering_aps"},
    "get_suspect_aps": {"method": "GET", "path": "/rapids/v1/suspect_aps"},
    "get_neighbor_aps": {"method": "GET", "path": "/rapids/v1/neighbor_aps"},
    "get_wids_infrastructure_attacks": {"method": "GET", "path": "/rapids/v1/wids/infrastructure_attacks"},
    "get_wids_client_attacks": {"method": "GET", "path": "/rapids/v1/wids/client_attacks"},
    "get_wids_events": {"method": "GET", "path": "/rapids/v1/wids/events"},

    # Audit Logs — paths verified against pycentral SDK
    "get_audit_trail_logs": {"method": "GET", "path": "/platform/auditlogs/v1/logs", "params": {"offset": 0, "limit": 20}},
    "get_event_logs": {"method": "GET", "path": "/auditlogs/v1/events", "params": {"offset": 0, "limit": 20}},
    "get_event_details": {"method": "GET", "path": "/auditlogs/v1/event_details/{event_id}",
                           "param_hints": {"event_id": "Call get_event_logs to retrieve valid event IDs."}},

    # VisualRF
    "get_visualrf_campus_list": {"method": "GET", "path": "/visualrf_api/v1/campus"},
    "get_visualrf_campus_info": {"method": "GET", "path": "/visualrf_api/v1/campus/{campus_id}"},
    "get_visualrf_building_info": {"method": "GET", "path": "/visualrf_api/v1/building/{building_id}"},
    "get_visualrf_floor_info": {"method": "GET", "path": "/visualrf_api/v1/floor/{floor_id}"},
    "get_visualrf_floor_aps": {"method": "GET", "path": "/visualrf_api/v1/floor/{floor_id}/access_point_location"},
    "get_visualrf_floor_clients": {"method": "GET", "path": "/visualrf_api/v1/floor/{floor_id}/client_location"},
    "get_visualrf_client_location": {"method": "GET", "path": "/visualrf_api/v1/client_location/{client_mac}"},
    "get_visualrf_rogue_location": {"method": "GET", "path": "/visualrf_api/v1/rogue_location/{rogue_mac}"},

    # User Management
    "list_users": {"method": "GET", "path": "/platform/rbac/v1/users"},
    "get_user": {"method": "GET", "path": "/platform/rbac/v1/users/{username}",
                  "param_hints": {"username": "Call list_users to retrieve valid usernames."}},
    "create_user": {"method": "POST", "path": "/platform/rbac/v1/users"},
    "update_user": {"method": "PATCH", "path": "/platform/rbac/v1/users/{username}",
                     "param_hints": {"username": "Call list_users to retrieve valid usernames."}},
    "delete_user": {"method": "DELETE", "path": "/platform/rbac/v1/users/{username}",
                     "param_hints": {"username": "Call list_users to retrieve valid usernames."}},
    "get_roles": {"method": "GET", "path": "/platform/rbac/v1/roles"},

    # MSP
    "get_msp_customers": {"method": "GET", "path": "/msp_api/v1/customers"},
    "create_msp_customer": {"method": "POST", "path": "/msp_api/v1/customers"},
    "get_msp_country_codes": {"method": "GET", "path": "/msp_api/v1/country_codes"},
    "get_msp_devices": {"method": "GET", "path": "/msp_api/v1/devices"},
    "get_msp_groups": {"method": "GET", "path": "/msp_api/v1/groups"},

    # Monitoring
    "get_all_reporting_radios": {"method": "GET", "path": "/monitoring/v2/aps", "params": {"offset": 0, "limit": 50}},
    "get_switches": {"method": "GET", "path": "/monitoring/v1/switches", "params": {"offset": 0, "limit": 50}},
    "get_gateways": {"method": "GET", "path": "/monitoring/v1/gateways", "params": {"offset": 0, "limit": 50}},
    "get_clients": {"method": "GET", "path": "/monitoring/v1/clients/wireless", "params": {"offset": 0, "limit": 50}},
    "get_wired_clients": {"method": "GET", "path": "/monitoring/v1/clients/wired", "params": {"offset": 0, "limit": 50}},

    # Phase 1 extended endpoints
    "get_wireless_clients": {"method": "GET", "path": "/monitoring/v1/clients/wireless", "params": {"offset": 0, "limit": 50}},
    "get_client_details": {"method": "GET", "path": "/monitoring/v1/clients/{macaddr}",
                            "param_hints": {"macaddr": "Pass the MAC address directly, e.g. macaddr='3C:0A:F3:9B:7E:51'."}},
    "get_client_count": {"method": "GET", "path": "/monitoring/v2/clients/count"},
    "get_alerts": {"method": "GET", "path": "/central/v1/notifications", "params": {"offset": 0, "limit": 20}},
    "get_alert_config": {"method": "GET", "path": "/central/v1/notifications/settings"},
    "acknowledge_alert": {"method": "POST", "path": "/central/v1/notifications/{alert_id}",
                           "param_hints": {"alert_id": "Call get_alerts to retrieve valid alert IDs."}},
    "get_ap_details": {"method": "GET", "path": "/monitoring/v1/aps/{serial}",
                        "param_hints": {"serial": "Call get_aps or get_device_inventory(sku_type='IAP') to retrieve AP serial numbers."}},
    "get_switch_details": {"method": "GET", "path": "/monitoring/v1/switches/{serial}",
                            "param_hints": {"serial": "Call get_switches to retrieve switch serial numbers."}},
    "get_gateway_details": {"method": "GET", "path": "/monitoring/v1/gateways/{serial}",
                             "param_hints": {"serial": "Call get_gateways to retrieve gateway serial numbers."}},
    "get_ap_rf_summary": {"method": "GET", "path": "/monitoring/v1/aps/rf_summary"},
    "get_switch_ports": {"method": "GET", "path": "/monitoring/v1/switches/{serial}/ports",
                          "param_hints": {"serial": "Call get_switches to retrieve switch serial numbers."}},
    "get_switch_port_details": {"method": "GET", "path": "/monitoring/v1/switches/{serial}/ports/{port}",
                                 "param_hints": {"serial": "Call get_switches to retrieve switch serial numbers."}},
    "get_device_tunnels": {"method": "GET", "path": "/monitoring/v1/devices/{serial}/tunnels",
                            "param_hints": {"serial": "Call get_device_inventory, get_aps, or get_switches to retrieve device serial numbers."}},
    "get_ap_neighbors": {"method": "GET", "path": "/monitoring/v1/aps/{serial}/neighbors",
                          "param_hints": {"serial": "Call get_aps or get_device_inventory(sku_type='IAP') to retrieve AP serial numbers."}},
    "get_networks": {"method": "GET", "path": "/monitoring/v2/networks", "params": {"offset": 0, "limit": 50}},
    "get_wan_uplinks": {"method": "GET", "path": "/monitoring/v1/wan/uplinks"},
    "get_wan_uplink_bandwidth": {"method": "GET", "path": "/monitoring/v1/wan/uplinks/bandwidth/{serial}",
                                  "param_hints": {"serial": "Call get_device_inventory or get_gateways to retrieve device serial numbers."}},
    "get_wan_tunnels": {"method": "GET", "path": "/monitoring/v1/wan/tunnels"},
    "get_presence_analytics": {"method": "GET", "path": "/presence/v1/analytics/sites"},
    "get_presence_trend": {"method": "GET", "path": "/presence/v1/analytics/trend"},
    "get_guest_portals": {"method": "GET", "path": "/guest/v1/portals"},
    "get_guest_visitors": {"method": "GET", "path": "/guest/v1/portals/{portal_id}/visitors",
                            "param_hints": {"portal_id": "Call get_guest_portals to retrieve valid portal IDs."}},
    "create_guest_visitor": {"method": "POST", "path": "/guest/v1/portals/{portal_id}/visitors",
                              "param_hints": {"portal_id": "Call get_guest_portals to retrieve valid portal IDs."}},
}


# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], "The messages in the conversation"]
    filtered_tool_names: Annotated[list[str], "Names of tools filtered for this query"]
    tool_failure_counts: Annotated[dict, "Tracks consecutive failure counts per tool to break retry loops"]


class MCPToolManager:
    """
    Manages TWO tool sources:
    1. Phase 1: Direct httpx API calls to Aruba Central (fast, no subprocess)
    2. Phase 2: SSH/CLI via MCP server subprocess (Netmiko)
    """

    def __init__(self):
        self.langchain_tools = {}
        self.tool_names = []
        self.tool_sources = {}  # tool_name -> "Phase1-API" or "Phase2-SSH"

        # Aruba Central API config
        self.base_url = os.getenv("ARUBA_CENTRAL_BASE_URL", "")
        self.token = os.getenv("ARUBA_CENTRAL_TOKEN", "")
        self.client_id = os.getenv("ARUBA_CENTRAL_CLIENT_ID", "")
        self.client_secret = os.getenv("ARUBA_CENTRAL_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("ARUBA_CENTRAL_REFRESH_TOKEN", "")
        self.timeout = int(os.getenv("ARUBA_CENTRAL_TIMEOUT", "30"))

        # SSH MCP server session
        self.ssh_session = None
        self.ssh_transport = None

    async def connect(self):
        """Connect to Phase 1 (API) and Phase 2 (SSH MCP server)."""
        import httpx
        print(f"\n{Colors.OKBLUE}═══ Connecting to Tool Sources ═══{Colors.ENDC}")

        self.http_client = httpx.AsyncClient(timeout=self.timeout)

        # ── Phase 1: Aruba Central API ──
        print(f"\n{Colors.OKBLUE}Phase 1: Aruba Central REST API{Colors.ENDC}")
        print(f"  Base URL: {self.base_url}")

        # Auto-refresh token
        print(f"  Refreshing access token...")
        refreshed = await self._do_refresh_token()
        if refreshed:
            print(f"{Colors.OKGREEN}  ✓ Token refreshed: {self.token[:15]}...{Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}  ⚠ Token refresh failed — using existing{Colors.ENDC}")

        # Load Phase 1 API tools from registry
        from tool_registry import TOOL_REGISTRY
        api_count = 0
        for tool_name, metadata in TOOL_REGISTRY.items():
            self.tool_names.append(tool_name)
            self.langchain_tools[tool_name] = self._create_api_tool(tool_name, metadata)
            self.tool_sources[tool_name] = "Phase1-API"
            api_count += 1

        print(f"{Colors.OKGREEN}  ✓ Phase 1: {api_count} API tools loaded{Colors.ENDC}")

        # ── Phase 2: SSH MCP Server ──
        ssh_count = await self._connect_ssh_server()

        # ── Summary ──
        total = api_count + ssh_count
        print(f"\n{Colors.OKGREEN}{'─' * 50}{Colors.ENDC}")
        print(f"{Colors.OKGREEN}  Total: {total} tools ({api_count} API + {ssh_count} SSH){Colors.ENDC}")
        print(f"{Colors.OKGREEN}{'─' * 50}{Colors.ENDC}")

    async def _connect_ssh_server(self) -> int:
        """Connect to Phase 2 SSH MCP server."""
        print(f"\n{Colors.OKBLUE}Phase 2: Aruba SSH/CLI (Netmiko){Colors.ENDC}")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        ssh_script = os.path.join(script_dir, "aruba_ssh_mcp_server.py")

        if not os.path.exists(ssh_script):
            print(f"{Colors.WARNING}  ⚠ aruba_ssh_mcp_server.py not found — Phase 2 skipped{Colors.ENDC}")
            return 0

        try:
            env = os.environ.copy()
            server_params = StdioServerParameters(
                command="python",
                args=[ssh_script],
                env=env
            )

            self.ssh_transport = stdio_client(server_params)
            stdio, write = await self.ssh_transport.__aenter__()
            self.ssh_session = ClientSession(stdio, write)
            await self.ssh_session.__aenter__()
            await self.ssh_session.initialize()

            tools_response = await self.ssh_session.list_tools()

            ssh_count = 0
            for mcp_tool in tools_response.tools:
                tool_name = mcp_tool.name
                self.tool_names.append(tool_name)
                self.langchain_tools[tool_name] = self._create_ssh_tool(mcp_tool)
                self.tool_sources[tool_name] = "Phase2-SSH"
                ssh_count += 1

            print(f"{Colors.OKGREEN}  ✓ Phase 2: {ssh_count} SSH tools loaded{Colors.ENDC}")
            return ssh_count

        except Exception as e:
            print(f"{Colors.FAIL}  ✗ Phase 2 failed: {str(e)}{Colors.ENDC}")
            print(f"{Colors.WARNING}  Agent will run with Phase 1 (API) tools only{Colors.ENDC}")
            return 0

    def _create_api_tool(self, tool_name: str, metadata: dict):
        """Create a LangChain tool for Phase 1 (direct API call)."""
        description = metadata["description"]
        manager = self

        @langchain_tool
        async def execute_tool(**kwargs) -> str:
            """Execute an Aruba Central API call."""
            endpoint = API_ENDPOINTS.get(tool_name)
            if not endpoint:
                return json.dumps({"error": True, "detail": f"No endpoint mapping for {tool_name}"})

            method = endpoint["method"]
            path_template = endpoint["path"]
            default_params = endpoint.get("params", {})

            # Unwrap if the LLM mistakenly nested all args inside a 'kwargs' key
            if len(kwargs) == 1 and "kwargs" in kwargs and isinstance(kwargs.get("kwargs"), dict):
                kwargs = kwargs["kwargs"]

            clean_kwargs = {k: v for k, v in kwargs.items() if v is not None}
            path_params = {}
            other_params = {}

            for key, value in clean_kwargs.items():
                if f"{{{key}}}" in path_template:
                    path_params[key] = value
                else:
                    other_params[key] = value

            for k, v in default_params.items():
                if k not in other_params:
                    other_params[k] = v

            try:
                path = path_template.format(**path_params)
            except KeyError as e:
                missing = str(e).strip("'")
                param_hints = endpoint.get("param_hints", {})
                hint = param_hints.get(missing, "")
                detail = f"Missing required path parameter: '{missing}'."
                if hint:
                    detail += f" {hint}"
                return json.dumps({"error": True, "detail": detail})

            url = f"{manager.base_url}{path}"
            headers = {"Authorization": f"Bearer {manager.token}", "Content-Type": "application/json"}

            try:
                response = await manager._make_request(method, url, headers, other_params, endpoint)

                if response.status_code == 401:
                    refreshed = await manager._do_refresh_token()
                    if refreshed:
                        headers["Authorization"] = f"Bearer {manager.token}"
                        response = await manager._make_request(method, url, headers, other_params, endpoint)

                if 200 <= response.status_code < 300:
                    try:
                        return json.dumps(response.json(), indent=2)
                    except Exception:
                        return response.text
                else:
                    return json.dumps({"error": True, "status_code": response.status_code, "detail": response.text[:500]})
            except Exception as e:
                return json.dumps({"error": True, "detail": str(e)})

        execute_tool.name = tool_name
        execute_tool.description = description
        return execute_tool

    def _create_ssh_tool(self, mcp_tool):
        """Create a LangChain tool for Phase 2 (SSH via MCP server)."""
        tool_name = mcp_tool.name
        tool_description = mcp_tool.description or f"Execute {tool_name}"
        session = self.ssh_session

        @langchain_tool
        async def execute_ssh_tool(**kwargs) -> str:
            """Execute an SSH command via MCP server."""
            try:
                result = await session.call_tool(tool_name, arguments=kwargs)
                if result.content:
                    text_parts = [item.text for item in result.content if hasattr(item, 'text')]
                    return "\n".join(text_parts) if text_parts else str(result.content)
                return "Tool executed successfully (no output)"
            except Exception as e:
                return json.dumps({"error": True, "detail": f"SSH tool error: {str(e)}"})

        execute_ssh_tool.name = tool_name
        execute_ssh_tool.description = tool_description
        return execute_ssh_tool

    async def _make_request(self, method, url, headers, params, endpoint):
        if method == "GET":
            return await self.http_client.get(url, params=params, headers=headers)
        elif method == "POST":
            if endpoint.get("type") == "form":
                return await self.http_client.post(url, data=params, headers={"Content-Type": "application/x-www-form-urlencoded"})
            else:
                return await self.http_client.post(url, json=params, headers=headers)
        elif method == "PATCH":
            return await self.http_client.patch(url, json=params, headers=headers)
        elif method == "PUT":
            return await self.http_client.put(url, json=params, headers=headers)
        elif method == "DELETE":
            return await self.http_client.delete(url, params=params, headers=headers)

    async def _do_refresh_token(self) -> bool:
        try:
            response = await self.http_client.post(
                f"{self.base_url}/oauth2/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("access_token", self.token)
                new_refresh = data.get("refresh_token", "")
                if new_refresh:
                    self.refresh_token = new_refresh
                return True
            return False
        except Exception:
            return False

    def get_tools_by_names(self, names: list[str]):
        return [self.langchain_tools[n] for n in names if n in self.langchain_tools]

    async def disconnect(self):
        if hasattr(self, 'http_client'):
            await self.http_client.aclose()
        if self.ssh_session:
            try:
                await self.ssh_session.__aexit__(None, None, None)
            except Exception:
                pass
        print(f"{Colors.OKBLUE}Disconnected from all sources{Colors.ENDC}")


class ArubaLangGraphAgent:
    def __init__(self, tool_manager: MCPToolManager, semantic_filter: SemanticToolFilter):
        self.tool_manager = tool_manager
        self.semantic_filter = semantic_filter

        print(f"\n{Colors.OKBLUE}Initializing Ollama LLM: {OLLAMA_MODEL}...{Colors.ENDC}")
        self.llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_URL, temperature=0)
        self._build_graph()
        print(f"{Colors.OKGREEN}LangGraph agent v2 initialized{Colors.ENDC}")

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("filter_tools", self._filter_tools_node)
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("execute_tools", self._execute_tools_node)

        workflow.set_entry_point("filter_tools")
        workflow.add_edge("filter_tools", "agent")
        workflow.add_conditional_edges("agent", self._should_continue, {"continue": "execute_tools", "end": END})
        workflow.add_edge("execute_tools", "agent")
        self.graph = workflow.compile()

    async def _filter_tools_node(self, state: AgentState) -> AgentState:
        user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
        if not user_msgs:
            return {**state, "filtered_tool_names": []}

        query = user_msgs[-1].content.lower()

        # BLOCKED TOOLS - known 404 on this instance
        blocked_tools = {
            "get_topology_devices", "get_topology_edges", "get_topology_uplinks",
            "get_topology_tunnels", "get_topology_site"
        }

        # ALWAYS INCLUDE for broad queries
        always_include_keywords = ["network", "summary", "overview", "health", "status",
                                   "everything", "understand", "topology", "architecture",
                                   "what do i have", "show me all", "full", "complete",
                                   "troubleshoot", "diagnose", "problem", "issue", "wrong"]

        essential_tools = ["get_device_inventory", "get_sites"]

        # Keyword overrides — Phase 1 API tools
        keyword_tools = {
            "switch": ["get_device_inventory", "get_switches"],
            "ap ": ["get_device_inventory", "get_ap_settings"],
            "ap?": ["get_device_inventory", "get_ap_settings"],
            "aps": ["get_device_inventory", "get_aps"],
            "access point": ["get_device_inventory", "get_aps"],
            "online": ["get_device_inventory"],
            "offline": ["get_device_inventory"],
            "down": ["get_device_inventory", "get_alerts"],
            "site": ["get_sites"],
            "group": ["get_groups"],
            "client": ["get_clients", "get_client_count"],
            "macaddr": ["get_client_details"],
            "mac address": ["get_client_details", "get_mac_address_table"],
            "verify": ["get_client_details", "get_clients"],
            "legitimate": ["get_client_details", "get_wids_client_attacks"],
            "wireless client": ["get_wireless_clients", "get_client_count"],
            "wired client": ["get_wired_clients"],
            "how many client": ["get_client_count"],
            "how many user": ["get_client_count"],
            "gateway": ["get_gateways"],
            "inventory": ["get_device_inventory"],
            "device": ["get_device_inventory"],
            "wlan": ["get_all_wlans", "get_wlan"],
            "ssid": ["get_all_wlans", "get_wlan"],
            "firmware": ["get_firmware_versions", "get_firmware_upgrade_status"],
            "upgrade": ["get_firmware_versions", "get_firmware_upgrade_status"],
            "license": ["get_subscription_keys", "get_license_stats"],
            "rogue": ["get_rogue_aps"],
            "alert": ["get_alerts"],
            "notification": ["get_alerts"],
            "critical": ["get_alerts"],
            "warning": ["get_alerts"],
            "user": ["list_users", "get_user"],
            "template": ["get_templates", "get_all_template_variables"],
            "audit": ["get_audit_trail_logs"],
            "log": ["get_audit_trail_logs", "get_event_logs"],
            "network": ["get_device_inventory", "get_sites", "get_networks"],
            "summary": ["get_device_inventory", "get_sites", "get_client_count"],
            "health": ["get_device_inventory", "get_aps", "get_switches", "get_alerts"],
            "security": ["get_rogue_aps", "get_suspect_aps", "get_wids_events"],
            "wids": ["get_wids_events", "get_wids_client_attacks"],
            "event": ["get_event_logs"],
            "config": ["get_device_configuration"],
            "wan": ["get_wan_uplinks", "get_wan_tunnels"],
            "guest": ["get_guest_portals", "get_guest_visitors"],
            "presence": ["get_presence_analytics", "get_presence_trend"],
            "port": ["get_switch_ports"],
            "rf": ["get_ap_rf_summary"],
            "interference": ["get_ap_rf_summary", "get_interfering_aps"],

            # Phase 2 SSH keyword triggers
            "ospf": ["get_ospf_neighbors", "get_route_table"],
            "bgp": ["get_bgp_summary", "get_route_table"],
            "eigrp": ["run_show_command"],
            "route": ["get_route_table"],
            "routing": ["get_route_table", "get_ospf_neighbors", "get_bgp_summary"],
            "arp": ["get_arp_table"],
            "mac address": ["get_mac_address_table"],
            "mac table": ["get_mac_address_table"],
            "vlan": ["get_vlan_info"],
            "spanning tree": ["get_spanning_tree"],
            "stp": ["get_spanning_tree"],
            "lldp": ["get_lldp_neighbors"],
            "cdp": ["get_lldp_neighbors"],
            "acl": ["get_access_lists"],
            "access list": ["get_access_lists"],
            "aaa": ["get_aaa_status"],
            "radius": ["get_aaa_status"],
            "tacacs": ["get_aaa_status"],
            "ntp": ["get_ntp_status"],
            "time sync": ["get_ntp_status"],
            "security audit": ["audit_security_posture"],
            "security posture": ["audit_security_posture"],
            "compliance": ["audit_security_posture"],
            "cis": ["audit_security_posture"],
            "benchmark": ["audit_security_posture"],
            "cpu": ["get_cpu_memory_detail"],
            "memory": ["get_cpu_memory_detail"],
            "resource": ["get_cpu_memory_detail"],
            "fan": ["get_environment"],
            "temperature": ["get_environment"],
            "power supply": ["get_environment", "get_poe_status"],
            "poe": ["get_poe_status"],
            "psu": ["get_environment"],
            "syslog": ["get_device_logs"],
            "device log": ["get_device_logs"],
            "uptime": ["get_system_info"],
            "version": ["get_system_info"],
            "hostname": ["get_system_info"],
            "serial number": ["get_system_info"],
            "running config": ["get_running_config"],
            "startup config": ["get_startup_config"],
            "config drift": ["compare_configs"],
            "config diff": ["compare_configs"],
            "show command": ["run_show_command"],
            "ssh": ["run_show_command"],
            "cli": ["run_show_command"],
            "interface error": ["get_interface_errors"],
            "interface status": ["get_interface_status"],
            "bounce": ["bounce_interface"],
            "reset port": ["bounce_interface"],
            "shut": ["bounce_interface"],
            "push config": ["push_config_commands"],
            "backup": ["backup_config"],
            "save config": ["save_config"],
            "write mem": ["save_config"],
            "vrf": ["get_vrf_info"],
        }

        # Collect keyword-matched tools
        boosted = []

        if any(kw in query for kw in always_include_keywords):
            for t in essential_tools:
                if t not in boosted:
                    boosted.append(t)

        for keyword, tools in keyword_tools.items():
            if keyword in query:
                for t in tools:
                    if t not in boosted:
                        boosted.append(t)

        # Get semantic filtered tools
        filtered = self.semantic_filter.filter(query, top_k=TOP_K_TOOLS)

        # Merge: boosted first, then semantic
        final = list(boosted)
        for t in filtered:
            if t not in final:
                final.append(t)

        # Remove blocked tools
        final = [t for t in final if t not in blocked_tools]

        # Only keep tools that actually exist in our loaded tools
        final = [t for t in final if t in self.tool_manager.langchain_tools]

        final = final[:TOP_K_TOOLS]

        print(f"\n{Colors.OKCYAN}🔍 Filtered tools ({len(final)}/{len(self.tool_manager.tool_names)}):{Colors.ENDC}")
        for i, name in enumerate(final, 1):
            source = self.tool_manager.tool_sources.get(name, "?")
            marker = " ⭐" if name in boosted else ""
            print(f"  {i}. {name} [{source}]{marker}")
        print()
        return {**state, "filtered_tool_names": final}

    async def _agent_node(self, state: AgentState) -> AgentState:
        tools = self.tool_manager.get_tools_by_names(state.get("filtered_tool_names", []))
        llm = self.llm.bind_tools(tools)

        system_prompt = SystemMessage(content="""You are an expert Aruba network engineer AI assistant with TWO tool sources:

PHASE 1 - Aruba Central API (cloud monitoring):
- get_device_inventory, get_aps, get_switches, get_gateways — device status
- get_clients, get_client_count — connected users
- get_client_details — get details for a specific client; pass the MAC address as macaddr="XX:XX:XX:XX:XX:XX"
- get_alerts — active alerts
- get_sites — returns all sites (no required params)
- get_groups — returns all groups (no required params)
- get_all_wlans(group_name) — REQUIRES group_name; returns WLANs for ONE group
- get_rogue_aps, get_wids_events — security

PHASE 2 - SSH/CLI (direct device access):
- run_show_command — run ANY CLI command on a device
- get_ospf_neighbors, get_bgp_summary, get_route_table — routing protocols
- get_interface_status, get_interface_errors — interface troubleshooting
- get_mac_address_table, get_vlan_info, get_spanning_tree — L2 info
- get_access_lists, get_aaa_status, get_ntp_status — security audit
- audit_security_posture — comprehensive security check
- get_cpu_memory_detail, get_device_logs, get_environment — deep health
- get_running_config, compare_configs — config management
- push_config_commands, backup_config, save_config — config changes

CRITICAL RULES:
1. ALWAYS call tools immediately. NEVER describe what you would do - just DO IT.
2. Call MULTIPLE tools in parallel when possible.
3. If a tool fails, AUTOMATICALLY try alternatives without asking.
4. SSH tools need device_ip parameter — ask the user for it if not provided.
5. For inventory queries, use get_device_inventory with sku_type parameter: IAP for APs, ArubaSwitch for switches.
6. Present data in organized tables or bullet points.
7. NEVER say "Would you like me to try?" — just try it automatically.
8. For SSH tools, the default device_type is aruba_oscx. User can override.
9. ALWAYS pass parameters directly (e.g., group_name="Airowire-IAP"), NEVER nest them inside a 'kwargs' dict.

KNOWN BROKEN TOOLS (DO NOT USE):
- get_topology_devices, get_topology_edges, get_topology_uplinks, get_topology_tunnels, get_topology_site

MULTI-STEP WLAN WORKFLOW (use this exact pattern):
- Step 1: call get_groups (no params needed) to get all group names
- Step 2: from the groups result, call get_all_wlans(group_name=<name>) for EACH group one by one
- Step 3: if a group returns 404, it has no WLANs (switch/non-wireless group) — skip it, move to next group
- Step 4: after iterating all groups, summarize all WLANs found

MULTI-STEP EXAMPLES:
- "WLAN/wireless config" → first call get_groups, then call get_all_wlans for each group in sequence
- "site, group, WLAN config" → call get_sites AND get_groups in parallel; then call get_all_wlans for each group one by one
- "network summary" → call get_device_inventory, get_sites, get_client_count, get_alerts in parallel; then get WLANs per group
- "device config" → first call get_device_inventory or get_aps/get_switches to obtain serial numbers, then call get_device_configuration(serial=<serial>)
- "AP settings" → first call get_aps to get serial numbers, then call get_ap_settings(serial=<serial>)
- "OSPF on 10.1.1.1" → call get_ospf_neighbors(device_ip="10.1.1.1")
- "security audit on 10.1.1.5" → call audit_security_posture(device_ip="10.1.1.5")
- "compare configs on switch" → call compare_configs(device_ip="x.x.x.x")

TOOLS THAT REQUIRE PRIOR LOOKUP:
- get_device_configuration, get_device_config_details, get_ap_settings: need serial → call get_aps/get_switches first
- get_all_wlans: needs group_name → call get_groups first
- get_wlan: needs group_name AND wlan_name → call get_groups, then get_all_wlans
- get_switch_ports, get_switch_details: need serial → call get_switches first
- get_ap_details, get_ap_neighbors: need serial → call get_aps first
""")

        messages = [system_prompt] + list(state["messages"])
        try:
            response = await llm.ainvoke(messages)
        except Exception as e:
            print(f"{Colors.FAIL}LLM Error: {e}{Colors.ENDC}")
            response = AIMessage(content=f"Error: {e}")

        if hasattr(response, "tool_calls") and response.tool_calls:
            print(f"{Colors.OKBLUE}🤖 LLM wants to call {len(response.tool_calls)} tool(s){Colors.ENDC}")
        elif hasattr(response, "content") and response.content:
            preview = response.content[:200]
            print(f"{Colors.OKBLUE}🤖 LLM response: {preview}...{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}🤖 LLM returned EMPTY response! Forcing retry...{Colors.ENDC}")
            nudge = HumanMessage(content="You returned an empty response. Based on the tool results above, please provide a clear summary. Never return empty.")
            try:
                retry_response = await llm.ainvoke(messages + [response, nudge])
                if hasattr(retry_response, "content") and retry_response.content:
                    print(f"{Colors.OKGREEN}🤖 Retry successful!{Colors.ENDC}")
                    return {**state, "messages": list(state["messages"]) + [retry_response]}
            except Exception as e:
                print(f"{Colors.FAIL}Retry failed: {e}{Colors.ENDC}")
            fallback = AIMessage(content="I retrieved some data but encountered issues. Please try a more specific query.")
            return {**state, "messages": list(state["messages"]) + [fallback]}
        return {**state, "messages": list(state["messages"]) + [response]}

    async def _execute_tools_node(self, state: AgentState) -> AgentState:
        last = state["messages"][-1]
        if not hasattr(last, "tool_calls") or not last.tool_calls:
            return state

        failure_counts = dict(state.get("tool_failure_counts") or {})
        msgs = []
        for tc in last.tool_calls:
            name, args = tc["name"], tc.get("args", {})
            source = self.tool_manager.tool_sources.get(name, "?")
            print(f"{Colors.WARNING}🔧 Executing: {name} [{source}]{Colors.ENDC}")
            if args:
                print(f"   Args: {json.dumps(args, indent=2)}")

            # Track failures per (tool_name + args) so that different arguments
            # (e.g. different group_name values) are counted independently.
            # This prevents blocking get_all_wlans for group B just because group A returned 404.
            try:
                failure_key = f"{name}::{json.dumps(args, sort_keys=True)}"
            except Exception:
                failure_key = f"{name}::{str(args)}"

            if name in self.tool_manager.langchain_tools:
                try:
                    invocation_result = await self.tool_manager.langchain_tools[name].ainvoke(args)
                    result_str = str(invocation_result)
                    # Check if the result indicates an error
                    try:
                        result_data = json.loads(result_str)
                        if isinstance(result_data, dict) and result_data.get("error"):
                            failure_counts[failure_key] = failure_counts.get(failure_key, 0) + 1
                        else:
                            failure_counts[failure_key] = 0  # Reset on success
                    except Exception:
                        failure_counts[failure_key] = 0  # Reset on non-JSON success

                    if failure_counts.get(failure_key, 0) >= MAX_TOOL_FAILURES:
                        result_str = json.dumps({
                            "error": True,
                            "detail": f"Tool '{name}' has failed {failure_counts[failure_key]} times with the same arguments. "
                                      "STOP calling this tool with these arguments and try different parameters or a different approach."
                        })
                        print(f"{Colors.FAIL}⛔ Blocking '{name}' after repeated failures with same args{Colors.ENDC}\n")
                    elif len(result_str) > 500:
                        print(f"{Colors.OKGREEN}✓ Done ({len(result_str)} chars){Colors.ENDC}")
                        print(f"   Preview: {result_str[:300]}...\n")
                    else:
                        print(f"{Colors.OKGREEN}✓ Done ({len(result_str)} chars){Colors.ENDC}")
                        print(f"   Result: {result_str}\n")
                except Exception as e:
                    result_str = json.dumps({"error": True, "detail": str(e)})
                    failure_counts[failure_key] = failure_counts.get(failure_key, 0) + 1
                    print(f"{Colors.FAIL}✗ Failed: {e}{Colors.ENDC}\n")
                msgs.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))

        return {**state, "messages": list(state["messages"]) + msgs, "tool_failure_counts": failure_counts}

    def _should_continue(self, state: AgentState):
        last = state["messages"][-1]
        return "continue" if hasattr(last, "tool_calls") and last.tool_calls else "end"

    async def run(self, query: str):
        result = await self.graph.ainvoke(
            {"messages": [HumanMessage(content=query)], "filtered_tool_names": [], "tool_failure_counts": {}},
            {"recursion_limit": 50}
        )
        final = result["messages"][-1]
        return final.content if hasattr(final, "content") else str(final)


async def main():
    print(f"\n{Colors.HEADER}{'═' * 80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}  🌐 Aruba Network AI Agent v2 — Phase 1 (API) + Phase 2 (SSH)  {Colors.ENDC}")
    print(f"{Colors.HEADER}{'═' * 80}{Colors.ENDC}\n")
    print(f"  Model:  {OLLAMA_MODEL}")
    print(f"  Ollama: {OLLAMA_URL}")
    print(f"  Top-K:  {TOP_K_TOOLS}")

    semantic_filter = SemanticToolFilter()
    tool_manager = MCPToolManager()

    try:
        await tool_manager.connect()
        agent = ArubaLangGraphAgent(tool_manager, semantic_filter)
        print(f"\n{Colors.OKGREEN}{'─' * 60}{Colors.ENDC}")
        print(f"{Colors.OKGREEN}  Ready! Type your queries or 'quit' to exit.{Colors.ENDC}")
        print(f"{Colors.OKCYAN}  Phase1-API = Aruba Central cloud monitoring{Colors.ENDC}")
        print(f"{Colors.OKCYAN}  Phase2-SSH = Direct device CLI (OSPF, BGP, ACL, configs...){Colors.ENDC}")
        print(f"{Colors.OKGREEN}{'─' * 60}{Colors.ENDC}\n")

        while True:
            try:
                query = input(f"{Colors.BOLD}You:{Colors.ENDC} ").strip()
                if not query:
                    continue
                if query.lower() in ["quit", "exit", "q"]:
                    print(f"\n{Colors.OKBLUE}Goodbye!{Colors.ENDC}\n")
                    break

                print(f"\n{Colors.OKBLUE}Processing...{Colors.ENDC}\n")
                start = datetime.now()
                response = await agent.run(query)
                elapsed = (datetime.now() - start).total_seconds()

                print(f"\n{Colors.OKGREEN}{Colors.BOLD}A:{Colors.ENDC} {response}\n")
                print(f"{Colors.OKCYAN}[Completed in {elapsed:.2f}s]{Colors.ENDC}\n")
                print("─" * 80 + "\n")

            except KeyboardInterrupt:
                print(f"\n\n{Colors.OKBLUE}Goodbye!{Colors.ENDC}\n")
                break
            except Exception as e:
                print(f"\n{Colors.FAIL}Error: {e}{Colors.ENDC}\n")
    finally:
        await tool_manager.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted")
        sys.exit(0)