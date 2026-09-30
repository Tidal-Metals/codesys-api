package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"go.bug.st/serial"

	"codesys-api/tools/modbus-rtu-sim/internal/device"
)

// configVersion is the only worker configuration schema this binary accepts.
const configVersion = 1

// Config is the worker file written by modbus_simulator_control.py. Device
// entries use the same field names as the Python simulator manifest.
type Config struct {
	Version          int            `json:"version"`
	Port             string         `json:"port"`
	USBSerial        string         `json:"usbSerial"`
	Baudrate         int            `json:"baudrate"`
	Bytesize         int            `json:"bytesize"`
	Parity           string         `json:"parity"`
	Stopbits         int            `json:"stopbits"`
	IdleGapMs        int            `json:"idleGapMs"`
	StatusFile       string         `json:"statusFile"`
	StatusIntervalMs int            `json:"statusIntervalMs"`
	TraceFrames      bool           `json:"traceFrames"`
	Devices          []DeviceConfig `json:"devices"`
}

type DeviceConfig struct {
	Unit              int               `json:"unit"`
	Name              string            `json:"name"`
	HoldingMap        map[string]uint16 `json:"holdingMap"`
	InputRegistersMap map[string]uint16 `json:"inputRegistersMap"`
	CoilsMap          map[string]bit    `json:"coilsMap"`
	DiscreteInputsMap map[string]bit    `json:"discreteInputsMap"`
	Silent            bool              `json:"silent"`
}

// bit is a JSON coil/discrete value: 0, 1, false or true.
type bit bool

func (b *bit) UnmarshalJSON(data []byte) error {
	switch string(data) {
	case "0", "false":
		*b = false
	case "1", "true":
		*b = true
	default:
		return fmt.Errorf("bit value %s must be 0, 1, false or true", data)
	}
	return nil
}

func loadConfig(path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	cfg := Config{Bytesize: 8, Parity: "N", Stopbits: 1, IdleGapMs: 50, StatusIntervalMs: 1000}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return Config{}, fmt.Errorf("parse %s: %w", path, err)
	}
	if cfg.Version != configVersion {
		return Config{}, fmt.Errorf("%s: version %d unsupported (want %d)", path, cfg.Version, configVersion)
	}
	if cfg.Port == "" && cfg.USBSerial == "" {
		return Config{}, fmt.Errorf("%s: port or usbSerial is required", path)
	}
	if cfg.Baudrate <= 0 {
		return Config{}, fmt.Errorf("%s: baudrate must be positive", path)
	}
	if cfg.IdleGapMs < 1 || cfg.StatusIntervalMs < 100 {
		return Config{}, fmt.Errorf("%s: idleGapMs must be >= 1 and statusIntervalMs >= 100", path)
	}
	return cfg, nil
}

func (c Config) serialMode() (serial.Mode, error) {
	mode := serial.Mode{BaudRate: c.Baudrate, DataBits: c.Bytesize}
	switch strings.ToUpper(c.Parity) {
	case "N":
		mode.Parity = serial.NoParity
	case "E":
		mode.Parity = serial.EvenParity
	case "O":
		mode.Parity = serial.OddParity
	default:
		return mode, fmt.Errorf("parity %q must be N, E or O", c.Parity)
	}
	switch c.Stopbits {
	case 1:
		mode.StopBits = serial.OneStopBit
	case 2:
		mode.StopBits = serial.TwoStopBits
	default:
		return mode, fmt.Errorf("stopbits %d must be 1 or 2", c.Stopbits)
	}
	return mode, nil
}

func (c Config) idleGap() time.Duration {
	return time.Duration(c.IdleGapMs) * time.Millisecond
}

func (c Config) units() ([]device.Unit, error) {
	units := make([]device.Unit, 0, len(c.Devices))
	for _, d := range c.Devices {
		if d.Unit < 1 || d.Unit > 247 {
			return nil, fmt.Errorf("device %q: unit %d must be 1-247", d.Name, d.Unit)
		}
		holding, err := registerMap(d.HoldingMap)
		if err != nil {
			return nil, fmt.Errorf("device %d holdingMap: %w", d.Unit, err)
		}
		input, err := registerMap(d.InputRegistersMap)
		if err != nil {
			return nil, fmt.Errorf("device %d inputRegistersMap: %w", d.Unit, err)
		}
		coils, err := bitMap(d.CoilsMap)
		if err != nil {
			return nil, fmt.Errorf("device %d coilsMap: %w", d.Unit, err)
		}
		discrete, err := bitMap(d.DiscreteInputsMap)
		if err != nil {
			return nil, fmt.Errorf("device %d discreteInputsMap: %w", d.Unit, err)
		}
		units = append(units, device.Unit{
			ID: byte(d.Unit), Name: d.Name, Holding: holding, InputRegisters: input,
			Coils: coils, DiscreteInputs: discrete, Silent: d.Silent,
		})
	}
	return units, nil
}

// registerMap converts JSON object keys ("0", "4112") to register offsets.
func registerMap(raw map[string]uint16) (map[uint16]uint16, error) {
	out := make(map[uint16]uint16, len(raw))
	for key, value := range raw {
		offset, err := strconv.ParseUint(key, 10, 16)
		if err != nil {
			return nil, fmt.Errorf("offset %q is not 0-65535", key)
		}
		out[uint16(offset)] = value
	}
	return out, nil
}

// bitMap converts JSON object keys to coil/discrete-input offsets.
func bitMap(raw map[string]bit) (map[uint16]bool, error) {
	out := make(map[uint16]bool, len(raw))
	for key, value := range raw {
		offset, err := strconv.ParseUint(key, 10, 16)
		if err != nil {
			return nil, fmt.Errorf("offset %q is not 0-65535", key)
		}
		out[uint16(offset)] = bool(value)
	}
	return out, nil
}
