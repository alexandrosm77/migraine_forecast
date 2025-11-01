#!/bin/bash
# migraine_forecast_deploy.sh - Manual deployment script for Migraine Forecast app
# Usage: ./deploy.sh --dockerhub_username <username> --dockerhub_token <token>

# Log function for better visibility of what's happening
log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Configuration variables - customize these as needed
CONTAINER_NAME="migraine"
IMAGE_NAME="alexandrosm77/migraine_forecast:latest"
HOST_PORT=8889
CONTAINER_PORT=8889
# Add your data volume if needed:
DATA_VOLUME="/home/alexandros/migraine/db.sqlite3:/app/db.sqlite3"

# Default Docker Hub credentials
DOCKER_USERNAME=""
DOCKER_ACCESS_TOKEN=""

# Default Sentry configuration
SENTRY_DSN=""
SENTRY_ENABLED=""
SENTRY_ENVIRONMENT=""
SENTRY_TRACES_SAMPLE_RATE=""
SENTRY_PROFILES_SAMPLE_RATE=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --dockerhub_username)
      DOCKER_USERNAME="$2"
      shift 2
      ;;
    --dockerhub_token)
      DOCKER_ACCESS_TOKEN="$2"
      shift 2
      ;;
    --sentry_dsn)
      SENTRY_DSN="$2"
      shift 2
      ;;
    --sentry_enabled)
      SENTRY_ENABLED="$2"
      shift 2
      ;;
    --sentry_environment)
      SENTRY_ENVIRONMENT="$2"
      shift 2
      ;;
    --sentry_traces_sample_rate)
      SENTRY_TRACES_SAMPLE_RATE="$2"
      shift 2
      ;;
    --sentry_profiles_sample_rate)
      SENTRY_PROFILES_SAMPLE_RATE="$2"
      shift 2
      ;;
    *)
      log "Unknown option: $1"
      log "Usage: $0 --dockerhub_username <username> --dockerhub_token <token> [--sentry_dsn <dsn>] [--sentry_enabled <true|false>] [--sentry_environment <env>] [--sentry_traces_sample_rate <rate>] [--sentry_profiles_sample_rate <rate>]"
      exit 1
      ;;
  esac
done

log "Starting deployment of $IMAGE_NAME..."

# Check if Docker is running
if ! command -v docker &> /dev/null; then
  log "Error: Docker is not available. Is it installed and running?"
  exit 1
fi

# Docker Hub login using Access Token
log "Authenticating with Docker Hub..."
if [[ -z "$DOCKER_USERNAME" || -z "$DOCKER_ACCESS_TOKEN" ]]; then
  log "Docker Hub credentials not provided. Prompting for credentials..."
  read -p "Enter Docker Hub username: " DOCKER_USERNAME
  read -sp "Enter Docker Hub access token: " DOCKER_ACCESS_TOKEN
  echo
fi

if echo "$DOCKER_ACCESS_TOKEN" | docker login -u "$DOCKER_USERNAME" --password-stdin; then
  log "Successfully authenticated with Docker Hub"
else
  log "Error: Failed to authenticate with Docker Hub. Check your credentials."
  exit 1
fi

# Pull the latest image
log "Pulling the latest image..."
if docker pull "$IMAGE_NAME"; then
  log "Successfully pulled the latest image"
else
  log "Error pulling the latest image. Check your internet connection or Docker Hub credentials."
  exit 1
fi

# Check if the container already exists
if docker ps -a --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
  # Stop and remove the existing container
  log "Stopping and removing existing container..."
  docker stop "$CONTAINER_NAME"
  docker rm "$CONTAINER_NAME"
fi

# Create and start the new container
log "Creating and starting new container..."

# Uncomment and modify volume mounts if needed
VOLUME_PARAM="-v $DATA_VOLUME"

# Build environment variables
ENV_PARAMS="-e DJANGO_DEBUG=True"

# Add Sentry environment variables if provided
if [[ -n "$SENTRY_DSN" ]]; then
  ENV_PARAMS="$ENV_PARAMS -e SENTRY_DSN=$SENTRY_DSN"
fi
if [[ -n "$SENTRY_ENABLED" ]]; then
  ENV_PARAMS="$ENV_PARAMS -e SENTRY_ENABLED=$SENTRY_ENABLED"
fi
if [[ -n "$SENTRY_ENVIRONMENT" ]]; then
  ENV_PARAMS="$ENV_PARAMS -e SENTRY_ENVIRONMENT=$SENTRY_ENVIRONMENT"
fi
if [[ -n "$SENTRY_TRACES_SAMPLE_RATE" ]]; then
  ENV_PARAMS="$ENV_PARAMS -e SENTRY_TRACES_SAMPLE_RATE=$SENTRY_TRACES_SAMPLE_RATE"
fi
if [[ -n "$SENTRY_PROFILES_SAMPLE_RATE" ]]; then
  ENV_PARAMS="$ENV_PARAMS -e SENTRY_PROFILES_SAMPLE_RATE=$SENTRY_PROFILES_SAMPLE_RATE"
fi

docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p "$HOST_PORT:$CONTAINER_PORT" \
  $VOLUME_PARAM \
  $ENV_PARAMS \
  "$IMAGE_NAME"

# Check if the container started successfully
if docker ps --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
  log "Deployment successful! Container is running."
  log "You can access the application at http://$(hostname -I | awk '{print $1}'):$HOST_PORT"

  # Show container logs
  log "Container logs (last 5 lines):"
  docker logs "$CONTAINER_NAME" --tail 5
else
  log "Error: Container failed to start. Check Docker logs for details."
  exit 1
fi

# Show some helpful commands
log "Useful commands:"
log "  - View logs: docker logs $CONTAINER_NAME"
log "  - Shell access: docker exec -it $CONTAINER_NAME /bin/bash"
log "  - Stop container: docker stop $CONTAINER_NAME"
log "  - Start container: docker start $CONTAINER_NAME"
