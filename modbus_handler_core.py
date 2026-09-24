"""Core helpers for Modbus API handlers."""

from __future__ import annotations

import csv
import os
import tempfile
import uuid

import modbus_scripts
from script_plc_generators import generate_plc_logout_script


def _param(params, camel_key, snake_key=None, default=None):
    """Read REST params accepting both canonical camelCase and snake_case aliases."""
    if camel_key in params:
        return params[camel_key]
    if snake_key and snake_key in params:
        return params[snake_key]
    return default


class ModbusHandlerCore:
    def __init__(self, script_executor):
        self.executor = script_executor

    def _exec(self, script, timeout=120):
        return self.executor.execute_script(script, timeout=timeout)

    @staticmethod
    def _canonical_variable_name(variable):
        variable = str(variable or "").strip()
        if not variable:
            return ""
        if "." not in variable:
            return f"Application.GVL.{variable}"
        if variable.startswith("GVL."):
            return f"Application.{variable}"
        return variable

    @staticmethod
    def _variable_aliases(variable):
        canonical = ModbusHandlerCore._canonical_variable_name(variable)
        if not canonical:
            return set()
        tail = canonical.split(".")[-1]
        return {
            canonical,
            tail,
            f"GVL.{tail}",
            f"Application.GVL.{tail}",
        }

    def _export_io_snapshot(self, device_name):
        temp_path = os.path.join(tempfile.gettempdir(), f"codesys_{device_name}_{uuid.uuid4().hex}.csv")
        export_result = self.export_io({"filePath": temp_path}, {"device": device_name})
        if not export_result.get("success"):
            return export_result

        prefix_lines = []
        data_lines = []
        with open(temp_path, "r", encoding="utf-8-sig", newline="") as handle:
            for line in handle:
                if line.startswith("//"):
                    prefix_lines.append(line.rstrip("\r\n"))
                else:
                    data_lines.append(line)

        rows = []
        if data_lines:
            reader = csv.reader(data_lines)
            for row in reader:
                if row:
                    rows.append(row)

        return {
            "success": True,
            "device": device_name,
            "filePath": temp_path,
            "prefixLines": prefix_lines,
            "rows": rows,
        }

    def _write_io_snapshot(self, snapshot):
        temp_path = os.path.join(tempfile.gettempdir(), f"codesys_{snapshot['device']}_{uuid.uuid4().hex}.csv")
        with open(temp_path, "w", encoding="utf-8", newline="") as handle:
            for line in snapshot.get("prefixLines", []):
                handle.write(line + "\n")
            writer = csv.writer(handle, lineterminator="\n")
            for row in snapshot.get("rows", []):
                writer.writerow(row)

        import_result = self._exec(modbus_scripts.import_io_csv(snapshot["device"], temp_path), timeout=120)
        if import_result.get("success"):
            import_result["file"] = temp_path
        return import_result

    @staticmethod
    def _row_param_name(row):
        return row[1].strip() if len(row) > 1 else ""

    @staticmethod
    def _row_variable(row):
        return row[0].strip() if len(row) > 0 else ""

    @staticmethod
    def _row_iec(row):
        return row[4].strip() if len(row) > 4 else ""

    @staticmethod
    def _leaf_row_for_channel(rows, channel_name, leaf_index=None):
        exact_leaf = f"{channel_name}[{0 if leaf_index is None else int(leaf_index)}]"
        for idx, row in enumerate(rows):
            param_name = ModbusHandlerCore._row_param_name(row)
            if param_name == exact_leaf:
                return idx
        if leaf_index is not None:
            return None
        for idx, row in enumerate(rows):
            param_name = ModbusHandlerCore._row_param_name(row)
            if param_name.startswith(f"{channel_name}["):
                return idx
        return None

    def _all_modbus_device_names(self):
        order_result = self._modbus_device_order()
        if not order_result.get("success"):
            return order_result
        return {"success": True, "devices": order_result.get("devices", [])}

    def _logout_application(self, application_path):
        script = generate_plc_logout_script({"applicationPath": application_path})
        return self._exec(script, timeout=60)

    def _modbus_device_order(self):
        result = self.list_devices({}, {})
        if not result.get("success"):
            return result

        ordered = []
        for plc in result.get("devices", []):
            for child in plc.get("children", []):
                if child.get("device_type") != 92:
                    continue
                for master in child.get("children", []):
                    if master.get("device_type") != 90:
                        continue
                    for device in master.get("children", []):
                        if device.get("device_type") == 91:
                            ordered.append(device.get("name"))
        return {"success": True, "devices": ordered, "raw": result}

    def _modbus_master_names(self):
        result = self.list_devices({}, {})
        if not result.get("success"):
            return result

        ordered = []
        for plc in result.get("devices", []):
            for child in plc.get("children", []):
                if child.get("device_type") != 92:
                    continue
                for master in child.get("children", []):
                    if master.get("device_type") != 90:
                        continue
                    name = master.get("name")
                    if name:
                        ordered.append(name)
        return {"success": True, "masters": ordered, "raw": result}

    def _device_context(self, device_name):
        result = self.list_devices({}, {})
        if not result.get("success"):
            return result

        for plc in result.get("devices", []):
            for com_device in plc.get("children", []):
                if com_device.get("device_type") != 92:
                    continue
                com_name = com_device.get("name")
                for master in com_device.get("children", []):
                    if master.get("device_type") != 90:
                        continue
                    master_name = master.get("name")
                    for device in master.get("children", []):
                        if device.get("device_type") != 91:
                            continue
                        if device.get("name") != device_name:
                            continue
                        params = device.get("params", {}) or {}
                        return {
                            "success": True,
                            "device": device_name,
                            "masterPath": "{0}.{1}".format(com_name, master_name),
                            "comDevice": com_name,
                            "masterName": master_name,
                            "slaveAddress": params.get("slaveAddress"),
                            "responseTimeout": params.get("responseTimeout"),
                            "raw": device,
                        }

        return {"success": False, "error": "Device not found in Modbus topology: {0}".format(device_name)}

    def _snapshot_device(self, device_name):
        device_result = self.get_device({}, {"device": device_name})
        if not device_result.get("success"):
            return device_result

        channels_result = self.list_channels({}, {"device": device_name})
        if not channels_result.get("success"):
            return channels_result

        params = device_result.get("device", {}).get("params", {})
        channels = channels_result.get("channels", [])
        mappings = []
        for channel in channels:
            mapping_result = self.get_mapping({}, {"device": device_name, "channel": channel["name"]})
            if mapping_result.get("success"):
                for mapping in mapping_result.get("mappings", []):
                    mappings.append({
                        "channel": channel["name"],
                        "variable": mapping.get("variable"),
                    })

        return {
            "success": True,
            "snapshot": {
                "name": device_name,
                "slaveAddress": params.get("SlaveAddress", params.get("ServerAddress", "1")),
                "responseTimeout": params.get("ResponseTimeout", "1000"),
                "channels": channels,
                "mappings": mappings,
            }
        }

    def _recreate_device_from_snapshot(self, snapshot, master_path, create_variable=True):
        create_result = self.create_device({
            "masterPath": master_path,
            "name": snapshot["name"],
            "slaveAddress": int(snapshot["slaveAddress"]),
        }, {})
        if not create_result.get("success"):
            return {"success": False, "stage": "create_device", "result": create_result}

        update_result = self.update_device({
            "responseTimeout": snapshot.get("responseTimeout"),
        }, {"device": snapshot["name"]})
        if not update_result.get("success"):
            return {"success": False, "stage": "update_device", "result": update_result}

        if snapshot.get("channels"):
            create_channels_result = self.create_channels_bulk({
                "channels": snapshot["channels"],
            }, {"device": snapshot["name"]})
            if not create_channels_result.get("success"):
                return {"success": False, "stage": "create_channels", "result": create_channels_result}

        applied_mappings = []
        for mapping in snapshot.get("mappings", []):
            if not mapping.get("variable"):
                continue
            mapping_result = self.set_mapping({
                "variable": mapping["variable"],
                "createVariable": create_variable,
            }, {"device": snapshot["name"], "channel": mapping["channel"]})
            if not mapping_result.get("success"):
                return {
                    "success": False,
                    "stage": "set_mapping",
                    "channel": mapping["channel"],
                    "result": mapping_result,
                }
            applied_mappings.append(mapping)

        return {"success": True, "recreated": snapshot["name"], "appliedMappings": applied_mappings}

    def dispatch(self, handler_name, params, groups):
        method = getattr(self, handler_name, None)
        if method is None:
            return {"success": False, "error": f"Unknown handler: {handler_name}"}
        return method(params, groups)
