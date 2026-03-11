"""
LangGraph ReAct Agent for Aruba Central MCP Server

Integrates semantic tool filtering with LangGraph and Ollama for 100% local
LLM execution. Uses direct Aruba Central API calls with correct endpoint paths.

Auto-refreshes token on startup and on 401 errors.
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
from dotenv import load_dotenv

from tool_filter import SemanticToolFilter

# Load environment variables
load_dotenv()



# Configuration
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
TOP_K_TOOLS = int(os.getenv("TOP_K_TOOLS", "8"))


# ══════════════════════════════════════════════════════════════════════════════
# Real Aruba Central API endpoint mapping
# "params" = required query parameters with default values
# ══════════════════════════════════════════════════════════════════════════════

API_ENDPOINTS = {
    # OAuth
    "refresh_api_token": {"method": "POST", "path": "/oauth2/token", "type": "form"},

    # Groups
    "get_groups": {"method": "GET", "path": "/configuration/v2/groups", "params": {"offset": 0, "limit": 20}},
    "get_group_template_info": {"method": "GET", "path": "/configuration/v1/groups/template_info"},
    "create_group": {"method": "POST", "path": "/configuration/v2/groups"},
    "clone_group": {"method": "POST", "path": "/configuration/v2/groups/clone"},
    "delete_group": {"method": "DELETE", "path": "/configuration/v2/groups/{group_name}"},

    # Devices Config
    "get_device_group": {"method": "GET", "path": "/configuration/v1/devices/{serial}/group"},
    "get_device_configuration": {"method": "GET", "path": "/configuration/v1/devices/{serial}/configuration"},
    "get_device_config_details": {"method": "GET", "path": "/configuration/v1/devices/{serial}/config_details"},
    "get_device_templates": {"method": "GET", "path": "/configuration/v1/devices/{serial}/templates"},
    "get_group_device_templates": {"method": "GET", "path": "/configuration/v1/groups/{group_name}/templates"},
    "set_switch_ssh_credentials": {"method": "POST", "path": "/configuration/v1/devices/{serial}/ssh_credentials"},
    "move_devices": {"method": "POST", "path": "/configuration/v1/devices/move"},

    # Templates
    "get_templates": {"method": "GET", "path": "/configuration/v1/groups/{group_name}/templates"},
    "get_template_text": {"method": "GET", "path": "/configuration/v1/groups/{group_name}/templates/{template_name}"},
    "delete_template": {"method": "DELETE", "path": "/configuration/v1/groups/{group_name}/templates/{template_name}"},

    # Template Variables
    "get_template_variables": {"method": "GET", "path": "/configuration/v1/devices/{serial}/template_variables"},
    "get_all_template_variables": {"method": "GET", "path": "/configuration/v1/devices/template_variables"},
    "create_template_variables": {"method": "POST", "path": "/configuration/v1/devices/{serial}/template_variables"},
    "update_template_variables": {"method": "PATCH", "path": "/configuration/v1/devices/{serial}/template_variables"},
    "replace_template_variables": {"method": "PUT", "path": "/configuration/v1/devices/{serial}/template_variables"},
    "delete_template_variables": {"method": "DELETE", "path": "/configuration/v1/devices/{serial}/template_variables"},

    # AP Settings
    "get_ap_settings": {"method": "GET", "path": "/configuration/v2/ap_settings/{serial}"},
    "update_ap_settings": {"method": "PATCH", "path": "/configuration/v2/ap_settings/{serial}"},
    "get_ap_cli_config": {"method": "GET", "path": "/configuration/v1/ap_cli/{group_or_serial}"},
    "replace_ap_cli_config": {"method": "POST", "path": "/configuration/v1/ap_cli/{group_or_serial}"},

    # WLANs
    "get_wlan": {"method": "GET", "path": "/configuration/v2/wlan/{group_name}/{wlan_name}"},
    "get_all_wlans": {"method": "GET", "path": "/configuration/v2/wlan/{group_name}"},
    "create_wlan": {"method": "POST", "path": "/configuration/v2/wlan/{group_name}"},
    "update_wlan": {"method": "PATCH", "path": "/configuration/v2/wlan/{group_name}/{wlan_name}"},
    "delete_wlan": {"method": "DELETE", "path": "/configuration/v2/wlan/{group_name}/{wlan_name}"},

    # Device Inventory — use monitoring/v2/aps + monitoring/v1/switches combined
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
    "update_site": {"method": "PATCH", "path": "/central/v2/sites/{site_id}"},
    "delete_site": {"method": "DELETE", "path": "/central/v2/sites/{site_id}"},
    "associate_devices_to_site": {"method": "POST", "path": "/central/v2/sites/{site_id}/associate"},
    "unassociate_devices_from_site": {"method": "POST", "path": "/central/v2/sites/{site_id}/unassociate"},

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

    # Audit Logs
    "get_audit_trail_logs": {"method": "GET", "path": "/auditlogs/v2/logs", "params": {"offset": 0, "limit": 20}},
    "get_event_logs": {"method": "GET", "path": "/auditlogs/v2/events", "params": {"offset": 0, "limit": 20}},
    "get_event_details": {"method": "GET", "path": "/auditlogs/v2/event_details/{event_id}"},

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
    "get_user": {"method": "GET", "path": "/platform/rbac/v1/users/{username}"},
    "create_user": {"method": "POST", "path": "/platform/rbac/v1/users"},
    "update_user": {"method": "PATCH", "path": "/platform/rbac/v1/users/{username}"},
    "delete_user": {"method": "DELETE", "path": "/platform/rbac/v1/users/{username}"},
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


class MCPToolManager:
    """Manages direct API calls to Aruba Central with correct endpoint paths."""

    def __init__(self):
        self.langchain_tools = {}
        self.tool_names = []

        self.base_url = os.getenv("ARUBA_CENTRAL_BASE_URL", "")
        self.token = os.getenv("ARUBA_CENTRAL_TOKEN", "")
        self.client_id = os.getenv("ARUBA_CENTRAL_CLIENT_ID", "")
        self.client_secret = os.getenv("ARUBA_CENTRAL_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("ARUBA_CENTRAL_REFRESH_TOKEN", "")
        self.timeout = int(os.getenv("ARUBA_CENTRAL_TIMEOUT", "30"))

    async def connect(self):
        import httpx
        print(f"{Colors.OKBLUE}Connecting to Aruba Central...{Colors.ENDC}")
        print(f"  Base URL: {self.base_url}")

        self.http_client = httpx.AsyncClient(timeout=self.timeout)

        # Auto-refresh token on startup
        print(f"{Colors.OKBLUE}  Refreshing access token...{Colors.ENDC}")
        refreshed = await self._do_refresh_token()
        if refreshed:
            print(f"{Colors.OKGREEN}  Token refreshed! New token: {self.token[:15]}...{Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}  Token refresh failed — using existing token{Colors.ENDC}")

        from tool_registry import TOOL_REGISTRY
        for tool_name, metadata in TOOL_REGISTRY.items():
            self.tool_names.append(tool_name)
            self.langchain_tools[tool_name] = self._create_tool(tool_name, metadata)

        print(f"{Colors.OKGREEN}  Loaded {len(self.tool_names)} tools{Colors.ENDC}")

    def _create_tool(self, tool_name: str, metadata: dict):
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

            # Separate path params from query/body params
            clean_kwargs = {k: v for k, v in kwargs.items() if v is not None}
            path_params = {}
            other_params = {}

            for key, value in clean_kwargs.items():
                if f"{{{key}}}" in path_template:
                    path_params[key] = value
                else:
                    other_params[key] = value

            # Merge default params (don't overwrite user-provided ones)
            for k, v in default_params.items():
                if k not in other_params:
                    other_params[k] = v

            # Build the full URL
            try:
                path = path_template.format(**path_params)
            except KeyError as e:
                return json.dumps({"error": True, "detail": f"Missing required path parameter: {e}"})

            url = f"{manager.base_url}{path}"
            headers = {
                "Authorization": f"Bearer {manager.token}",
                "Content-Type": "application/json"
            }

            try:
                response = await manager._make_request(method, url, headers, other_params, endpoint)

                # Auto-refresh on 401
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
                    return json.dumps({
                        "error": True,
                        "status_code": response.status_code,
                        "detail": response.text[:500]
                    })

            except Exception as e:
                return json.dumps({"error": True, "detail": str(e)})

        execute_tool.name = tool_name
        execute_tool.description = description
        return execute_tool

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
        print(f"{Colors.OKBLUE}Disconnected{Colors.ENDC}")


class ArubaLangGraphAgent:
    def __init__(self, tool_manager: MCPToolManager, semantic_filter: SemanticToolFilter):
        self.tool_manager = tool_manager
        self.semantic_filter = semantic_filter

        print(f"{Colors.OKBLUE}Initializing Ollama LLM: {OLLAMA_MODEL}...{Colors.ENDC}")
        self.llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_URL, temperature=0)
        self._build_graph()
        print(f"{Colors.OKGREEN}LangGraph agent initialized{Colors.ENDC}")

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

        # BLOCKED TOOLS - these return 404 on this Aruba Central instance
        blocked_tools = {
            "get_topology_devices", "get_topology_edges", "get_topology_uplinks",
            "get_topology_tunnels", "get_topology_site"
        }

        # ALWAYS INCLUDE these essential tools for broad queries
        always_include_keywords = ["network", "summary", "overview", "health", "status",
                                   "everything", "understand", "topology", "architecture",
                                   "what do i have", "show me all", "full", "complete",
                                   "troubleshoot", "diagnose", "problem", "issue", "wrong"]
        
        essential_tools = ["get_device_inventory", "get_sites"]
        
        # Keyword overrides — ensure the right tool is always included
        keyword_tools = {
            "switch": ["get_device_inventory"],
            "ap ": ["get_device_inventory", "get_ap_settings"],
            "ap?": ["get_device_inventory", "get_ap_settings"],
            "aps": ["get_device_inventory", "get_ap_settings"],
            "access point": ["get_device_inventory", "get_ap_settings"],
            "wireless ap": ["get_device_inventory", "get_ap_settings"],
            "online": ["get_device_inventory"],
            "offline": ["get_device_inventory"],
            "down": ["get_device_inventory"],
            "site": ["get_sites"],
            "group": ["get_groups"],
            "client": ["get_visualrf_floor_clients", "get_wids_client_attacks"],
            "wireless client": ["get_visualrf_floor_clients"],
            "wired client": ["get_visualrf_floor_clients"],
            "gateway": ["get_device_inventory"],
            "inventory": ["get_device_inventory"],
            "device": ["get_device_inventory"],
            "wlan": ["get_all_wlans", "get_wlan"],
            "ssid": ["get_all_wlans", "get_wlan"],
            "firmware": ["get_firmware_versions", "get_firmware_upgrade_status", "get_device_inventory"],
            "upgrade": ["get_firmware_versions", "get_firmware_upgrade_status", "get_device_inventory"],
            "license": ["get_subscription_keys", "get_license_stats"],
            "subscription": ["get_subscription_keys"],
            "rogue": ["get_rogue_aps", "get_visualrf_rogue_location"],
            "user": ["list_users", "get_user"],
            "template": ["get_templates", "get_all_template_variables"],
            "audit": ["get_audit_trail_logs"],
            "log": ["get_audit_trail_logs", "get_event_logs"],
            "topology": ["get_device_inventory", "get_sites"],
            "architecture": ["get_device_inventory", "get_sites", "get_groups"],
            "network": ["get_device_inventory", "get_sites", "get_all_wlans"],
            "summary": ["get_device_inventory", "get_sites", "get_all_wlans", "get_rogue_aps"],
            "health": ["get_device_inventory", "get_sites", "get_rogue_aps"],
            "security": ["get_rogue_aps", "get_suspect_aps", "get_wids_events", "get_interfering_aps"],
            "interfering": ["get_interfering_aps"],
            "neighbor": ["get_neighbor_aps"],
            "suspect": ["get_suspect_aps"],
            "wids": ["get_wids_events", "get_wids_client_attacks", "get_wids_infrastructure_attacks"],
            "attack": ["get_wids_events", "get_wids_client_attacks", "get_wids_infrastructure_attacks"],
            "event": ["get_event_logs", "get_event_details"],
            "config": ["get_device_configuration", "get_device_config_details"],
            "slow": ["get_device_inventory", "get_interfering_aps", "get_rogue_aps"],
            "wifi": ["get_device_inventory", "get_all_wlans", "get_interfering_aps"],
            "connect": ["get_device_inventory", "get_visualrf_floor_clients"],
        }
        
        # Collect keyword-matched tools
        boosted = []
        
        # Check if this is a broad/overview query — always include essentials
        if any(kw in query for kw in always_include_keywords):
            for t in essential_tools:
                if t in self.tool_manager.tool_names and t not in boosted:
                    boosted.append(t)
        
        for keyword, tools in keyword_tools.items():
            if keyword in query:
                for t in tools:
                    if t in self.tool_manager.tool_names and t not in boosted:
                        boosted.append(t)
        
        # Get semantic filtered tools
        filtered = self.semantic_filter.filter(query, top_k=TOP_K_TOOLS)
        
        # Merge: boosted tools first, then semantic results
        final = list(boosted)
        for t in filtered:
            if t not in final:
                final.append(t)
        
        # REMOVE blocked tools
        final = [t for t in final if t not in blocked_tools]
        
        final = final[:TOP_K_TOOLS]

        print(f"\n{Colors.OKCYAN}🔍 Filtered tools ({len(final)}/{len(self.tool_manager.tool_names)}):{Colors.ENDC}")
        for i, name in enumerate(final, 1):
            marker = " ⭐" if name in boosted else ""
            print(f"  {i}. {name}{marker}")
        print()
        return {**state, "filtered_tool_names": final}
        
    async def _agent_node(self, state: AgentState) -> AgentState:
        tools = self.tool_manager.get_tools_by_names(state.get("filtered_tool_names", []))
        llm = self.llm.bind_tools(tools)

        system_prompt = SystemMessage(content="""You are an expert Aruba Central network engineer AI assistant. You MUST use tools to answer every question.

