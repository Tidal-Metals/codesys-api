"""Mapping, COM/master, and utility handlers for Modbus API."""

from __future__ import annotations

import modbus_scripts


class ModbusMappingMiscMixin:
    def get_mapping(self, params, groups):
        snapshot = self._export_io_snapshot(groups["device"])
        if not snapshot.get("success"):
            return snapshot

        mappings = []
        leaf_index = params.get("leafIndex")
        leaf_idx = self._leaf_row_for_channel(snapshot["rows"], groups["channel"], leaf_index=leaf_index)
        header_iec = ""
        for row in snapshot["rows"]:
            if self._row_param_name(row) == groups["channel"]:
                header_iec = self._row_iec(row)
                break
        if leaf_idx is not None:
            row = snapshot["rows"][leaf_idx]
            variable = self._row_variable(row)
            if variable:
                mappings.append({
                    "variable": variable,
                    "iecAddress": self._row_iec(row) or header_iec,
                    "nodeVisibleName": self._row_param_name(row),
                    "nodeDepth": 1,
                })
        return {
            "success": leaf_idx is not None,
            "device": groups["device"],
            "channel": groups["channel"],
            "iecAddress": header_iec,
            "resolvedDepth": 1 if leaf_idx is not None else 0,
            "resolvedType": "WORD" if leaf_idx is not None else "",
            "resolvedVisibleName": self._row_param_name(snapshot["rows"][leaf_idx]) if leaf_idx is not None else "",
            "leafIndex": leaf_index,
            "mappings": mappings,
            "source": "io_csv",
            "error": None if leaf_idx is not None else f"Channel IO row not found: {groups['channel']}",
        }

    def set_mapping(self, params, groups):
        if "variable" not in params:
            return {"success": False, "error": "Missing required parameter: variable"}
        canonical = self._canonical_variable_name(params["variable"])
        aliases = self._variable_aliases(canonical)

        devices_result = self._all_modbus_device_names()
        if not devices_result.get("success"):
            return devices_result

        modified_devices = []
        target_found = False
        target_iec = ""

        for device_name in devices_result.get("devices", []):
            snapshot = self._export_io_snapshot(device_name)
            if not snapshot.get("success"):
                return snapshot

            changed = False
            leaf_idx = None
            if device_name == groups["device"]:
                leaf_idx = self._leaf_row_for_channel(
                    snapshot["rows"],
                    groups["channel"],
                    leaf_index=params.get("leafIndex"),
                )
                if leaf_idx is None:
                    return {"success": False, "error": f"Channel IO row not found: {groups['channel']}", "device": device_name}
                target_found = True

            for idx, row in enumerate(snapshot["rows"]):
                current_var = self._row_variable(row)
                if current_var in aliases:
                    if not (device_name == groups["device"] and idx == leaf_idx):
                        snapshot["rows"][idx][0] = ""
                        changed = True

            if device_name == groups["device"] and leaf_idx is not None:
                current_value = self._row_variable(snapshot["rows"][leaf_idx])
                if current_value != canonical:
                    snapshot["rows"][leaf_idx][0] = canonical
                    changed = True
                target_iec = self._row_iec(snapshot["rows"][leaf_idx])

            if changed:
                import_result = self._write_io_snapshot(snapshot)
                if not import_result.get("success"):
                    import_result["device"] = device_name
                    return import_result
                modified_devices.append(device_name)

        if not target_found:
            return {"success": False, "error": f"Target channel not found: {groups['device']}/{groups['channel']}"}

        return {
            "success": True,
            "device": groups["device"],
            "channel": groups["channel"],
            "variable": canonical,
            "iecAddress": target_iec,
            "leafIndex": params.get("leafIndex"),
            "modifiedDevices": modified_devices,
            "source": "io_csv_import",
        }

    def clear_mapping(self, params, groups):
        snapshot = self._export_io_snapshot(groups["device"])
        if not snapshot.get("success"):
            return snapshot

        leaf_idx = self._leaf_row_for_channel(
            snapshot["rows"],
            groups["channel"],
            leaf_index=params.get("leafIndex"),
        )
        if leaf_idx is None:
            return {"success": False, "error": f"Channel IO row not found: {groups['channel']}"}

        removed = 1 if self._row_variable(snapshot["rows"][leaf_idx]) else 0
        snapshot["rows"][leaf_idx][0] = ""
        import_result = self._write_io_snapshot(snapshot)
        if not import_result.get("success"):
            return import_result

        return {
            "success": True,
            "device": groups["device"],
            "channel": groups["channel"],
            "leafIndex": params.get("leafIndex"),
            "removedMappings": removed,
            "source": "io_csv_import",
        }

    def get_com(self, params, groups):
        script = modbus_scripts.get_com_params(groups["device"])
        return self._exec(script)

    def update_com(self, params, groups):
        script = modbus_scripts.update_com_params(
            groups["device"],
            com_port=params.get("comPort", params.get("ComPort")),
            baudrate=params.get("baudrate", params.get("Baudrate")),
            data_bits=params.get("dataBits", params.get("DataBits")),
            parity=params.get("parity", params.get("Parity")),
            stop_bits=params.get("stopBits", params.get("StopBits")),
        )
        return self._exec(script)

    def get_master(self, params, groups):
        script = modbus_scripts.get_master_params(groups["device"])
        return self._exec(script)

    def update_master(self, params, groups):
        script = modbus_scripts.update_master_params(
            groups["device"],
            optimization_on=params.get("optimizationOn", params.get("OptimizationOn")),
            auto_restart_communication=params.get(
                "autoRestartCommunication",
                params.get("AutoRestartCommunication", params.get("auto-restart communication")),
            ),
        )
        return self._exec(script)

    def save_project(self, params, groups):
        script = modbus_scripts.save_project()
        result = self._exec(script)
        if isinstance(result, dict):
            result["deprecated"] = True
            result["deprecatedEndpoint"] = "/api/v1/modbus/save"
            result["canonicalEndpoint"] = "/api/v1/project/save"
        return result

    def export_io(self, params, groups):
        if "filePath" not in params:
            return {"success": False, "error": "Missing required parameter: filePath"}

        script = modbus_scripts.export_io_csv(groups["device"], params["filePath"])
        return self._exec(script)

    def find_variable(self, params, groups):
        variable = params.get("variable", params.get("name", ""))
        if not variable:
            return {"success": False, "error": "Missing required parameter: variable"}
        canonical = self._canonical_variable_name(variable)
        aliases = self._variable_aliases(canonical)

        devices_result = self._all_modbus_device_names()
        if not devices_result.get("success"):
            return devices_result

        matches = []
        for device_name in devices_result.get("devices", []):
            snapshot = self._export_io_snapshot(device_name)
            if not snapshot.get("success"):
                return snapshot
            current_channel = ""
            current_header_iec = ""
            for row in snapshot["rows"]:
                param_name = self._row_param_name(row)
                variable_value = self._row_variable(row)
                if param_name and not param_name.startswith("Bit") and "[" not in param_name:
                    current_channel = param_name
                    current_header_iec = self._row_iec(row)
                if variable_value in aliases:
                    match_type = "exact" if variable_value == canonical else "alias"
                    matches.append({
                        "device": device_name,
                        "channel": current_channel,
                        "channelType": "Input",
                        "variable": variable_value,
                        "canonicalVariable": canonical,
                        "matchType": match_type,
                        "iecAddress": self._row_iec(row) or current_header_iec,
                        "nodeVisibleName": param_name,
                        "nodeDepth": 1 if "[" in param_name else 0,
                        "source": "io_csv",
                    })

        return {
            "success": True,
            "input": variable,
            "canonicalVariable": canonical,
            "devicesChecked": devices_result.get("devices", []),
            "matchCount": len(matches),
            "matches": matches,
            "source": "io_csv",
        }

    def validate_mappings(self, params, groups):
        script = modbus_scripts.validate_mappings(params.get("device"))
        return self._exec(script, timeout=180)

    def normalize_iec_addresses(self, params, groups):
        script = modbus_scripts.normalize_iec_addresses(
            device_name=params.get("device"),
            start_word=params.get("startWord", 0),
        )
        return self._exec(script, timeout=180)
