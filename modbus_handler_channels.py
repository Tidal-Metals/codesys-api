"""Channel handlers for Modbus API."""

from __future__ import annotations

import os
import tempfile
import uuid

import modbus_scripts
from modbus_handler_core import _param
from modbus_native_export_generator import generate_modbus_slave_export
from modbus_script_utils import normalize_channel


class ModbusChannelMixin:
    def list_channels(self, params, groups):
        script = modbus_scripts.list_channels(groups["device"])
        return self._exec(script)

    def create_channel(self, params, groups):
        if "name" not in params:
            return {"success": False, "error": "Missing required parameter: name"}

        channel = {
            "name": params["name"],
            "accessType": _param(params, "accessType", "access_type", 3),
            "readOffset": _param(params, "readOffset", "read_offset", "16#0000"),
            "readLength": _param(params, "readLength", "read_length", 1),
            "writeOffset": _param(params, "writeOffset", "write_offset", "0"),
            "writeLength": _param(params, "writeLength", "write_length", "0"),
            "trigger": _param(params, "trigger", default=5),
            "cycleTime": _param(params, "cycleTime", "cycle_time", 100),
            "errorHandling": _param(params, "errorHandling", "error_handling", "true"),
            "comment": _param(params, "comment", default=""),
        }

        result = self.create_channels_bulk({
            "channels": [channel],
            "mode": params.get("mode", params.get("strategy", "native")),
        }, groups)
        if result.get("success"):
            result["deprecatedLegacyPath"] = True
            result["canonicalPath"] = "native device rebuild/import"
        return result

    def create_channels_bulk(self, params, groups):
        if "channels" not in params:
            return {"success": False, "error": "Missing required parameter: channels"}

        mode = str(params.get("mode", params.get("strategy", "native"))).lower()
        if mode in ("native", "export", "import_native"):
            return self._create_channels_bulk_native_merge(params, groups)

        script = modbus_scripts.create_channels_bulk(
            device_name=groups["device"],
            channels=params["channels"],
        )
        result = self._exec(script, timeout=300)
        result["deprecated"] = True
        result["deprecatedMode"] = "script"
        result["canonicalMode"] = "native"
        return result

    def safe_insert_channels(self, params, groups):
        if "channels" not in params:
            return {"success": False, "error": "Missing required parameter: channels"}

        target_device = groups["device"]
        master_path = params.get("masterPath", "Modbus_COM.Modbus_Client_COM_Port")
        application_path = params.get("applicationPath", "Device/Plc Logic/Application")
        auto_rebuild = bool(params.get("autoRebuildDownstream", True))
        create_variable = bool(params.get("createVariable", True))
        mappings = params.get("mappings", [])

        workflow = {
            "success": False,
            "targetDevice": target_device,
            "masterPath": master_path,
            "steps": [],
        }

        logout_result = self._logout_application(application_path)
        workflow["steps"].append({"step": "logout", "result": logout_result})
        if not logout_result.get("success"):
            workflow["error"] = "Failed to logout application"
            return workflow

        order_result = self._modbus_device_order()
        workflow["steps"].append({"step": "device_order", "result": order_result})
        if not order_result.get("success"):
            workflow["error"] = "Failed to enumerate Modbus device order"
            return workflow

        device_order = order_result.get("devices", [])
        if target_device not in device_order:
            workflow["error"] = "Target device not found in Modbus device order"
            return workflow

        target_index = device_order.index(target_device)
        downstream_names = device_order[target_index + 1:]
        workflow["downstreamDevices"] = downstream_names

        downstream_snapshots = []
        for downstream_name in downstream_names:
            snapshot_result = self._snapshot_device(downstream_name)
            workflow["steps"].append({
                "step": "snapshot_downstream",
                "device": downstream_name,
                "result": snapshot_result,
            })
            if not snapshot_result.get("success"):
                workflow["error"] = "Failed to snapshot downstream device"
                return workflow
            downstream_snapshots.append(snapshot_result["snapshot"])

        insert_result = self.create_channels_bulk({
            "channels": params["channels"],
        }, {"device": target_device})
        workflow["steps"].append({"step": "insert_channels", "result": insert_result})
        if not insert_result.get("success"):
            workflow["error"] = "Failed to insert channels"
            return workflow

        applied_mappings = []
        for mapping in mappings:
            if not mapping.get("variable") or not mapping.get("channel"):
                continue
            mapping_result = self.set_mapping({
                "variable": mapping["variable"],
                "createVariable": create_variable,
            }, {"device": target_device, "channel": mapping["channel"]})
            workflow["steps"].append({
                "step": "apply_mapping",
                "channel": mapping["channel"],
                "result": mapping_result,
            })
            if not mapping_result.get("success"):
                workflow["error"] = "Failed to apply mapping"
                return workflow
            applied_mappings.append(mapping)

        validation_result = self.validate_mappings({}, {})
        workflow["steps"].append({"step": "validate_after_insert", "result": validation_result})
        if validation_result.get("success"):
            workflow["success"] = True
            workflow["validation"] = validation_result
            workflow["appliedMappings"] = applied_mappings
            return workflow

        workflow["validation"] = validation_result
        if (not downstream_names) or (not auto_rebuild):
            workflow["error"] = "Validation failed after insert"
            workflow["requiresDownstreamRebuild"] = bool(downstream_names)
            return workflow

        for downstream_name in reversed(downstream_names):
            delete_result = self.delete_device({}, {"device": downstream_name})
            workflow["steps"].append({
                "step": "delete_downstream",
                "device": downstream_name,
                "result": delete_result,
            })
            if not delete_result.get("success"):
                workflow["error"] = "Failed to delete downstream device"
                return workflow

        recreated = []
        for snapshot in downstream_snapshots:
            recreate_result = self._recreate_device_from_snapshot(snapshot, master_path, create_variable=create_variable)
            workflow["steps"].append({
                "step": "recreate_downstream",
                "device": snapshot["name"],
                "result": recreate_result,
            })
            if not recreate_result.get("success"):
                workflow["error"] = "Failed to recreate downstream device"
                return workflow
            recreated.append(snapshot["name"])

        final_validation = self.validate_mappings({}, {})
        workflow["steps"].append({"step": "validate_after_rebuild", "result": final_validation})
        workflow["recreatedDownstream"] = recreated
        workflow["validation"] = final_validation
        workflow["success"] = bool(final_validation.get("success"))
        if not workflow["success"]:
            workflow["error"] = "Validation failed after downstream rebuild"
        return workflow

    def _create_channels_bulk_native(self, params, groups):
        master_path = params.get("masterPath") or params.get("master_path")
        if not master_path:
            return {"success": False, "error": "Missing required parameter for native mode: masterPath"}

        device_name = groups["device"]
        output_path = os.path.join(
            tempfile.gettempdir(),
            "codesys_modbus_{0}.export".format(uuid.uuid4()),
        )
        try:
            generated = generate_modbus_slave_export(
                device_name=device_name,
                slave_address=params.get("slaveAddress", params.get("slave_address", 1)),
                channels=params["channels"],
                output_path=output_path,
            )
        except Exception as e:
            return {"success": False, "error": "Failed to generate native export: {0}".format(str(e))}

        script = modbus_scripts.import_native_device(
            master_path=master_path,
            export_path=output_path,
            device_name=device_name,
            replace=params.get("replace", False),
        )
        result = self._exec(script, timeout=180)
        result["generatedExport"] = generated
        return result

    def _create_channels_bulk_native_merge(self, params, groups):
        device_name = groups["device"]
        snapshot_result = self._snapshot_device(device_name)
        if not snapshot_result.get("success"):
            return snapshot_result

        context_result = self._device_context(device_name)
        if not context_result.get("success"):
            return context_result

        snapshot = snapshot_result.get("snapshot", {})
        existing_channels = snapshot.get("channels", []) or []
        existing_mappings = snapshot.get("mappings", []) or []

        merged_channels = []
        merged_by_name = {}
        for channel in existing_channels:
            name = channel.get("name")
            if not name:
                continue
            merged_by_name[name] = dict(channel)
            merged_channels.append(merged_by_name[name])

        for channel in params.get("channels", []):
            normalized = normalize_channel(channel)
            name = normalized.get("name")
            if not name:
                return {"success": False, "error": "Channel name is required"}
            if name in merged_by_name:
                return {"success": False, "error": "Channel already exists: {0}".format(name)}
            merged_channels.append(normalized)
            merged_by_name[name] = normalized

        native_result = self._create_channels_bulk_native({
            "masterPath": context_result["masterPath"],
            "slaveAddress": int(context_result.get("slaveAddress") or snapshot.get("slaveAddress") or 1),
            "channels": merged_channels,
            "replace": True,
        }, groups)
        if not native_result.get("success"):
            return native_result

        reapplied = []
        for mapping in existing_mappings:
            channel_name = mapping.get("channel")
            variable = mapping.get("variable")
            if not channel_name or not variable:
                continue
            mapping_result = self.set_mapping({
                "variable": variable,
                "createVariable": False,
            }, {"device": device_name, "channel": channel_name})
            if not mapping_result.get("success"):
                return {
                    "success": False,
                    "error": "Failed to restore mapping after native rebuild",
                    "channel": channel_name,
                    "result": mapping_result,
                }
            reapplied.append({"channel": channel_name, "variable": variable})

        native_result["deprecatedLegacyPath"] = True
        native_result["canonicalMode"] = "native"
        native_result["mergedExistingChannels"] = len(existing_channels)
        native_result["addedChannels"] = len(params.get("channels", []))
        native_result["restoredMappings"] = reapplied
        return native_result

    def update_channels_bulk(self, params, groups):
        if "channels" not in params:
            return {"success": False, "error": "Missing required parameter: channels"}

        script = modbus_scripts.update_channels_bulk(
            device_name=groups["device"],
            channels=params["channels"],
        )
        return self._exec(script, timeout=120)

    def delete_channel(self, params, groups):
        script = modbus_scripts.delete_channel(groups["device"], groups["channel"])
        return self._exec(script)

    def update_channel(self, params, groups):
        kwargs = {}
        for key, alias in (
            ("accessType", "access_type"),
            ("readOffset", "read_offset"),
            ("readLength", "read_length"),
            ("writeOffset", "write_offset"),
            ("writeLength", "write_length"),
            ("trigger", None),
            ("cycleTime", "cycle_time"),
            ("errorHandling", "error_handling"),
            ("comment", None),
        ):
            if key in params or (alias and alias in params):
                kwargs[key] = _param(params, key, alias)

        if not kwargs:
            return {"success": False, "error": "No fields to update"}

        script = modbus_scripts.update_channel(
            device_name=groups["device"],
            channel_name=groups["channel"],
            **kwargs,
        )
        return self._exec(script)
