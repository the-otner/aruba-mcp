#!/usr/bin/env python3
"""
HPE Aruba SSH/CLI MCP Server - Phase 2

Direct device-level access via SSH using Netmiko.
Supports: ArubaOS-CX switches, AOS-Switch, AOS8 controllers/APs.

This runs alongside the Aruba Central MCP server (Phase 1) to provide
deep CLI-level device access that the REST API cannot.

Requires: pip install netmiko
"""

import os
import sys
import json
import logging
from typing import Any, Dict, Optional, List
from datetime import datetime

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_AVAILABLE = True
except ImportError:
    NETMIKO_AVAILABLE = False
    print("WARNING: netmiko not installed. Run: pip install netmiko")

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("aruba-ssh-mcp")

# Global configuration
SSH_USERNAME = os.getenv("ARUBA_SSH_USERNAME", "admin")
SSH_PASSWORD = os.getenv("ARUBA_SSH_PASSWORD", "")
SSH_TIMEOUT = int(os.getenv("ARUBA_SSH_TIMEOUT", "30"))
SSH_DEVICE_TYPE = os.getenv("ARUBA_SSH_DEVICE_TYPE", "aruba_oscx")  # aruba_oscx, aruba_osswitch, aruba_os

# Initialize FastMCP server
mcp = FastMCP("aruba-ssh")


def _get_connection(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    enable_password: Optional[str] = None
) -> Dict[str, Any]:
    """Create Netmiko connection parameters."""
    return {
        "device_type": device_type or SSH_DEVICE_TYPE,
        "host": device_ip,
        "username": username or SSH_USERNAME,
        "password": password or SSH_PASSWORD,
        "timeout": SSH_TIMEOUT,
        "secret": enable_password or password or SSH_PASSWORD,
    }


def _ssh_execute(device_ip: str, command: str, device_type: Optional[str] = None,
                 username: Optional[str] = None, password: Optional[str] = None,
                 enable: bool = False) -> Dict[str, Any]:
    """Execute a single command via SSH."""
    if not NETMIKO_AVAILABLE:
        return {"error": True, "message": "netmiko not installed. Run: pip install netmiko"}

    try:
        conn_params = _get_connection(device_ip, device_type, username, password)
        with ConnectHandler(**conn_params) as conn:
            if enable:
                conn.enable()
            output = conn.send_command(command, read_timeout=SSH_TIMEOUT)
            return {
                "success": True,
                "device": device_ip,
                "command": command,
                "output": output,
                "timestamp": datetime.now().isoformat()
            }
    except NetmikoTimeoutException:
        return {"error": True, "device": device_ip, "message": f"SSH timeout connecting to {device_ip}"}
    except NetmikoAuthenticationException:
        return {"error": True, "device": device_ip, "message": f"SSH authentication failed for {device_ip}"}
    except Exception as e:
        return {"error": True, "device": device_ip, "message": str(e)}


