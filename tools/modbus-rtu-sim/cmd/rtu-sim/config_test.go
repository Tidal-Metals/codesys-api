package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestUnitsParseBitMaps(t *testing.T) {
	raw := `{"devices":[{"unit":14,"name":"io",
		"coilsMap":{"0":1,"1":0,"2":true,"3":false},
		"discreteInputsMap":{"7":1}}]}`
	var cfg Config
	if err := json.Unmarshal([]byte(raw), &cfg); err != nil {
		t.Fatal(err)
	}
	units, err := cfg.units()
	if err != nil {
		t.Fatal(err)
	}
	coils := units[0].Coils
	if len(coils) != 4 || !coils[0] || coils[1] || !coils[2] || coils[3] {
		t.Errorf("coils %v", coils)
	}
	if !units[0].DiscreteInputs[7] {
		t.Errorf("discrete inputs %v", units[0].DiscreteInputs)
	}
}

func TestBitMapsRejectBadValuesAndOffsets(t *testing.T) {
	var cfg Config
	err := json.Unmarshal([]byte(`{"devices":[{"unit":1,"coilsMap":{"0":2}}]}`), &cfg)
	if err == nil || !strings.Contains(err.Error(), "must be 0, 1, false or true") {
		t.Errorf("value 2: err %v", err)
	}
	err = json.Unmarshal([]byte(`{"devices":[{"unit":1,"coilsMap":{"0":"1"}}]}`), &cfg)
	if err == nil {
		t.Error("string value accepted")
	}
	cfg = Config{}
	if err := json.Unmarshal([]byte(`{"devices":[{"unit":1,"discreteInputsMap":{"70000":1}}]}`), &cfg); err != nil {
		t.Fatal(err)
	}
	if _, err := cfg.units(); err == nil || !strings.Contains(err.Error(), "discreteInputsMap") {
		t.Errorf("offset 70000: err %v", err)
	}
}
