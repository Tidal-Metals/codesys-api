// Package device answers Modbus requests for a set of simulated unit IDs.
package device

import (
	"fmt"
	"slices"
	"sync"

	"codesys-api/tools/modbus-rtu-sim/internal/rtu"
)

// Modbus exception codes returned to the master.
const (
	ExceptionIllegalFunction = 0x01
	ExceptionIllegalAddress  = 0x02
	ExceptionIllegalValue    = 0x03
)

// maxReadRegisters is the FC03/FC04 quantity limit from the Modbus spec.
const maxReadRegisters = 125

// Unit is one simulated slave. Register maps are sparse and zero-based.
type Unit struct {
	ID             byte
	Name           string
	Holding        map[uint16]uint16
	InputRegisters map[uint16]uint16
	// Silent units consume their requests without replying (timeout tests).
	Silent bool
}

// Outcome describes what the bank did with a request.
type Outcome int

const (
	NotMine Outcome = iota
	Broadcast
	Silenced
	Replied
	Excepted
)

// UnitStats counts traffic for one unit ID.
type UnitStats struct {
	Name       string `json:"name"`
	Silent     bool   `json:"silent"`
	Requests   uint64 `json:"requests"`
	Replies    uint64 `json:"replies"`
	Exceptions uint64 `json:"exceptions"`
	Skipped    uint64 `json:"skipped"`
}

// Bank owns the units served on one bus.
type Bank struct {
	mu    sync.Mutex
	units map[byte]*Unit
	stats map[byte]*UnitStats
}

// NewBank validates IDs and returns a bank; duplicate or out-of-range IDs fail.
func NewBank(units []Unit) (*Bank, error) {
	bank := &Bank{units: map[byte]*Unit{}, stats: map[byte]*UnitStats{}}
	for i := range units {
		unit := units[i]
		if unit.ID < 1 || unit.ID > 247 {
			return nil, fmt.Errorf("unit %d (%q): ID must be 1-247", unit.ID, unit.Name)
		}
		if _, exists := bank.units[unit.ID]; exists {
			return nil, fmt.Errorf("unit %d (%q): duplicate ID on this bus", unit.ID, unit.Name)
		}
		bank.units[unit.ID] = &unit
		bank.stats[unit.ID] = &UnitStats{Name: unit.Name, Silent: unit.Silent}
	}
	if len(bank.units) == 0 {
		return nil, fmt.Errorf("at least one unit is required")
	}
	return bank, nil
}

// Owns reports whether id is served by this bank.
func (b *Bank) Owns(id byte) bool {
	_, ok := b.units[id]
	return ok
}

// IDs returns the served unit IDs in ascending order.
func (b *Bank) IDs() []int {
	ids := make([]int, 0, len(b.units))
	for id := range b.units {
		ids = append(ids, int(id))
	}
	slices.Sort(ids)
	return ids
}

// Handle builds the reply ADU (with CRC) for a CRC-valid request frame.
// A nil reply means stay silent.
func (b *Bank) Handle(frame []byte) ([]byte, Outcome) {
	id := frame[0]
	if id == 0 {
		return nil, Broadcast
	}
	unit, ok := b.units[id]
	if !ok {
		return nil, NotMine
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	stats := b.stats[id]
	stats.Requests++
	if unit.Silent {
		return nil, Silenced
	}
	pdu, exception := unit.respond(frame[1 : len(frame)-2])
	reply := rtu.AppendCRC(append([]byte{id}, pdu...))
	if exception {
		stats.Exceptions++
		return reply, Excepted
	}
	stats.Replies++
	return reply, Replied
}

// Skip records a request for this bank that was deliberately not answered.
func (b *Bank) Skip(id byte) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if stats, ok := b.stats[id]; ok {
		stats.Requests++
		stats.Skipped++
	}
}

// Snapshot returns a copy of per-unit counters keyed by decimal ID.
func (b *Bank) Snapshot() map[string]UnitStats {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := make(map[string]UnitStats, len(b.stats))
	for id, stats := range b.stats {
		out[fmt.Sprint(id)] = *stats
	}
	return out
}

// respond returns the reply PDU and whether it is an exception.
func (u *Unit) respond(pdu []byte) ([]byte, bool) {
	function := pdu[0]
	switch function {
	case 3:
		return readRegisters(function, u.Holding, pdu)
	case 4:
		return readRegisters(function, u.InputRegisters, pdu)
	}
	return exceptionPDU(function, ExceptionIllegalFunction), true
}

func readRegisters(function byte, registers map[uint16]uint16, pdu []byte) ([]byte, bool) {
	if len(pdu) != 5 {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	address := int(pdu[1])<<8 | int(pdu[2])
	count := int(pdu[3])<<8 | int(pdu[4])
	if count < 1 || count > maxReadRegisters {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	reply := make([]byte, 2, 2+2*count)
	reply[0], reply[1] = function, byte(2*count)
	for offset := address; offset < address+count; offset++ {
		value, ok := registers[uint16(offset)]
		if offset > 0xFFFF || !ok {
			return exceptionPDU(function, ExceptionIllegalAddress), true
		}
		reply = append(reply, byte(value>>8), byte(value))
	}
	return reply, false
}

func exceptionPDU(function, code byte) []byte {
	return []byte{function | 0x80, code}
}
