from pathlib import Path

ASSETS_ROOT = Path(__file__).resolve().parent

def get_v2_urdf_path() -> str:
    """
    assets/robot/openarm_v2.0/urdf/example/v2.urdf の絶対パスを返す
    """
    urdf_path = ASSETS_ROOT / "robot" / "openarm_v2.0" / "urdf" / "example" / "v2.urdf"
    if not urdf_path.exists():
        print(f"[Warning] URDF not found at: {urdf_path}")
    return str(urdf_path)

__all__ = ["get_v2_urdf_path", "ASSETS_ROOT"]