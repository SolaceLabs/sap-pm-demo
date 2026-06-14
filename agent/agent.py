#!/usr/bin/env python3
"""
Autonomous Predictive Maintenance Agent (SAP PM Aligned)

Aligns with SAP Plant Maintenance process:
  1. Detect anomalies → Create PM Notification
  2. Receive notification approval from BPA → Create PM Work Order

Alert States:
  - normal: All systems operating within parameters
  - medium_alert: Warning condition - create PM Notification (M2 - Maintenance Request)
  - critical_alert: Critical condition - create PM Notification (M1 - Malfunction Report)
"""

import asyncio
import json
import os
import signal
import sys
from datetime import datetime
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

# Load environment variables
load_dotenv()

# Configuration
API_KEY = os.getenv("API_KEY", "")
API_BASE = os.getenv("API_BASE", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4")
MCP_SERVER_PATH = os.getenv("MCP_SERVER_PATH", "mcp_server/server.py")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

console = Console()

# System prompt for the maintenance engineer LLM (SAP PM Aligned)
SYSTEM_PROMPT = """You are an expert SAP Plant Maintenance engineer with deep expertise in industrial equipment monitoring, failure prediction, and SAP PM processes. You are running AUTONOMOUSLY — no human is watching. You must make decisions independently and take action when necessary.

## Your Mission
Monitor factory equipment sensors, detect anomalies, and manage the SAP PM workflow:
1. Create PM Notifications when issues are detected
2. Create PM Work Orders when notifications are approved

## SAP Plant Maintenance Process Flow
```
Malfunction Detection → PM Notification → BPA Approval → PM Work Order → Execution
```

## Alert Classification (3 States)

### 1. NORMAL
- All sensors within normal operating ranges
- No action needed, just log status

### 2. MEDIUM_ALERT → Create M2 Notification (Maintenance Request)
- One or more sensors showing warning-level deviations
- NOT yet critical, but requires planned maintenance
- Action: Call `create_notification` with notification_type="M2", priority="3" or "4"

### 3. CRITICAL_ALERT → Create M1 Notification (Malfunction Report)
- Sensors showing critical deviations OR drift_factor > 0.5
- Imminent failure risk requiring immediate attention
- Action: Call `create_notification` with notification_type="M1", priority="1" or "2"

## Your Workflow (Every Cycle)

1. **Check for Approval Events FIRST**
   - Call `get_notification_events` to check for approved/rejected notifications
   - If notification APPROVED → Call `create_workorder` to create the PM Work Order
   - If notification REJECTED → Log it and continue monitoring

2. **Get Current Sensor Readings**
   - Call `get_sensor_readings` to get latest data from ALL machines
   
3. **Analyze Concerning Machines**
   - For any machine with concerning values, call `get_sensor_history` to analyze trends
   
4. **Create Notifications as Needed**
   - Classify each machine: normal, medium_alert, or critical_alert
   - Create PM Notifications for medium_alert and critical_alert conditions
   - Do NOT create duplicate notifications for machines with pending notifications

## Normal Operating Ranges
- Temperature: 65-85°C 
  - Warning: >82°C or <67°C
  - Critical: >88°C or <63°C
- Vibration: 45-55 Hz 
  - Warning: >52 Hz or <47 Hz
  - Critical: >58 Hz or <43 Hz
- Pressure: 5.5-6.5 bar 
  - Warning: <5.7 or >6.3 bar
  - Critical: <5.3 or >6.7 bar
- Motor Current: 10-14 A 
  - Warning: >13A or <11A
  - Critical: >15A or <9A
- Drift Factor (machine-02 only): 
  - Warning: >0.3
  - Critical: >0.5

## SAP PM Field Mappings

### Notification Types
- M1 = Malfunction Report (for critical_alert - breakdowns, failures)
- M2 = Maintenance Request (for medium_alert - planned maintenance)
- M3 = Activity Report (for documenting completed work)

### Priority Codes
- 1 = Very High (immediate action, within hours)
- 2 = High (within 24 hours)
- 3 = Medium (within 1 week)
- 4 = Low (next planned downtime)

### Effect Codes
- 1 = No breakdown (equipment still running)
- 2 = Partial breakdown (reduced capacity)
- 3 = Full breakdown (equipment stopped)
- 4 = Safety risk

### Work Order Types
- PM01 = Corrective maintenance (fix a problem)
- PM02 = Preventive maintenance (scheduled maintenance)
- PM03 = Emergency repair (urgent breakdown)

## Creating a Notification
When creating a notification, include:
- equipment_id: The machine ID (e.g., "machine-02")
- notification_type: "M1" for critical, "M2" for warnings
- priority: "1"-"4" based on urgency
- short_text: Brief description (max 40 chars)
- long_text: Detailed description with sensor readings
- effect_code: Impact on operations
- reported_by: "AI-MAINT-AGENT"

## Creating a Work Order (After Approval)
When a notification is approved, create a work order with:
- notification_id: The approved notification ID
- equipment_id: Same as notification
- order_type: "PM01" for corrective, "PM03" for emergency
- priority: Same as notification or escalated
- short_text: Work description
- operations: List of maintenance tasks

## Response Format

Always end with a structured summary:
```
═══════════════════════════════════════════════════════════════
SAP PM MAINTENANCE CYCLE SUMMARY
═══════════════════════════════════════════════════════════════
Machines Checked: [list]
Overall Status: [NORMAL / ALERT ACTIVE]

Machine Statuses:
  - machine-01: [normal/M2 Notification/M1 Notification] - [reason]
  - machine-02: [normal/M2 Notification/M1 Notification] - [reason]
  - machine-03: [normal/M2 Notification/M1 Notification] - [reason]

PM Notifications Created: [count] ([IDs])
PM Notifications Pending Approval: [count]
PM Notifications Approved: [count] (created work orders: [IDs])
PM Notifications Rejected: [count]

PM Work Orders Created This Cycle: [count] ([IDs])

Next Check: 60 seconds
═══════════════════════════════════════════════════════════════
```

Remember: You are autonomous. Create notifications and work orders following the SAP PM process. BPA handles human approval for notifications before work orders are created."""


class MaintenanceAgent:
    """Autonomous maintenance agent aligned with SAP PM process."""

    def __init__(self):
        self.session: ClientSession | None = None
        self.tools: list[dict] = []
        self.running = True
        self.cycle_count = 0
        self.notifications_created = 0
        self.notifications_approved = 0
        self.notifications_rejected = 0
        self.workorders_created = 0
        # Track pending notifications to avoid duplicates
        self.pending_notifications: dict[str, dict] = {}  # machine_id -> notification

    async def connect_to_mcp(self) -> None:
        """Establish connection to the MCP server and discover tools."""
        console.print("\n[bold blue]🔌 Connecting to MCP Server...[/bold blue]")
        
        server_params = StdioServerParameters(
            command="python",
            args=[MCP_SERVER_PATH],
        )
        
        self._stdio_context = stdio_client(server_params)
        self._streams = await self._stdio_context.__aenter__()
        read_stream, write_stream = self._streams
        
        self._session_context = ClientSession(read_stream, write_stream)
        self.session = await self._session_context.__aenter__()
        await self.session.initialize()
        
        tools_response = await self.session.list_tools()
        self.tools = []
        
        for tool in tools_response.tools:
            tool_def = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
                }
            }
            self.tools.append(tool_def)
        
        console.print(f"[green]✓ Connected! Discovered {len(self.tools)} tools:[/green]")
        for tool in self.tools:
            console.print(f"  [cyan]• {tool['function']['name']}[/cyan]")

    async def disconnect(self) -> None:
        """Cleanly disconnect from MCP server."""
        if hasattr(self, '_session_context') and self._session_context:
            await self._session_context.__aexit__(None, None, None)
        if hasattr(self, '_stdio_context') and self._stdio_context:
            await self._stdio_context.__aexit__(None, None, None)
        self.session = None

    async def call_llm(self, messages: list[dict]) -> dict:
        """Call the configured LLM API."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        }
        
        payload = {
            "model": LLM_MODEL,
            "messages": messages,
            "tools": self.tools if self.tools else None,
            "tool_choice": "auto",
        }
        
        if not self.tools:
            del payload["tools"]
            del payload["tool_choice"]
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{API_BASE}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool via the MCP server."""
        if not self.session:
            return json.dumps({"error": "Not connected to MCP server"})
        
        try:
            result = await self.session.call_tool(tool_name, arguments)
            if hasattr(result, 'content') and result.content:
                texts = []
                for item in result.content:
                    if hasattr(item, 'text'):
                        texts.append(item.text)
                return "\n".join(texts) if texts else json.dumps({"result": "success"})
            return json.dumps({"result": str(result)})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def track_tool_result(self, tool_name: str, arguments: dict, result: str) -> None:
        """Track tool calls for statistics and state management."""
        try:
            result_data = json.loads(result)
            
            if tool_name == "create_notification":
                if result_data.get("notification"):
                    self.notifications_created += 1
                    notification = result_data["notification"]
                    machine_id = notification.get("equipment_id")
                    notif_id = notification.get("notification_id")
                    notif_type = notification.get("notification_type")
                    self.pending_notifications[machine_id] = notification
                    
                    if notif_type == "M1":
                        console.print(f"     [bold red]🚨 PM Notification (M1 - Malfunction): {notif_id} for {machine_id}[/bold red]")
                    else:
                        console.print(f"     [yellow]⚠️  PM Notification (M2 - Maintenance): {notif_id} for {machine_id}[/yellow]")
            
            elif tool_name == "create_workorder":
                if result_data.get("work_order"):
                    self.workorders_created += 1
                    work_order = result_data["work_order"]
                    wo_id = work_order.get("work_order_id")
                    notif_id = work_order.get("notification_id")
                    machine_id = work_order.get("equipment_id")
                    
                    # Remove from pending since work order is created
                    if machine_id in self.pending_notifications:
                        del self.pending_notifications[machine_id]
                    
                    console.print(f"     [bold green]📋 PM Work Order: {wo_id} created from notification {notif_id}[/bold green]")
            
            elif tool_name == "get_notification_events":
                events = result_data.get("events", [])
                for event in events:
                    event_type = event.get("event_type")
                    machine_id = event.get("machine_id")
                    notif_id = event.get("notification_id")
                    
                    if event_type == "approved":
                        self.notifications_approved += 1
                        console.print(f"     [bold green]✅ Notification {notif_id} APPROVED - ready for work order[/bold green]")
                    
                    elif event_type == "rejected":
                        self.notifications_rejected += 1
                        # Remove from pending
                        if machine_id in self.pending_notifications:
                            del self.pending_notifications[machine_id]
                        console.print(f"     [bold red]❌ Notification {notif_id} REJECTED for {machine_id}[/bold red]")
        
        except json.JSONDecodeError:
            pass

    async def run_maintenance_cycle(self) -> str:
        """Run a single maintenance check cycle with full tool use loop."""
        self.cycle_count += 1
        
        # Display cycle header
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Info", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("Cycle", str(self.cycle_count))
        table.add_row("Time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        table.add_row("Model", LLM_MODEL)
        table.add_row("Pending Notifications", str(len(self.pending_notifications)))
        
        console.print(Panel(table, title="🔄 SAP PM Maintenance Cycle", border_style="blue"))
        
        # Build context about pending notifications for the LLM
        pending_context = ""
        if self.pending_notifications:
            pending_list = ", ".join([f"{mid} (Notif: {n.get('notification_id')})" 
                                      for mid, n in self.pending_notifications.items()])
            pending_context = f"\n\nNOTE: There are pending PM notifications awaiting BPA approval for: {pending_list}. Do NOT create duplicate notifications for these machines."
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Perform a SAP PM maintenance cycle. First check for notification approval events, then analyze sensors, and take appropriate action following the SAP PM process.{pending_context}"},
        ]
        
        iteration = 0
        max_iterations = 15
        
        while iteration < max_iterations:
            iteration += 1
            console.print(f"\n[dim]LLM Call #{iteration}...[/dim]")
            
            try:
                response = await self.call_llm(messages)
            except httpx.HTTPStatusError as e:
                console.print(f"[red]HTTP Error: {e.response.status_code} - {e.response.text}[/red]")
                return f"Error calling LLM: {e}"
            except Exception as e:
                console.print(f"[red]Error calling LLM: {e}[/red]")
                return f"Error: {e}"
            
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "")
            
            tool_calls = message.get("tool_calls", [])
            
            if tool_calls:
                messages.append(message)
                
                for tool_call in tool_calls:
                    func = tool_call.get("function", {})
                    tool_name = func.get("name", "")
                    tool_id = tool_call.get("id", "")
                    
                    try:
                        arguments = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        arguments = {}
                    
                    console.print(f"  [bold magenta]🔧 Tool Call:[/bold magenta] [cyan]{tool_name}[/cyan]")
                    if arguments:
                        # Truncate long arguments for display
                        args_display = json.dumps(arguments)
                        if len(args_display) > 200:
                            args_display = args_display[:200] + "..."
                        console.print(f"     [dim]Args: {args_display}[/dim]")
                    
                    tool_result = await self.execute_tool(tool_name, arguments)
                    
                    self.track_tool_result(tool_name, arguments, tool_result)
                    
                    display_result = tool_result[:300] + "..." if len(tool_result) > 300 else tool_result
                    console.print(f"     [dim]Result: {display_result}[/dim]")
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": tool_result,
                    })
            
            elif finish_reason == "stop" or not tool_calls:
                final_content = message.get("content", "No response generated")
                
                console.print("\n")
                console.print(Panel(
                    final_content,
                    title="📋 SAP PM Assessment",
                    border_style="green",
                    padding=(1, 2),
                ))
                
                return final_content
        
        return "Max iterations reached without final response"

    async def main_loop(self) -> None:
        """Main agent loop - check every 60 seconds."""
        console.print(Panel(
            "[bold green]🏭 SAP PM AUTONOMOUS MAINTENANCE AGENT[/bold green]\n\n"
            f"[cyan]Model:[/cyan] {LLM_MODEL}\n"
            f"[cyan]API Base:[/cyan] {API_BASE}\n"
            f"[cyan]Check Interval:[/cyan] {CHECK_INTERVAL}s\n"
            f"[cyan]MCP Server:[/cyan] {MCP_SERVER_PATH}\n\n"
            "[bold]SAP PM Process Flow:[/bold]\n"
            "  1. [yellow]Detect Anomaly[/yellow] → Create PM Notification\n"
            "  2. [cyan]BPA Approval[/cyan] → Notification Approved/Rejected\n"
            "  3. [green]Approved[/green] → Create PM Work Order\n\n"
            "[bold]Notification Types:[/bold]\n"
            "  • [red]M1[/red] - Malfunction Report (critical issues)\n"
            "  • [yellow]M2[/yellow] - Maintenance Request (warnings)\n\n"
            "[dim]Press Ctrl+C to shutdown gracefully[/dim]",
            title="🚀 Starting Up",
            border_style="green",
            box=box.DOUBLE,
        ))
        
        if not API_KEY:
            console.print("[bold red]❌ ERROR: API_KEY not set in .env file[/bold red]")
            return
        
        try:
            await self.connect_to_mcp()
        except Exception as e:
            console.print(f"[bold red]❌ Failed to connect to MCP server: {e}[/bold red]")
            console.print("[yellow]Make sure the MCP server path is correct and the server is available.[/yellow]")
            return
        
        console.print("\n[bold green]✓ Agent initialized successfully![/bold green]")
        console.print(f"[dim]Starting SAP PM maintenance loop (checking every {CHECK_INTERVAL}s)...[/dim]\n")
        
        try:
            while self.running:
                try:
                    await self.run_maintenance_cycle()
                except Exception as e:
                    console.print(f"[red]Error in maintenance cycle: {e}[/red]")
                
                # Display stats
                stats_table = Table(show_header=False, box=box.ROUNDED)
                stats_table.add_column("Stat", style="cyan")
                stats_table.add_column("Value", style="white")
                stats_table.add_row("Total Cycles", str(self.cycle_count))
                stats_table.add_row("PM Notifications Created", str(self.notifications_created))
                stats_table.add_row("Notifications Approved", str(self.notifications_approved))
                stats_table.add_row("Notifications Rejected", str(self.notifications_rejected))
                stats_table.add_row("Pending BPA Approval", str(len(self.pending_notifications)))
                stats_table.add_row("PM Work Orders Created", str(self.workorders_created))
                stats_table.add_row("Next Check", f"in {CHECK_INTERVAL}s")
                
                console.print(Panel(stats_table, title="📊 SAP PM Agent Stats", border_style="dim"))
                
                console.print(f"\n[dim]Sleeping for {CHECK_INTERVAL} seconds...[/dim]")
                await asyncio.sleep(CHECK_INTERVAL)
                
        except asyncio.CancelledError:
            console.print("\n[yellow]Agent loop cancelled[/yellow]")
        finally:
            await self.disconnect()

    def shutdown(self) -> None:
        """Signal the agent to shutdown gracefully."""
        console.print("\n[bold yellow]🛑 Shutdown signal received...[/bold yellow]")
        self.running = False


async def main():
    """Entry point for the maintenance agent."""
    agent = MaintenanceAgent()
    
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        agent.shutdown()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await agent.main_loop()
    finally:
        console.print(Panel(
            f"[bold]SAP PM Agent Statistics[/bold]\n\n"
            f"Total Cycles: {agent.cycle_count}\n"
            f"PM Notifications Created: {agent.notifications_created}\n"
            f"Notifications Approved: {agent.notifications_approved}\n"
            f"Notifications Rejected: {agent.notifications_rejected}\n"
            f"PM Work Orders Created: {agent.workorders_created}",
            title="👋 Agent Shutdown Complete",
            border_style="blue",
        ))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold green]✓ Agent terminated by user[/bold green]")
