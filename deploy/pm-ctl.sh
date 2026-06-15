#!/bin/bash
SERVICES="pm-simulator pm-agent pm-arbitrator"

case "${1:-status}" in
  status)
    echo "SAP PM Demo — Service Status"
    echo "─────────────────────────────"
    for svc in $SERVICES; do
      status=$(systemctl is-active $svc 2>/dev/null)
      if [ "$status" = "active" ]; then
        printf "  ✅ %-20s running\n" "$svc"
      else
        printf "  ❌ %-20s %s\n" "$svc" "$status"
      fi
    done
    echo ""
    echo "Dashboard: http://$(hostname -f):9080/sap-pm-demo/dashboard"
    ;;
  start)
    echo "Starting services..."
    sudo systemctl start pm-simulator pm-arbitrator pm-agent
    echo "  ✓ All services started"
    ;;
  stop)
    echo "Stopping services..."
    sudo systemctl stop pm-agent pm-arbitrator pm-simulator
    echo "  ✓ All services stopped"
    ;;
  restart)
    echo "Restarting services..."
    sudo systemctl restart pm-simulator pm-arbitrator pm-agent
    echo "  ✓ All services restarted"
    ;;
  logs)
    journalctl -u pm-simulator -u pm-agent -u pm-arbitrator -f --no-hostname
    ;;
  *)
    echo "Usage: $0 {status|start|stop|restart|logs}"
    ;;
esac
