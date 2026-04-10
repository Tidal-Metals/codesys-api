"""Facade preserving the legacy ScriptGenerator API."""

from script_custom_generators import generate_script_execute_script
from script_pou_code_generators import (
    generate_pou_code_read_script,
    generate_pou_code_script,
)
from script_pou_create_generators import generate_pou_create_script
from script_pou_list_generators import generate_pou_list_script
from script_plc_generators import (
    generate_plc_gateways_script,
    generate_plc_scan_script,
    generate_plc_status_script,
    generate_plc_targets_script,
    generate_plc_validate_deploy_script,
)
from script_plc_binding_generators import (
    generate_plc_bind_ip_script,
    generate_plc_bindings_script,
)
from script_project_compile_generators import generate_project_compile_script
from script_project_generators import (
    generate_project_close_script,
    generate_project_create_script,
    generate_project_list_script,
    generate_project_open_script,
    generate_project_save_script,
)
from script_session_generators import (
    generate_session_start_script,
    generate_session_status_script,
)


class ScriptGenerator:
    """Generates scripts for different operations."""

    generate_session_start_script = staticmethod(generate_session_start_script)
    generate_session_status_script = staticmethod(generate_session_status_script)
    generate_project_create_script = staticmethod(generate_project_create_script)
    generate_project_open_script = staticmethod(generate_project_open_script)
    generate_project_save_script = staticmethod(generate_project_save_script)
    generate_project_close_script = staticmethod(generate_project_close_script)
    generate_project_list_script = staticmethod(generate_project_list_script)
    generate_project_compile_script = staticmethod(generate_project_compile_script)
    generate_pou_create_script = staticmethod(generate_pou_create_script)
    generate_pou_code_script = staticmethod(generate_pou_code_script)
    generate_pou_code_read_script = staticmethod(generate_pou_code_read_script)
    generate_pou_list_script = staticmethod(generate_pou_list_script)
    generate_plc_bind_ip_script = staticmethod(generate_plc_bind_ip_script)
    generate_plc_bindings_script = staticmethod(generate_plc_bindings_script)
    generate_plc_gateways_script = staticmethod(generate_plc_gateways_script)
    generate_plc_scan_script = staticmethod(generate_plc_scan_script)
    generate_plc_status_script = staticmethod(generate_plc_status_script)
    generate_plc_targets_script = staticmethod(generate_plc_targets_script)
    generate_plc_validate_deploy_script = staticmethod(generate_plc_validate_deploy_script)
    generate_script_execute_script = staticmethod(generate_script_execute_script)
