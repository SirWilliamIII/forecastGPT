#!/bin/bash
# Setup script for BloombergGPT LaunchAgent services

set -e

PROJECT_DIR="/Users/will/Programming/Projects/bloombergGPT"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "========================================="
echo "BloombergGPT Services Setup"
echo "========================================="
echo ""

# Function to install a service
install_service() {
    local plist_name=$1
    local plist_path="$PROJECT_DIR/$plist_name"
    local target_path="$LAUNCH_AGENTS_DIR/$plist_name"

    if [ -f "$plist_path" ]; then
        echo "Installing $plist_name..."
        cp "$plist_path" "$target_path"
        launchctl load "$target_path"
        echo "✓ $plist_name installed and started"
    else
        echo "✗ $plist_path not found"
    fi
}

# Function to uninstall a service
uninstall_service() {
    local plist_name=$1
    local target_path="$LAUNCH_AGENTS_DIR/$plist_name"

    if [ -f "$target_path" ]; then
        echo "Uninstalling $plist_name..."
        launchctl unload "$target_path" 2>/dev/null || true
        rm "$target_path"
        echo "✓ $plist_name uninstalled"
    else
        echo "✗ $plist_name not installed"
    fi
}

# Function to check service status
check_status() {
    local plist_name=$1
    local label="${plist_name%.plist}"

    if launchctl list | grep -q "$label"; then
        echo "✓ $label is running"
    else
        echo "✗ $label is not running"
    fi
}

# Main menu
case "${1:-install}" in
    install)
        echo "Installing services..."
        echo ""

        # Create logs directory
        mkdir -p "$PROJECT_DIR/logs"

        # Install database service
        install_service "com.bloomberggpt.database.plist"
        echo ""

        # Wait for database to start
        echo "Waiting 5 seconds for database to initialize..."
        sleep 5
        echo ""

        # Install backend service
        install_service "com.bloomberggpt.backend.plist"
        echo ""

        echo "========================================="
        echo "Installation complete!"
        echo "========================================="
        echo ""
        echo "Services:"
        echo "  Database: http://localhost:8080 (Adminer)"
        echo "  Backend:  http://localhost:9000"
        echo ""
        echo "Logs:"
        echo "  Database: $PROJECT_DIR/logs/database-*.log"
        echo "  Backend:  $PROJECT_DIR/logs/backend-*.log"
        echo ""
        echo "Useful commands:"
        echo "  ./setup-services.sh status   - Check service status"
        echo "  ./setup-services.sh restart  - Restart all services"
        echo "  ./setup-services.sh stop     - Stop all services"
        echo "  ./setup-services.sh uninstall - Uninstall all services"
        echo ""
        ;;

    uninstall)
        echo "Uninstalling services..."
        echo ""
        uninstall_service "com.bloomberggpt.backend.plist"
        uninstall_service "com.bloomberggpt.database.plist"
        echo ""
        echo "Services uninstalled."
        echo ""
        ;;

    stop)
        echo "Stopping services..."
        echo ""
        launchctl unload "$LAUNCH_AGENTS_DIR/com.bloomberggpt.backend.plist" 2>/dev/null || true
        launchctl unload "$LAUNCH_AGENTS_DIR/com.bloomberggpt.database.plist" 2>/dev/null || true
        echo "Services stopped."
        echo ""
        ;;

    start)
        echo "Starting services..."
        echo ""
        launchctl load "$LAUNCH_AGENTS_DIR/com.bloomberggpt.database.plist" 2>/dev/null || true
        sleep 3
        launchctl load "$LAUNCH_AGENTS_DIR/com.bloomberggpt.backend.plist" 2>/dev/null || true
        echo "Services started."
        echo ""
        ;;

    restart)
        echo "Restarting services..."
        echo ""
        $0 stop
        sleep 2
        $0 start
        echo "Services restarted."
        echo ""
        ;;

    status)
        echo "Service Status:"
        echo ""
        check_status "com.bloomberggpt.database.plist"
        check_status "com.bloomberggpt.backend.plist"
        echo ""

        # Show recent log entries
        echo "Recent Backend Logs:"
        if [ -f "$PROJECT_DIR/logs/backend-stdout.log" ]; then
            tail -5 "$PROJECT_DIR/logs/backend-stdout.log"
        else
            echo "(no logs yet)"
        fi
        echo ""
        ;;

    logs)
        # Follow logs in real-time
        echo "Following backend logs (Ctrl+C to exit)..."
        tail -f "$PROJECT_DIR/logs/backend-stdout.log" "$PROJECT_DIR/logs/backend-stderr.log"
        ;;

    *)
        echo "Usage: $0 {install|uninstall|start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  install    - Install and start all services"
        echo "  uninstall  - Stop and remove all services"
        echo "  start      - Start services"
        echo "  stop       - Stop services"
        echo "  restart    - Restart services"
        echo "  status     - Check service status"
        echo "  logs       - Follow backend logs in real-time"
        exit 1
        ;;
esac