CRITICAL RULES:
1. ALWAYS call tools immediately. NEVER describe what you would do - just DO IT.
2. Call MULTIPLE tools in parallel when the question needs data from different sources.
3. If a tool fails or returns an error, AUTOMATICALLY try alternative tools. Do NOT ask the user.
4. If one tool returns 404, try related tools immediately without asking permission.
5. After getting results, give a CLEAR summary with counts, names, IPs, and status.
6. NEVER say "Would you like me to try?" - just try it automatically.
7. NEVER say "the tools cannot do this" without trying ALL relevant tools first.
8. For inventory queries, use get_device_inventory with sku_type parameter: IAP for APs, ArubaSwitch for switches.
9. Present data in organized tables or bullet points with key details.
10. If asked about topology/connections and topology tools fail, use get_device_inventory to show all devices instead.

TOOL PARAMETER TIPS:
- get_device_inventory: use sku_type="IAP" for APs, sku_type="ArubaSwitch" for switches, omit for all devices
- get_sites: no required params, returns all sites
- get_all_wlans: use group parameter if filtering by group
- get_firmware_versions: use device_type parameter

KNOWN BROKEN TOOLS (DO NOT USE THESE - they return 404):
- get_topology_devices, get_topology_edges, get_topology_uplinks, get_topology_tunnels, get_topology_site
- These topology endpoints are NOT available on this Aruba Central instance.
- Instead use: get_device_inventory (for all devices), get_sites (for sites)

