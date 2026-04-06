#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTRACTOR="${ROOT_DIR}/scripts/src/extract_urdf_params.py"
CONTENT_MODE="all"
EXISTING_MODE="skip"
INERTIALS_NAME="nominal"
MODE="test"
ARM_SOURCE_INPUT=""
EE_SOURCE_INPUT=""
ARM_TARGET_NAME=""
EE_TARGET_NAME=""

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
    --arm-source)
      ARM_SOURCE_INPUT="${2:-}"
      if [[ -z "${ARM_SOURCE_INPUT}" ]]; then
        echo "Missing value for --arm-source" >&2
        exit 1
      fi
      shift 2
      ;;
    --ee-source)
      EE_SOURCE_INPUT="${2:-}"
      if [[ -z "${EE_SOURCE_INPUT}" ]]; then
        echo "Missing value for --ee-source" >&2
        exit 1
      fi
      shift 2
      ;;
    --arm-target)
      ARM_TARGET_NAME="${2:-}"
      if [[ -z "${ARM_TARGET_NAME}" ]]; then
        echo "Missing value for --arm-target" >&2
        exit 1
      fi
      shift 2
      ;;
    --ee-target)
      EE_TARGET_NAME="${2:-}"
      if [[ -z "${EE_TARGET_NAME}" ]]; then
        echo "Missing value for --ee-target" >&2
        exit 1
      fi
      shift 2
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
Usage: bash scripts/dev_extract_arm_with_ee.sh [test|release] [--arm-source arm_source_urdf_or_package] [--ee-source ee_source_urdf_or_package] [--arm-target arm_target_or_test_name] [--ee-target ee_target_name_if_release] [--inertials-only] [--inertials-name name] [--existing overwrite|skip]
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
  echo "Usage: $0 [test|release] [--arm-source arm_source_urdf_or_package] [--ee-source ee_source_urdf_or_package] [--arm-target arm_target_or_test_name] [--ee-target ee_target_name_if_release] [--inertials-only] [--inertials-name name] [--existing overwrite|skip]" >&2
  exit 1
fi

if [[ -z "${ARM_SOURCE_INPUT}" ]]; then
  echo "Missing required argument: --arm-source" >&2
  exit 1
fi

if [[ -z "${EE_SOURCE_INPUT}" ]]; then
  echo "Missing required argument: --ee-source" >&2
  exit 1
fi

if [[ -z "${ARM_TARGET_NAME}" ]]; then
  echo "Missing required argument: --arm-target" >&2
  exit 1
fi

if [[ "${MODE}" == "release" && -z "${EE_TARGET_NAME}" ]]; then
  echo "Missing required argument in release mode: --ee-target" >&2
  exit 1
fi

ARM_SOURCE_URDF="$(resolve_source_urdf "${ARM_SOURCE_INPUT}")"
EE_SOURCE_URDF="$(resolve_source_urdf "${EE_SOURCE_INPUT}")"

if [[ "${MODE}" == "release" ]]; then
  ARM_TARGET_NAME="${ARM_TARGET_NAME}"
  EE_TARGET_NAME="${EE_TARGET_NAME}"
else
  TEST_NAME="${ARM_TARGET_NAME}"
fi

if [[ "${MODE}" == "release" ]]; then
  ARM_OUTPUT_DIR="${ROOT_DIR}/assets/robot/openarm_v2.0/config/${ARM_TARGET_NAME}"
  ARM_MESH_COPY_TO="${ROOT_DIR}/assets/robot/openarm_v2.0/meshes/${ARM_TARGET_NAME}"
  ARM_MESH_PREFIX="package://openarm_description/assets/robot/openarm_v2.0/meshes/${ARM_TARGET_NAME}"
  EE_OUTPUT_DIR="${ROOT_DIR}/assets/end_effector/${EE_TARGET_NAME}/config"
  EE_MESH_COPY_TO="${ROOT_DIR}/assets/end_effector/${EE_TARGET_NAME}/meshes"
  EE_MESH_PREFIX="package://openarm_description/assets/end_effector/${EE_TARGET_NAME}/meshes"
else
  OUT_ROOT="${ROOT_DIR}/assets/robot/openarm_v2.0/base_urdf_ws/extracted/${TEST_NAME}"
  ARM_OUTPUT_DIR="${OUT_ROOT}/arm_config"
  ARM_MESH_COPY_TO="${OUT_ROOT}/arm_meshes"
  ARM_MESH_PREFIX="package://openarm_description/assets/robot/openarm_v2.0/base_urdf_ws/extracted/${TEST_NAME}/arm_meshes"
  EE_OUTPUT_DIR="${OUT_ROOT}/ee_config"
  EE_MESH_COPY_TO="${OUT_ROOT}/ee_meshes"
  EE_MESH_PREFIX="package://openarm_description/assets/robot/openarm_v2.0/base_urdf_ws/extracted/${TEST_NAME}/ee_meshes"
fi

ARM_CMD=(
  python3 "${EXTRACTOR}"
  --urdf "${ARM_SOURCE_URDF}"
  --output-dir "${ARM_OUTPUT_DIR}"
  --configs-layout tree
  --inertials-name "${INERTIALS_NAME}"
  --content "${CONTENT_MODE}"
  --existing-config "${EXISTING_MODE}"
  --existing-mesh "${EXISTING_MODE}"
  --existing-inertials "${EXISTING_MODE}"
)

EE_CMD=(
  python3 "${EXTRACTOR}"
  --urdf "${EE_SOURCE_URDF}"
  --output-dir "${EE_OUTPUT_DIR}"
  --configs-layout tree
  --inertials-name "${INERTIALS_NAME}"
  --content "${CONTENT_MODE}"
  --existing-config "${EXISTING_MODE}"
  --existing-mesh "${EXISTING_MODE}"
  --existing-inertials "${EXISTING_MODE}"
)

if [[ "${CONTENT_MODE}" != "inertials" ]]; then
  ARM_CMD+=(
    --mesh-copy-to "${ARM_MESH_COPY_TO}"
    --mesh-prefix "${ARM_MESH_PREFIX}"
  )
  EE_CMD+=(
    --mesh-copy-to "${EE_MESH_COPY_TO}"
    --mesh-prefix "${EE_MESH_PREFIX}"
  )
fi

"${ARM_CMD[@]}"
"${EE_CMD[@]}"
