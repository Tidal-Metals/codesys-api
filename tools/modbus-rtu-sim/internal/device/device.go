// Package device answers Modbus requests for a set of simulated unit IDs.
package device

import (
	"fmt"
	"slices"
	"strconv"
	"sync"
	"time"

	"codesys-api/tools/modbus-rtu-sim/internal/rtu"
)

// Modbus exception codes returned to the master.
const (
	ExceptionIllegalFunction = 0x01
	ExceptionIllegalAddress  = 0x02
	ExceptionIllegalValue    = 0x03
)

// Quantity limits from the Modbus spec.
const (
	maxReadRegisters  = 125  // FC03/FC04
	maxReadBits       = 2000 // FC01/FC02
	maxWriteRegisters = 123  // FC16
	maxWriteCoils     = 1968 // FC15
)

// Unit is one simulated slave. Register and bit maps are sparse and zero-based.
// Writes (FC05/06/15/16) mutate Coils and Holding under the Bank mutex.
type Unit struct {
	ID             byte
	Name           string
	Holding        map[uint16]uint16
	InputRegisters map[uint16]uint16
	Coils          map[uint16]bool
	DiscreteInputs map[uint16]bool
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
	// Writes counts accepted write requests (FC05/06/15/16).
	Writes uint64 `json:"writes"`
	// LastWrite is nil until the first accepted write.
	LastWrite *WriteRecord `json:"lastWrite"`
	// Coils is a copy of the current coil values (offset -> 0/1), omitted when the unit has none.
	Coils map[string]int `json:"coils,omitempty"`
}