def _ssh_execute_multiple(device_ip: str, commands: List[str], device_type: Optional[str] = None,
                          username: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    """Execute multiple show commands via SSH in a single session."""
    if not NETMIKO_AVAILABLE:
        return {"error": True, "message": "netmiko not installed"}

    try:
        conn_params = _get_connection(device_ip, device_type, username, password)
        results = []
        with ConnectHandler(**conn_params) as conn:
            for cmd in commands:
                output = conn.send_command(cmd, read_timeout=SSH_TIMEOUT)
                results.append({"command": cmd, "output": output})
        return {
            "success": True, "device": device_ip,
            "results": results, "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": True, "device": device_ip, "message": str(e)}


def _ssh_config(device_ip: str, config_commands: List[str], device_type: Optional[str] = None,
                username: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
    """Send configuration commands via SSH."""
    if not NETMIKO_AVAILABLE:
        return {"error": True, "message": "netmiko not installed"}

    try:
        conn_params = _get_connection(device_ip, device_type, username, password)
        with ConnectHandler(**conn_params) as conn:
            output = conn.send_config_set(config_commands)
            return {
                "success": True, "device": device_ip,
                "commands_sent": config_commands,
                "output": output, "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        return {"error": True, "device": device_ip, "message": str(e)}


# ============================================================================
# Category 1: Device CLI Access (5 tools)
# ============================================================================

@mcp.tool()
def run_show_command(
    device_ip: str, command: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Run any show command on an Aruba device via SSH.
    This is the most flexible tool - can run ANY show command.

    Args:
        device_ip: Device IP address or hostname
        command: CLI command to execute (e.g., 'show running-config', 'show ip route')
        device_type: Optional device type override (aruba_oscx, aruba_osswitch, aruba_os)
        username: Optional SSH username override
        password: Optional SSH password override

    Returns:
        JSON with command output
    """
    result = _ssh_execute(device_ip, command, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def run_show_commands(
    device_ip: str, commands: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Run multiple show commands on an Aruba device in a single SSH session.
    More efficient than calling run_show_command multiple times.

    Args:
        device_ip: Device IP address
        commands: Comma-separated list of commands (e.g., 'show version,show ip route,show vlan')
        device_type: Optional device type override
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with all command outputs
    """
    cmd_list = [c.strip() for c in commands.split(",")]
    result = _ssh_execute_multiple(device_ip, cmd_list, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_running_config(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get the full running configuration of an Aruba device.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with running config text
    """
    result = _ssh_execute(device_ip, "show running-config", device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_startup_config(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get the startup configuration of an Aruba device.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with startup config text
    """
    result = _ssh_execute(device_ip, "show startup-config", device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def compare_configs(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Compare running config vs startup config (detect config drift).
    Shows differences between what's running and what's saved.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with config diff
    """
    result = _ssh_execute(device_ip, "show diff running-config startup-config", device_type, username, password)
    return json.dumps(result, indent=2)


# ============================================================================
# Category 2: Routing Protocol Health (5 tools)
# ============================================================================

@mcp.tool()
def get_ospf_neighbors(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get OSPF neighbor table from an Aruba device. Shows all OSPF adjacencies,
    their state (FULL, 2WAY, etc.), router ID, and interface.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with OSPF neighbor information
    """
    commands = ["show ip ospf neighbor", "show ip ospf interface brief"]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_bgp_summary(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get BGP peer summary from an Aruba device. Shows all BGP peers, their state,
    AS number, prefixes received, and uptime.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with BGP summary
    """
    commands = ["show ip bgp summary", "show ip bgp neighbor"]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_route_table(
    device_ip: str,
    prefix: Optional[str] = None,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get IP routing table from an Aruba device. Shows all routes or a specific prefix.

    Args:
        device_ip: Device IP address
        prefix: Optional specific prefix to look up (e.g., '10.1.1.0/24')
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with routing table
    """
    cmd = f"show ip route {prefix}" if prefix else "show ip route"
    result = _ssh_execute(device_ip, cmd, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_arp_table(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get ARP table from an Aruba device. Shows IP-to-MAC address mappings.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with ARP table
    """
    result = _ssh_execute(device_ip, "show arp", device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_vrf_info(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get VRF information from an Aruba device. Shows all VRFs and their interfaces.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with VRF details
    """
    commands = ["show vrf", "show ip route vrf all summary"]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


# ============================================================================
# Category 3: Interface Troubleshooting (5 tools)
# ============================================================================

@mcp.tool()
def get_interface_status(
    device_ip: str,
    interface: Optional[str] = None,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get interface status from an Aruba device. Shows all interfaces or a specific one
    with admin/oper status, speed, duplex, and description.

    Args:
        device_ip: Device IP address
        interface: Optional specific interface (e.g., '1/1/1')
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with interface status
    """
    cmd = f"show interface {interface}" if interface else "show interface brief"
    result = _ssh_execute(device_ip, cmd, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_interface_errors(
    device_ip: str,
    interface: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get interface error counters for a specific interface. Shows CRC errors,
    input/output errors, drops, collisions, and other error statistics.

    Args:
        device_ip: Device IP address
        interface: Interface name (e.g., '1/1/1', 'vlan100')
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with interface error counters
    """
    commands = [f"show interface {interface}", f"show interface {interface} extended"]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_interface_counters(
    device_ip: str,
    interface: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get traffic counters for a specific interface. Shows bytes in/out,
    packets in/out, broadcast, multicast statistics.

    Args:
        device_ip: Device IP address
        interface: Interface name
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with interface counters
    """
    result = _ssh_execute(device_ip, f"show interface {interface} statistics", device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_poe_status(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get PoE (Power over Ethernet) status for all ports. Shows per-port power
    draw, power budget, priority, and connected PD class.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with PoE status
    """
    commands = ["show poe brief", "show poe"]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def bounce_interface(
    device_ip: str,
    interface: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Bounce (shut/no shut) an interface to reset it. USE WITH CAUTION.
    This will briefly disconnect anything on that port.

    Args:
        device_ip: Device IP address
        interface: Interface to bounce (e.g., '1/1/1')
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with bounce result
    """
    config_cmds = [
        f"interface {interface}",
        "shutdown",
        "no shutdown"
    ]
    result = _ssh_config(device_ip, config_cmds, device_type, username, password)
    return json.dumps(result, indent=2)


# ============================================================================
# Category 4: L2 Troubleshooting (4 tools)
# ============================================================================

@mcp.tool()
def get_mac_address_table(
    device_ip: str,
    mac: Optional[str] = None,
    vlan: Optional[str] = None,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get MAC address table from an Aruba switch. Find which port a MAC is on.

    Args:
        device_ip: Device IP address
        mac: Optional specific MAC to search for
        vlan: Optional VLAN to filter by
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with MAC address table
    """
    if mac:
        cmd = f"show mac-address-table {mac}"
    elif vlan:
        cmd = f"show mac-address-table vlan {vlan}"
    else:
        cmd = "show mac-address-table"
    result = _ssh_execute(device_ip, cmd, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_vlan_info(
    device_ip: str,
    vlan_id: Optional[str] = None,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get VLAN information from an Aruba switch. Shows all VLANs or a specific one
    with member ports and status.

    Args:
        device_ip: Device IP address
        vlan_id: Optional specific VLAN ID
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with VLAN information
    """
    cmd = f"show vlan {vlan_id}" if vlan_id else "show vlan"
    result = _ssh_execute(device_ip, cmd, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_spanning_tree(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get Spanning Tree Protocol status. Shows root bridge, port roles/states,
    and topology information for loop prevention.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with STP status
    """
    commands = ["show spanning-tree", "show spanning-tree detail"]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_lldp_neighbors(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get LLDP neighbor information. Shows connected devices on each port
    with their name, IP, model, and capabilities.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with LLDP neighbor details
    """
    commands = ["show lldp neighbor-info", "show lldp neighbor-info detail"]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


# ============================================================================
# Category 5: Security Audit (4 tools)
# ============================================================================

@mcp.tool()
def get_access_lists(
    device_ip: str,
    acl_name: Optional[str] = None,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get access control lists (ACLs) from an Aruba device. Shows all ACL rules
    and optionally hit counts for security auditing.

    Args:
        device_ip: Device IP address
        acl_name: Optional specific ACL name
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with ACL details
    """
    if acl_name:
        cmd = f"show access-list {acl_name}"
    else:
        cmd = "show access-list"
    result = _ssh_execute(device_ip, cmd, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_aaa_status(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get AAA (Authentication, Authorization, Accounting) status.
    Shows RADIUS/TACACS+ server reachability and configuration.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with AAA status
    """
    commands = [
        "show aaa server-group",
        "show radius-server",
        "show aaa authentication"
    ]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_ntp_status(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get NTP synchronization status. Shows if the clock is synced,
    NTP server reachability, stratum, and offset.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with NTP status
    """
    commands = ["show ntp status", "show ntp associations"]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def audit_security_posture(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Run a comprehensive security posture audit on a device.
    Checks ACLs, AAA, NTP, SSH config, SNMP, and password complexity.
    Returns all results in one call for efficiency.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with comprehensive security audit results
    """
    commands = [
        "show running-config | include aaa",
        "show running-config | include radius",
        "show running-config | include tacacs",
        "show running-config | include ntp",
        "show running-config | include ssh",
        "show running-config | include snmp",
        "show running-config | include password",
        "show running-config | include access-list",
        "show running-config | include logging",
        "show ntp status",
        "show access-list",
    ]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


# ============================================================================
# Category 6: Device Health Deep (4 tools)
# ============================================================================

@mcp.tool()
def get_cpu_memory_detail(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get detailed CPU and memory utilization from an Aruba device.
    Shows current usage, historical trend, and top processes.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with CPU/memory details
    """
    commands = [
        "show system resource-utilization",
        "show capacityprofile",
    ]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_device_logs(
    device_ip: str,
    lines: Optional[int] = None,
    severity: Optional[str] = None,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get log buffer from an Aruba device. Shows recent syslog entries
    with timestamps, severity, and messages.

    Args:
        device_ip: Device IP address
        lines: Optional number of lines to retrieve
        severity: Optional minimum severity filter
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with device logs
    """
    cmd = "show log"
    if lines:
        cmd = f"show log -r | tail -{lines}"
    result = _ssh_execute(device_ip, cmd, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_environment(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get environmental status: fans, power supplies, temperature sensors.
    Critical for hardware health monitoring.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with environmental status
    """
    commands = [
        "show environment",
        "show system temperature",
        "show system fan",
        "show system power-supply",
    ]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_system_info(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Get system information: hostname, uptime, firmware version, serial number,
    model, and boot details.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with system info
    """
    commands = ["show version", "show system", "show boot-history"]
    result = _ssh_execute_multiple(device_ip, commands, device_type, username, password)
    return json.dumps(result, indent=2)


# ============================================================================
# Category 7: Config Management (3 tools)
# ============================================================================

@mcp.tool()
def push_config_commands(
    device_ip: str,
    commands: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Push configuration commands to an Aruba device. USE WITH CAUTION.
    Sends commands in config mode. Always verify before pushing.

    Args:
        device_ip: Device IP address
        commands: Newline-separated or comma-separated config commands
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with push result
    """
    if "\n" in commands:
        cmd_list = [c.strip() for c in commands.split("\n") if c.strip()]
    else:
        cmd_list = [c.strip() for c in commands.split(",") if c.strip()]

    result = _ssh_config(device_ip, cmd_list, device_type, username, password)
    return json.dumps(result, indent=2)


@mcp.tool()
def backup_config(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Backup the running configuration of an Aruba device.
    Retrieves the full running-config and returns it for saving.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with the full running config for backup
    """
    result = _ssh_execute(device_ip, "show running-config", device_type, username, password)
    if result.get("success"):
        result["backup_timestamp"] = datetime.now().isoformat()
        result["backup_type"] = "running-config"
    return json.dumps(result, indent=2)


@mcp.tool()
def save_config(
    device_ip: str,
    device_type: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> str:
    """
    Save the running configuration to startup (write memory).
    Ensures config survives a reboot.

    Args:
        device_ip: Device IP address
        device_type: Optional device type
        username: Optional SSH username
        password: Optional SSH password

    Returns:
        JSON with save result
    """
    if not NETMIKO_AVAILABLE:
        return json.dumps({"error": True, "message": "netmiko not installed"})

    try:
        conn_params = _get_connection(device_ip, device_type, username, password)
        with ConnectHandler(**conn_params) as conn:
            output = conn.save_config()
            return json.dumps({
                "success": True, "device": device_ip,
                "output": output, "timestamp": datetime.now().isoformat()
            }, indent=2)
    except Exception as e:
        return json.dumps({"error": True, "device": device_ip, "message": str(e)}, indent=2)


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import argparse, signal

    parser = argparse.ArgumentParser(description="Aruba SSH MCP Server")
    parser.add_argument("--sse", action="store_true", help="Run with SSE transport")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("HPE Aruba SSH/CLI MCP Server - Phase 2")
    logger.info(f"Tools: 31 across 7 categories")
    logger.info(f"Default device type: {SSH_DEVICE_TYPE}")
    logger.info(f"Netmiko available: {NETMIKO_AVAILABLE}")
    logger.info(f"Transport: {'SSE' if args.sse else 'stdio'}")
    logger.info("=" * 60)

    mcp.run(transport="sse" if args.sse else "stdio")