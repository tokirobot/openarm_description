from pathlib import Path

ASSETS_ROOT = Path(__file__).resolve().parent


def get_urdf_path(robot: str, *parts: str) -> Path:
    """
    get_urdf_path("openarm_v2.0", "example", "v2.urdf")
    get_urdf_path("openarm_v1.0", "openarm_v10.urdf.xacro")
    """
    path = ASSETS_ROOT / "robot" / robot / "urdf" / Path(*parts)
    if not path.exists():
        print(f"[Warning] URDF not found at: {path}")
    return path


def get_config_path(robot: str, *parts: str) -> Path:
    path = ASSETS_ROOT / "robot" / robot / "config" / Path(*parts)
    if not path.exists():
        print(f"[Warning] Config not found at: {path}")
    return path


ASSETS_ROOT = ASSETS_ROOT
__all__ = ["get_urdf_path", "get_config_path", "ASSETS_ROOT"]