// WriteRecord describes the most recent accepted write. Coil values are 0/1.
// It is never modified after creation, so snapshots may share the pointer.
type WriteRecord struct {
	Function byte   `json:"function"`
	Start    uint16 `json:"start"`
	Values   []int  `json:"values"`
	Time     string `json:"time"`
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
	pdu, exception := unit.respond(frame[1:len(frame)-2], stats)
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

// Snapshot returns a copy of per-unit counters and coil values keyed by decimal ID.
func (b *Bank) Snapshot() map[string]UnitStats {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := make(map[string]UnitStats, len(b.stats))
	for id, stats := range b.stats {
		snap := *stats
		if coils := b.units[id].Coils; len(coils) > 0 {
			snap.Coils = make(map[string]int, len(coils))
			for offset, on := range coils {
				snap.Coils[strconv.Itoa(int(offset))] = bitValue(on)
			}
		}
		out[fmt.Sprint(id)] = snap
	}
	return out
}

// respond returns the reply PDU and whether it is an exception. Accepted
// writes are recorded on stats.
func (u *Unit) respond(pdu []byte, stats *UnitStats) ([]byte, bool) {
	function := pdu[0]
	switch function {
	case 1:
		return readBits(function, u.Coils, pdu)
	case 2:
		return readBits(function, u.DiscreteInputs, pdu)
	case 3:
		return readRegisters(function, u.Holding, pdu)
	case 4:
		return readRegisters(function, u.InputRegisters, pdu)
	case 5:
		return u.writeSingleCoil(pdu, stats)
	case 6:
		return u.writeSingleRegister(pdu, stats)
	case 15:
		return u.writeCoils(pdu, stats)
	case 16:
		return u.writeRegisters(pdu, stats)
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

// readBits answers FC01/FC02. Bits pack LSB-first; unused high bits stay zero.
func readBits(function byte, bits map[uint16]bool, pdu []byte) ([]byte, bool) {
	if len(pdu) != 5 {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	address := int(pdu[1])<<8 | int(pdu[2])
	count := int(pdu[3])<<8 | int(pdu[4])
	if count < 1 || count > maxReadBits {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	if !allBitsExist(bits, address, count) {
		return exceptionPDU(function, ExceptionIllegalAddress), true
	}
	byteCount := (count + 7) / 8
	reply := make([]byte, 2+byteCount)
	reply[0], reply[1] = function, byte(byteCount)
	for i := 0; i < count; i++ {
		if bits[uint16(address+i)] {
			reply[2+i/8] |= 1 << (i % 8)
		}
	}
	return reply, false
}

func (u *Unit) writeSingleCoil(pdu []byte, stats *UnitStats) ([]byte, bool) {
	const function = 5
	if len(pdu) != 5 {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	address := uint16(pdu[1])<<8 | uint16(pdu[2])
	raw := uint16(pdu[3])<<8 | uint16(pdu[4])
	if raw != 0xFF00 && raw != 0x0000 {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	if _, ok := u.Coils[address]; !ok {
		return exceptionPDU(function, ExceptionIllegalAddress), true
	}
	on := raw == 0xFF00
	u.Coils[address] = on
	stats.recordWrite(function, address, []int{bitValue(on)})
	return slices.Clone(pdu), false
}

func (u *Unit) writeSingleRegister(pdu []byte, stats *UnitStats) ([]byte, bool) {
	const function = 6
	if len(pdu) != 5 {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	address := uint16(pdu[1])<<8 | uint16(pdu[2])
	value := uint16(pdu[3])<<8 | uint16(pdu[4])
	if _, ok := u.Holding[address]; !ok {
		return exceptionPDU(function, ExceptionIllegalAddress), true
	}
	u.Holding[address] = value
	stats.recordWrite(function, address, []int{int(value)})
	return slices.Clone(pdu), false
}

func (u *Unit) writeCoils(pdu []byte, stats *UnitStats) ([]byte, bool) {
	const function = 15
	if len(pdu) < 6 {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	address := int(pdu[1])<<8 | int(pdu[2])
	count := int(pdu[3])<<8 | int(pdu[4])
	byteCount := int(pdu[5])
	if count < 1 || count > maxWriteCoils || byteCount != (count+7)/8 || len(pdu) != 6+byteCount {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	if !allBitsExist(u.Coils, address, count) {
		return exceptionPDU(function, ExceptionIllegalAddress), true
	}
	values := make([]int, count)
	for i := range values {
		values[i] = int(pdu[6+i/8]>>(i%8)) & 1
		u.Coils[uint16(address+i)] = values[i] == 1
	}
	stats.recordWrite(function, uint16(address), values)
	return slices.Clone(pdu[:5]), false
}

func (u *Unit) writeRegisters(pdu []byte, stats *UnitStats) ([]byte, bool) {
	const function = 16
	if len(pdu) < 6 {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	address := int(pdu[1])<<8 | int(pdu[2])
	count := int(pdu[3])<<8 | int(pdu[4])
	byteCount := int(pdu[5])
	if count < 1 || count > maxWriteRegisters || byteCount != 2*count || len(pdu) != 6+byteCount {
		return exceptionPDU(function, ExceptionIllegalValue), true
	}
	for offset := address; offset < address+count; offset++ {
		if _, ok := u.Holding[uint16(offset)]; offset > 0xFFFF || !ok {
			return exceptionPDU(function, ExceptionIllegalAddress), true
		}
	}
	values := make([]int, count)
	for i := range values {
		value := uint16(pdu[6+2*i])<<8 | uint16(pdu[7+2*i])
		values[i] = int(value)
		u.Holding[uint16(address+i)] = value
	}
	stats.recordWrite(function, uint16(address), values)
	return slices.Clone(pdu[:5]), false
}

// allBitsExist reports whether every address in [start, start+count) is in bits.
func allBitsExist(bits map[uint16]bool, start, count int) bool {
	if start+count > 0x10000 {
		return false
	}
	for offset := start; offset < start+count; offset++ {
		if _, ok := bits[uint16(offset)]; !ok {
			return false
		}
	}
	return true
}

func (s *UnitStats) recordWrite(function byte, start uint16, values []int) {
	s.Writes++
	s.LastWrite = &WriteRecord{
		Function: function, Start: start, Values: values,
		Time: time.Now().Format(time.RFC3339Nano),
	}
}

func bitValue(on bool) int {
	if on {
		return 1
	}
	return 0
}

func exceptionPDU(function, code byte) []byte {
	return []byte{function | 0x80, code}
}
