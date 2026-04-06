#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTRACTOR="${ROOT_DIR}/scripts/src/extract_urdf_params.py"
CONTENT_MODE="all"
EXISTING_MODE="skip"
INERTIALS_NAME="nominal"
MODE="test"
SOURCE_INPUT=""
TARGET_NAME=""
COMPONENT_KIND=""

resolve_source_urdf() {
  local value="$1"
  if [[ -z "${value}" ]]; then
    return 1
  fi
  if [[ "${value}" == */* || "${value}" == *.urdf ]]; then
    printf '%s\n' "${value}"
    return 0
  fi
  printf '%s\n' "${ROOT_DIR}/assets/robot/openarm_v2.0/base_urdf_ws/urdf_paks/${value}/urdf/${value}.urdf"
}

POSITIONALS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    test|release)
      if [[ "${MODE}" != "test" || ${#POSITIONALS[@]} -gt 0 ]]; then
        echo "Mode may only be provided once." >&2
        exit 1
      fi
      MODE="$1"
      shift
      ;;
    --source)
      SOURCE_INPUT="${2:-}"
      if [[ -z "${SOURCE_INPUT}" ]]; then
        echo "Missing value for --source" >&2
        exit 1
      fi
      shift 2
      ;;
    --target)
      TARGET_NAME="${2:-}"
      if [[ -z "${TARGET_NAME}" ]]; then
        echo "Missing value for --target" >&2
        exit 1
      fi
      shift 2
      ;;
    --ee)
      COMPONENT_KIND="ee"
      shift
      ;;
    --inertials-only)
      CONTENT_MODE="inertials"
      shift
      ;;
    --inertials-name)
      INERTIALS_NAME="${2:-}"
      if [[ -z "${INERTIALS_NAME}" ]]; then
        echo "Missing value for --inertials-name" >&2
        exit 1
      fi
      shift 2
      ;;
    --existing)
      EXISTING_MODE="${2:-}"
      if [[ "${EXISTING_MODE}" != "overwrite" && "${EXISTING_MODE}" != "skip" ]]; then
        echo "Invalid value for --existing: ${EXISTING_MODE}. Use overwrite or skip." >&2
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      cat <<'EOF' >&2
Usage: bash scripts/dev_extract.sh [test|release] [--source source_urdf_or_package] [--target target_name] [--ee] [--inertials-only] [--inertials-name name] [--existing overwrite|skip]
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Use --help for usage." >&2
      exit 1
      ;;
  esac
done

if [[ "${MODE}" != "test" && "${MODE}" != "release" ]]; then
  echo "Usage: $0 [test|release] [--source source_urdf_or_package] [--target target_name] [--ee] [--inertials-only] [--inertials-name name] [--existing overwrite|skip]" >&2
  exit 1
fi

if [[ -z "${SOURCE_INPUT}" ]]; then
  echo "Missing required argument: --source" >&2
  exit 1
fi

if [[ -z "${TARGET_NAME}" ]]; then
  echo "Missing required argument: --target" >&2
  exit 1
fi

SOURCE_URDF="$(resolve_source_urdf "${SOURCE_INPUT}")"

if [[ -n "${COMPONENT_KIND}" && "${COMPONENT_KIND}" != "ee" ]]; then
  echo "Unsupported component selector: ${COMPONENT_KIND}. Omit it for arm/body-style output, or use ee." >&2
  exit 1
fi

if [[ "${MODE}" == "release" ]]; then
  if [[ "${COMPONENT_KIND}" == "ee" ]]; then
    OUTPUT_DIR="${ROOT_DIR}/assets/end_effector/${TARGET_NAME}/config"
    MESH_COPY_TO="${ROOT_DIR}/assets/end_effector/${TARGET_NAME}/meshes"
    MESH_PREFIX="package://openarm_description/assets/end_effector/${TARGET_NAME}/meshes"
  else
    OUTPUT_DIR="${ROOT_DIR}/assets/robot/openarm_v2.0/config/${TARGET_NAME}"
    MESH_COPY_TO="${ROOT_DIR}/assets/robot/openarm_v2.0/meshes/${TARGET_NAME}"
    MESH_PREFIX="package://openarm_description/assets/robot/openarm_v2.0/meshes/${TARGET_NAME}"
  fi
else
  OUT_ROOT="${ROOT_DIR}/assets/robot/openarm_v2.0/base_urdf_ws/extracted/${TARGET_NAME}"
  OUTPUT_DIR="${OUT_ROOT}/config"
  MESH_COPY_TO="${OUT_ROOT}/meshes"
  MESH_PREFIX="package://openarm_description/assets/robot/openarm_v2.0/base_urdf_ws/extracted/${TARGET_NAME}/meshes"
fi

CMD=(
  python3 "${EXTRACTOR}"
  --urdf "${SOURCE_URDF}"
  --output-dir "${OUTPUT_DIR}"
  --configs-layout tree
  --inertials-name "${INERTIALS_NAME}"
  --content "${CONTENT_MODE}"
  --existing-config "${EXISTING_MODE}"
  --existing-mesh "${EXISTING_MODE}"
  --existing-inertials "${EXISTING_MODE}"
)

if [[ "${CONTENT_MODE}" != "inertials" ]]; then
  CMD+=(
    --mesh-copy-to "${MESH_COPY_TO}"
    --mesh-prefix "${MESH_PREFIX}"
  )
fi

"${CMD[@]}"
