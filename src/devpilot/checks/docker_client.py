import docker


def get_docker_client() -> docker.DockerClient:
    """docker.from_env() honors DOCKER_HOST automatically -- pointed at the
    docker-socket-proxy in compose, or Docker Desktop's own pipe when run
    directly on Windows. No branching needed here for either case."""
    return docker.from_env()
