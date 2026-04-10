"""PLC deployment endpoint handlers."""

from server_config import logger


class PlcHandlersMixin:
    def handle_plc_targets(self, params):
        """Handle plc/targets endpoint."""
        logger.info("PLC target discovery requested")
        script = self.script_generator.generate_plc_targets_script(params)
        result = self.script_executor.execute_script(script, timeout=30)
        self._send_plc_result(result, "discovering PLC targets")

    def handle_plc_validate_deploy(self, params):
        """Handle plc/validate-deploy endpoint."""
        logger.info("PLC deploy validation requested")
        script = self.script_generator.generate_plc_validate_deploy_script(params)
        result = self.script_executor.execute_script(script, timeout=30)
        self._send_plc_result(result, "validating PLC deploy")

    def handle_plc_gateways(self, params):
        """Handle plc/gateways endpoint."""
        logger.info("PLC gateway discovery requested")
        script = self.script_generator.generate_plc_gateways_script(params)
        result = self.script_executor.execute_script(script, timeout=30)
        self._send_plc_result(result, "discovering PLC gateways")

    def handle_plc_scan(self, params):
        """Handle plc/scan endpoint."""
        logger.info("PLC network scan requested")
        script = self.script_generator.generate_plc_scan_script(params)
        timeout = int(params.get("timeout", 60))
        result = self.script_executor.execute_script(script, timeout=timeout)
        self._send_plc_result(result, "scanning PLC network")

    def handle_plc_status(self, params):
        """Handle plc/status endpoint."""
        logger.info("PLC application status requested")
        script = self.script_generator.generate_plc_status_script(params)
        timeout = int(params.get("timeout", 60))
        result = self.script_executor.execute_script(script, timeout=timeout)
        self._send_plc_result(result, "checking PLC status")

    def handle_plc_bindings(self, params):
        """Handle plc/bindings endpoint."""
        logger.info("PLC binding list requested")
        script = self.script_generator.generate_plc_bindings_script(params)
        result = self.script_executor.execute_script(script, timeout=30)
        self._send_plc_result(result, "listing PLC bindings")

    def handle_plc_bind_ip(self, params):
        """Handle plc/bind-ip endpoint."""
        logger.info("PLC IP bind requested")
        script = self.script_generator.generate_plc_bind_ip_script(params)
        timeout = int(params.get("timeout", 30))
        result = self.script_executor.execute_script(script, timeout=timeout)
        self._send_plc_result(result, "binding PLC IP")

    def _send_plc_result(self, result, action):
        if result.get("success", False):
            self.send_json_response(result)
            return

        error_msg = result.get("error", "Unknown error")
        logger.error("Error %s: %s", action, error_msg)
        self.send_json_response({
            "success": False,
            "error": error_msg,
            "details": result
        }, 500)