WORKING API ENDPOINTS:
- get_device_inventory -> returns all devices (APs, switches, gateways)
- get_sites -> returns all sites
- get_all_wlans -> returns WLANs
- get_groups -> returns groups
- get_rogue_aps, get_suspect_aps, get_interfering_aps -> security
- get_firmware_versions -> available firmware
- get_subscription_keys -> licenses

MULTI-STEP EXAMPLES:
- "topology/architecture" -> call get_device_inventory AND get_sites in parallel, then describe network layout
- "switches needing upgrades" -> call get_device_inventory(sku_type=ArubaSwitch) AND get_firmware_versions in parallel, then compare versions
- "network summary" -> call get_sites, get_device_inventory, get_all_wlans, get_rogue_aps in parallel
- "slow WiFi troubleshoot" -> call get_device_inventory(sku_type=IAP), get_interfering_aps, get_rogue_aps in parallel

RESPONSE FORMAT:
- Always respond with actual data, never an empty response
- If tools fail, explain what you found and what failed
- Use bullet points, tables, and clear formatting
- Include device names, IPs, status, firmware versions when available
""")

        messages = [system_prompt] + list(state["messages"])
        try:
            response = await llm.ainvoke(messages)
        except Exception as e:
            print(f"{Colors.FAIL}LLM Error: {e}{Colors.ENDC}")
            response = AIMessage(content=f"Error: {e}")
        # Debug: show what LLM returned
        if hasattr(response, "tool_calls") and response.tool_calls:
            print(f"{Colors.OKBLUE}🤖 LLM wants to call {len(response.tool_calls)} tool(s){Colors.ENDC}")
        elif hasattr(response, "content") and response.content:
            preview = response.content[:200]
            print(f"{Colors.OKBLUE}🤖 LLM response: {preview}...{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}🤖 LLM returned EMPTY response! Forcing retry...{Colors.ENDC}")
            # Force the LLM to respond by adding a nudge message
            nudge = HumanMessage(content="You returned an empty response. Based on the tool results above, please provide a clear summary of what you found. If some tools failed with 404, explain what DID work and present that data. Never return empty.")
            try:
                retry_response = await llm.ainvoke(messages + [response, nudge])
                if hasattr(retry_response, "content") and retry_response.content:
                    print(f"{Colors.OKGREEN}🤖 Retry successful!{Colors.ENDC}")
                    return {**state, "messages": list(state["messages"]) + [retry_response]}
            except Exception as e:
                print(f"{Colors.FAIL}Retry also failed: {e}{Colors.ENDC}")
            # If retry also empty, create a fallback response
            fallback = AIMessage(content="I retrieved some data but encountered issues with certain endpoints. Please try a more specific query like 'show me all sites' or 'list all devices'.")
            return {**state, "messages": list(state["messages"]) + [fallback]}
        return {**state, "messages": list(state["messages"]) + [response]}

    async def _execute_tools_node(self, state: AgentState) -> AgentState:
        last = state["messages"][-1]
        if not hasattr(last, "tool_calls") or not last.tool_calls:
            return state

        msgs = []
        for tc in last.tool_calls:
            name, args = tc["name"], tc.get("args", {})
            print(f"{Colors.WARNING}🔧 Executing: {name}{Colors.ENDC}")
            if args:
                print(f"   Args: {json.dumps(args, indent=2)}")

            if name in self.tool_manager.langchain_tools:
                try:
                    result = await self.tool_manager.langchain_tools[name].ainvoke(args)
                    result_str = str(result)
                    if len(result_str) > 500:
                        print(f"{Colors.OKGREEN}✓ Done ({len(result_str)} chars){Colors.ENDC}")
                        print(f"   Preview: {result_str[:300]}...\n")
                    else:
                        print(f"{Colors.OKGREEN}✓ Done ({len(result_str)} chars){Colors.ENDC}")
                        print(f"   Result: {result_str}\n")
                except Exception as e:
                    result = json.dumps({"error": True, "detail": str(e)})
                    print(f"{Colors.FAIL}✗ Failed: {e}{Colors.ENDC}\n")
                msgs.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

        return {**state, "messages": list(state["messages"]) + msgs}

    def _should_continue(self, state: AgentState):
        last = state["messages"][-1]
        return "continue" if hasattr(last, "tool_calls") and last.tool_calls else "end"

    async def run(self, query: str):
        result = await self.graph.ainvoke({"messages": [HumanMessage(content=query)], "filtered_tool_names": []}, {"recursion_limit": 15})
        final = result["messages"][-1]
        return final.content if hasattr(final, "content") else str(final)


async def main():
    print(f"\n{Colors.HEADER}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}  Aruba Central LangGraph Agent with Semantic Tool Filtering{Colors.ENDC}")
    print(f"{Colors.HEADER}{'=' * 80}{Colors.ENDC}\n")
    print(f"  Model: {OLLAMA_MODEL}")
    print(f"  Ollama: {OLLAMA_URL}")
    print(f"  Top-K: {TOP_K_TOOLS}\n")

    semantic_filter = SemanticToolFilter()
    tool_manager = MCPToolManager()

    try:
        await tool_manager.connect()
        agent = ArubaLangGraphAgent(tool_manager, semantic_filter)
        print(f"\n{Colors.OKGREEN}Ready! Type your queries or 'quit' to exit.{Colors.ENDC}\n")

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
                print("-" * 80 + "\n")

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