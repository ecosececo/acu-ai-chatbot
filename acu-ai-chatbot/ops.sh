#!/bin/bash
# ACU Chatbot Operations Helper
# Simplifies common Docker and scraping operations
#
# Usage:
#   ./ops.sh start           # Start all services
#   ./ops.sh stop            # Stop all services
#   ./ops.sh scrape main     # Scrape main site
#   ./ops.sh scrape bologna  # Scrape Bologna system
#   ./ops.sh scrape all      # Scrape both
#   ./ops.sh scrape main --clear  # Clear + re-scrape main
#   ./ops.sh stats           # Show database stats
#   ./ops.sh logs web        # View webapp logs
#   ./ops.sh shell           # Shell into webapp container

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "\n${BLUE}════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}! $1${NC}"
}

check_docker() {
    if ! command -v docker-compose &> /dev/null; then
        print_error "docker-compose not found. Please install Docker Desktop."
        exit 1
    fi
    print_success "Docker found"
}

start_services() {
    print_header "STARTING SERVICES"
    docker-compose up -d
    print_success "Services started"
    print_warning "Waiting for services to be ready (30-60 seconds)..."
    sleep 10

    print_header "INITIALIZING DATABASE"
    docker-compose exec -T webapp python manage.py migrate --noinput
    docker-compose exec -T webapp python manage.py collectstatic --noinput
    print_success "Database initialized"
}

stop_services() {
    print_header "STOPPING SERVICES"
    docker-compose down
    print_success "Services stopped"
}

scrape_source() {
    local source=$1
    shift
    local args="$@"

    print_header "SCRAPING: $source"

    if [[ "$args" == *"--clear"* ]]; then
        print_warning "This will DELETE existing data and re-scrape"
    fi

    case $source in
        main)
            docker-compose exec -T webapp python manage.py scrape_acu --source=main $args
            ;;
        bologna)
            docker-compose exec -T webapp python manage.py scrape_acu --source=bologna $args
            ;;
        all)
            docker-compose exec -T webapp python manage.py scrape_acu --source=all $args
            ;;
        *)
            print_error "Unknown source: $source"
            echo "Valid sources: main, bologna, all"
            exit 1
            ;;
    esac

    print_success "Scraping complete"
    show_stats
}

show_stats() {
    print_header "DATABASE STATISTICS"
    docker-compose exec -T webapp python -c "
from chat.models import WebPage, DocumentChunk
from chat.services.rag_service import rag_service

stats = rag_service.get_stats()
print(f'Total pages:        {stats[\"total_pages\"]}')
print(f'Processed pages:    {stats[\"processed_pages\"]}')
print(f'Total chunks:       {stats[\"total_chunks\"]}')
print(f'Embedded chunks:    {stats[\"embedded_chunks\"]}')
print(f'Coverage:           {stats[\"coverage\"]}')

print()
main = WebPage.objects.filter(source='main').count()
bologna = WebPage.objects.filter(source='bologna').count()
print(f'Main site pages:    {main}')
print(f'Bologna pages:      {bologna}')

print()
main_chunks = DocumentChunk.objects.filter(web_page__source='main').count()
bologna_chunks = DocumentChunk.objects.filter(web_page__source='bologna').count()
print(f'Main chunks:        {main_chunks}')
print(f'Bologna chunks:     {bologna_chunks}')
"
}

view_logs() {
    local service=${1:-webapp}
    print_header "LOGS: $service"
    docker-compose logs -f --tail=100 $service
}

shell_webapp() {
    print_header "ENTERING WEBAPP SHELL"
    docker-compose exec webapp bash
}

show_help() {
    cat << EOF
${BLUE}ACU Chatbot Operations${NC}

STARTUP:
  ${GREEN}./ops.sh start${NC}              Start all services
  ${GREEN}./ops.sh stop${NC}               Stop all services

SCRAPING:
  ${GREEN}./ops.sh scrape main${NC}        Scrape main site (acibadem.edu.tr)
  ${GREEN}./ops.sh scrape bologna${NC}     Scrape Bologna system (obs.acibadem.edu.tr)
  ${GREEN}./ops.sh scrape all${NC}         Scrape both sites
  ${GREEN}./ops.sh scrape main --clear${NC} Clear data + re-scrape

MANAGEMENT:
  ${GREEN}./ops.sh stats${NC}              Show database statistics
  ${GREEN}./ops.sh logs [service]${NC}     View service logs (default: webapp)
  ${GREEN}./ops.sh shell${NC}              Open webapp container shell

EXAMPLES:
  Start fresh:
    ${YELLOW}./ops.sh start${NC}
    ${YELLOW}./ops.sh scrape all${NC}

  Update Bologna data:
    ${YELLOW}./ops.sh scrape bologna --clear${NC}

  Check progress:
    ${YELLOW}./ops.sh stats${NC}

  Debug issues:
    ${YELLOW}./ops.sh logs${NC}
    ${YELLOW}./ops.sh shell${NC}

For detailed documentation, see: SCRAPING_GUIDE.md
EOF
}

main() {
    check_docker

    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    case "$1" in
        start)
            start_services
            ;;
        stop)
            stop_services
            ;;
        scrape)
            if [ $# -lt 2 ]; then
                print_error "Usage: ./ops.sh scrape [main|bologna|all] [options]"
                exit 1
            fi
            scrape_source "$2" "${@:3}"
            ;;
        stats)
            show_stats
            ;;
        logs)
            view_logs "${2:-webapp}"
            ;;
        shell)
            shell_webapp
            ;;
        help|-h|--help)
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
