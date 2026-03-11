"""
SSH Tool Registry for Phase 2 - Aruba SSH/CLI MCP Server

Metadata for all 31 SSH tools organized by category.
Used for semantic filtering alongside the Phase 1 registry.
"""

SSH_TOOL_REGISTRY = {
    # Device CLI Access (5 tools)
    "run_show_command": {"category": "ssh_cli", "description": "Run any show command on an Aruba device via SSH. Most flexible tool for direct CLI access.", "keywords": ["SSH", "CLI", "show", "command", "execute", "run", "device", "direct"]},
    "run_show_commands": {"category": "ssh_cli", "description": "Run multiple show commands in a single SSH session. Efficient batch command execution.", "keywords": ["SSH", "CLI", "multiple", "commands", "batch", "execute"]},
    "get_running_config": {"category": "ssh_cli", "description": "Get full running configuration via SSH. Shows the complete active device config.", "keywords": ["running", "config", "configuration", "SSH", "full", "show"]},
    "get_startup_config": {"category": "ssh_cli", "description": "Get startup configuration via SSH. Shows saved configuration.", "keywords": ["startup", "config", "saved", "SSH", "boot"]},
    "compare_configs": {"category": "ssh_cli", "description": "Compare running vs startup config to detect config drift.", "keywords": ["compare", "diff", "drift", "running", "startup", "config", "difference"]},

    # Routing Protocol Health (5 tools)
    "get_ospf_neighbors": {"category": "ssh_routing", "description": "Get OSPF neighbor table via SSH. Shows adjacencies, state, router ID, interface.", "keywords": ["OSPF", "neighbor", "routing", "adjacency", "FULL", "state", "protocol"]},
    "get_bgp_summary": {"category": "ssh_routing", "description": "Get BGP peer summary via SSH. Shows peers, state, AS number, prefixes.", "keywords": ["BGP", "peer", "summary", "AS", "routing", "prefix", "neighbor"]},
    "get_route_table": {"category": "ssh_routing", "description": "Get IP routing table via SSH. Shows all routes or specific prefix.", "keywords": ["route", "routing", "table", "IP", "prefix", "next-hop", "gateway"]},
    "get_arp_table": {"category": "ssh_routing", "description": "Get ARP table via SSH. Shows IP-to-MAC address mappings.", "keywords": ["ARP", "MAC", "IP", "mapping", "address", "resolution"]},
    "get_vrf_info": {"category": "ssh_routing", "description": "Get VRF information via SSH. Shows all VRFs and their interfaces.", "keywords": ["VRF", "virtual", "routing", "forwarding", "instance"]},

    # Interface Troubleshooting (5 tools)
    "get_interface_status": {"category": "ssh_interface", "description": "Get interface status via SSH. Admin/oper state, speed, duplex.", "keywords": ["interface", "status", "up", "down", "speed", "duplex", "link"]},
    "get_interface_errors": {"category": "ssh_interface", "description": "Get interface error counters. CRC, drops, collisions.", "keywords": ["interface", "errors", "CRC", "drops", "collisions", "input", "output"]},
    "get_interface_counters": {"category": "ssh_interface", "description": "Get interface traffic counters. Bytes, packets in/out.", "keywords": ["interface", "counters", "traffic", "bytes", "packets", "statistics"]},
    "get_poe_status": {"category": "ssh_interface", "description": "Get PoE power status per port. Power draw, budget, class.", "keywords": ["PoE", "power", "ethernet", "port", "watts", "budget"]},
    "bounce_interface": {"category": "ssh_interface", "description": "Bounce (shut/no shut) an interface to reset it.", "keywords": ["bounce", "reset", "interface", "shutdown", "restart", "port"]},

    # L2 Troubleshooting (4 tools)
    "get_mac_address_table": {"category": "ssh_l2", "description": "Get MAC address table. Find which port a MAC address is on.", "keywords": ["MAC", "address", "table", "port", "switch", "L2", "find"]},
    "get_vlan_info": {"category": "ssh_l2", "description": "Get VLAN info via SSH. All VLANs, member ports, status.", "keywords": ["VLAN", "info", "ports", "members", "tagged", "untagged"]},
    "get_spanning_tree": {"category": "ssh_l2", "description": "Get Spanning Tree status. Root bridge, port roles, topology.", "keywords": ["spanning", "tree", "STP", "RSTP", "root", "bridge", "loop"]},
    "get_lldp_neighbors": {"category": "ssh_l2", "description": "Get LLDP neighbors. Connected devices on each port.", "keywords": ["LLDP", "neighbor", "CDP", "connected", "device", "topology"]},

    # Security Audit (4 tools)
    "get_access_lists": {"category": "ssh_security", "description": "Get ACLs from device. All rules and hit counts for security audit.", "keywords": ["ACL", "access", "list", "security", "firewall", "rules", "audit"]},
    "get_aaa_status": {"category": "ssh_security", "description": "Get AAA status. RADIUS/TACACS server reachability and config.", "keywords": ["AAA", "RADIUS", "TACACS", "authentication", "authorization", "server"]},
    "get_ntp_status": {"category": "ssh_security", "description": "Get NTP sync status. Clock synced, server reachability, stratum.", "keywords": ["NTP", "time", "clock", "sync", "stratum", "offset"]},
    "audit_security_posture": {"category": "ssh_security", "description": "Comprehensive security audit. Checks ACL, AAA, NTP, SSH, SNMP, passwords.", "keywords": ["security", "audit", "posture", "compliance", "check", "CIS", "benchmark"]},

    # Device Health Deep (4 tools)
    "get_cpu_memory_detail": {"category": "ssh_health", "description": "Get detailed CPU/memory usage via SSH. Current, historical, top processes.", "keywords": ["CPU", "memory", "utilization", "resource", "performance", "process"]},
    "get_device_logs": {"category": "ssh_health", "description": "Get device log buffer via SSH. Recent syslog entries.", "keywords": ["log", "syslog", "events", "messages", "buffer", "history"]},
    "get_environment": {"category": "ssh_health", "description": "Get environmental status. Fans, PSU, temperature.", "keywords": ["environment", "fan", "power", "temperature", "PSU", "hardware", "health"]},
    "get_system_info": {"category": "ssh_health", "description": "Get system info. Hostname, uptime, version, serial, model.", "keywords": ["system", "info", "version", "uptime", "serial", "hostname", "model"]},

    # Config Management (3 tools)
    "push_config_commands": {"category": "ssh_config", "description": "Push config commands to device via SSH. Config mode CLI push.", "keywords": ["push", "config", "configure", "change", "command", "write"]},
    "backup_config": {"category": "ssh_config", "description": "Backup running config via SSH for disaster recovery.", "keywords": ["backup", "config", "save", "export", "disaster", "recovery"]},
    "save_config": {"category": "ssh_config", "description": "Save running config to startup (write memory).", "keywords": ["save", "write", "memory", "startup", "persist", "commit"]},
}