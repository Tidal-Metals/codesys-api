"""Device, status, topology, and simulator handlers for Modbus API."""

from __future__ import annotations

import time

import modbus_scripts
import modbus_simulator_control


class ModbusDeviceStatusMixin:
    def list_devices(self, params, groups):
        script = modbus_scripts.list_device_tree()
        return self._exec(script)

    def get_device(self, params, groups):
        script = modbus_scripts.get_device(groups["device"])
        return self._exec(script)

    def create_device(self, params, groups):
        required = ["masterPath", "name"]
        for key in required:
            if key not in params:
                return {"success": False, "error": f"Missing required parameter: {key}"}

        script = modbus_scripts.create_device(
            master_path=params["masterPath"],
            device_name=params["name"],
            slave_address=params.get("slaveAddress", 1),
            device_type=params.get("deviceType", 91),
            device_id=params.get("deviceId", "0000 0001"),
            device_version=params.get("deviceVersion", "4.5.0.0"),
        )
        return self._exec(script, timeout=180)

    def delete_device(self, params, groups):
        script = modbus_scripts.delete_device(groups["device"])
        return self._exec(script)

    def update_device(self, params, groups):
        script = modbus_scripts.update_device(
            device_name=groups["device"],
            slave_address=params.get("slaveAddress"),
            response_timeout=params.get("responseTimeout"),
            always_update_variables=params.get("alwaysUpdateVariables"),
        )
        return self._exec(script)

    def acknowledge_device(self, params, groups):
        script = modbus_scripts.acknowledge_device(device_name=groups["device"], subtree=False)
        return self._exec(script, timeout=120)

    def acknowledge_device_subtree(self, params, groups):
        script = modbus_scripts.acknowledge_device(device_name=groups["device"], subtree=True)
        return self._exec(script, timeout=120)

    def get_device_status(self, params, groups):
        application_path = params.get("applicationPath", "Device/Plc Logic/Application")
        script = modbus_scripts.get_device_status(
            device_name=groups["device"],
            application_path=application_path,
        )
        return self._exec(script, timeout=120)

    def get_status_map(self, params, groups):
        master_name = params.get("master", params.get("masterName"))
        if master_name:
            script = modbus_scripts.get_status_map(master_name=master_name)
            return self._exec(script, timeout=60)

        master_names = self._modbus_master_names()
        if not master_names.get("success"):
            return master_names

        maps = []
        combined_devices = []
        for name in master_names.get("masters", []):
            script = modbus_scripts.get_status_map(master_name=name)
            result = self._exec(script, timeout=60)
            maps.append(result)
            if not result.get("success"):
                return result
            for device in result.get("devices", []):
                entry = dict(device)
                entry["master"] = name
                combined_devices.append(entry)

        return {
            "success": True,
            "masters": master_names.get("masters", []),
            "devices": combined_devices,
            "maps": maps,
        }

    def get_topology(self, params, groups):
        tree = self.list_devices({}, {})
        if not tree.get("success"):
            return tree

        buses = []
        for plc in tree.get("devices", []):
            for child in plc.get("children", []):
                if child.get("device_type") != 92:
                    continue

                com_name = child.get("name")
                com_result = self.get_com({}, {"device": com_name})
                if not com_result.get("success"):
                    return com_result

                bus_entry = {
                    "comDevice": com_name,
                    "deviceType": child.get("device_type"),
                    "deviceId": child.get("device_id"),
                    "deviceVersion": child.get("device_version"),
                    "serial": com_result.get("params", {}),
                    "masters": [],
                }

                for master in child.get("children", []):
                    if master.get("device_type") != 90:
                        continue
                    master_name = master.get("name")
                    master_entry = {
                        "name": master_name,
                        "deviceType": master.get("device_type"),
                        "deviceId": master.get("device_id"),
                        "deviceVersion": master.get("device_version"),
                        "path": f"{com_name}.{master_name}",
                        "devices": [],
                    }
                    for device in master.get("children", []):
                        if device.get("device_type") != 91:
                            continue
                        params_map = device.get("params", {}) or {}
                        master_entry["devices"].append({
                            "name": device.get("name"),
                            "deviceType": device.get("device_type"),
                            "deviceId": device.get("device_id"),
                            "deviceVersion": device.get("device_version"),
                            "slaveAddress": params_map.get("slaveAddress"),
                            "responseTimeout": params_map.get("responseTimeout"),
                        })
                    bus_entry["masters"].append(master_entry)
                buses.append(bus_entry)

        def _sort_key(_bus):
            serial = _bus.get("serial", {}) or {}
            port_text = str(serial.get("ComPort", "")).strip()
            try:
                port_num = int(port_text)
            except Exception:
                port_num = 9999
            return (port_num, str(_bus.get("comDevice", "")))

        buses = sorted(buses, key=_sort_key)
        by_port = {}
        for bus in buses:
            port_text = str((bus.get("serial", {}) or {}).get("ComPort", "")).strip()
            if port_text:
                by_port[f"COM{port_text}"] = bus

        return {
            "success": True,
            "buses": buses,
            "byPort": by_port,
        }

    def get_simulator_status(self, params, groups):
        return modbus_simulator_control.get_simulator_status()

    def apply_simulator(self, params, groups):
        buses = params.get("buses")
        if not isinstance(buses, list) or not buses:
            return {"success": False, "error": "Payload must contain a non-empty buses array"}
        return modbus_simulator_control.apply_simulator(buses)

    def get_bus_status(self, params, groups):
        application_path = params.get("applicationPath", "Device/Plc Logic/Application")
        master_name = params.get("master", params.get("masterName"))
        sample_seconds = float(params.get("sampleSeconds", 2.0))
        if sample_seconds < 0:
            sample_seconds = 0.0

        status_map = self.get_status_map({"master": master_name} if master_name else {}, {})
        if not status_map.get("success"):
            return status_map

        devices = []
        stalled_devices = []
        non_polling_devices = []
        failed_devices = []
        all_healthy = True

        initial_devices = []
        for entry in status_map.get("devices", []):
            device_name = entry.get("name")
            device_status = self.get_device_status({"applicationPath": application_path}, {"device": device_name})
            combined = dict(entry)
            combined["status"] = device_status
            initial_devices.append(combined)

            if not device_status.get("success"):
                failed_devices.append(device_name)
                all_healthy = False
                continue

            derived = device_status.get("derived", {})
            if bool(derived.get("stalled")):
                stalled_devices.append(device_name)
                all_healthy = False

        if sample_seconds > 0:
            time.sleep(sample_seconds)

        for combined in initial_devices:
            device_name = combined.get("name")
            initial_status = combined.get("status", {})
            initial_request = (
                ((initial_status.get("serverDiag", {}) or {}).get("requestCounter", {}) or {}).get("valueHigh16")
            )
            polling = None
            counter_delta = None

            if initial_status.get("success"):
                sampled_status = self.get_device_status({"applicationPath": application_path}, {"device": device_name})
                combined["statusSampled"] = sampled_status
                if sampled_status.get("success"):
                    sampled_request = (
                        ((sampled_status.get("serverDiag", {}) or {}).get("requestCounter", {}) or {}).get("valueHigh16")
                    )
                    if isinstance(initial_request, int) and isinstance(sampled_request, int):
                        counter_delta = sampled_request - initial_request
                        polling = counter_delta > 0
                        combined["polling"] = {
                            "sampleSeconds": sample_seconds,
                            "requestCounterStart": initial_request,
                            "requestCounterEnd": sampled_request,
                            "requestCounterDelta": counter_delta,
                            "moving": polling,
                        }
                        derived = dict((sampled_status.get("derived", {}) or {}))
                        derived["requestCounterMoving"] = polling
                        if polling:
                            derived["pollingStatus"] = "moving"
                        else:
                            derived["pollingStatus"] = "stopped"
                        if not derived.get("stalled") and polling is False:
                            derived["healthy"] = False
                            derived["status"] = "non_polling"
                        sampled_status["derived"] = derived
                        combined["status"] = sampled_status
                    else:
                        combined["polling"] = {
                            "sampleSeconds": sample_seconds,
                            "requestCounterStart": initial_request,
                            "requestCounterEnd": sampled_request,
                            "requestCounterDelta": None,
                            "moving": None,
                        }
                else:
                    combined["status"] = sampled_status
                    failed_devices.append(device_name)
                    all_healthy = False

            if combined.get("status", {}).get("success"):
                derived = combined["status"].get("derived", {})
                if bool(derived.get("stalled")):
                    if device_name not in stalled_devices:
                        stalled_devices.append(device_name)
                    all_healthy = False
                elif derived.get("requestCounterMoving") is False:
                    non_polling_devices.append(device_name)
                    all_healthy = False

            devices.append(combined)

        return {
            "success": True,
            "master": master_name,
            "masters": status_map.get("masters") if not master_name else [master_name],
            "applicationPath": application_path,
            "sampleSeconds": sample_seconds,
            "allHealthy": all_healthy and not failed_devices,
            "stalledDevices": stalled_devices,
            "nonPollingDevices": non_polling_devices,
            "failedDevices": failed_devices,
            "devices": devices,
        }

    def acknowledge_stalled(self, params, groups):
        application_path = params.get("applicationPath", "Device/Plc Logic/Application")
        master_name = params.get("master", params.get("masterName"))
        subtree = bool(params.get("subtree", False))

        before = self.get_bus_status(
            {"applicationPath": application_path, "master": master_name} if master_name else {"applicationPath": application_path},
            {},
        )
        if not before.get("success"):
            return before

        acknowledged = []
        failed = []

        for device_name in before.get("stalledDevices", []):
            if subtree:
                ack_result = self.acknowledge_device_subtree({}, {"device": device_name})
            else:
                ack_result = self.acknowledge_device({}, {"device": device_name})
            entry = {"device": device_name, "result": ack_result}
            acknowledged.append(entry)
            if not ack_result.get("success"):
                failed.append(entry)

        after = self.get_bus_status(
            {"applicationPath": application_path, "master": master_name} if master_name else {"applicationPath": application_path},
            {},
        )

        return {
            "success": bool(after.get("success")) and len(failed) == 0,
            "applicationPath": application_path,
            "master": master_name,
            "subtree": subtree,
            "before": before,
            "acknowledged": acknowledged,
            "after": after,
            "stalledBefore": before.get("stalledDevices", []),
            "stalledAfter": after.get("stalledDevices", []) if after.get("success") else None,
            "failedAcknowledge": failed,
        }
