package serialrun

import (
	"encoding/json"
	"os"
	"sync"
	"time"

	"codesys-api/tools/modbus-rtu-sim/internal/device"
	"codesys-api/tools/modbus-rtu-sim/internal/rtu"
)

// Snapshot is the worker state published to the status file.
type Snapshot struct {
	Version       int       `json:"version"`
	PID           int       `json:"pid"`
	StartedAt     time.Time `json:"startedAt"`
	HeartbeatAt   time.Time `json:"heartbeatAt"`
	ConfiguredCOM string    `json:"configuredPort"`
	USBSerial     string    `json:"usbSerial,omitempty"`
	ActivePort    string    `json:"activePort,omitempty"`
	PortOpen      bool      `json:"portOpen"`
	OpenedAt      time.Time `json:"openedAt,omitzero"`
	LastError     string    `json:"lastError,omitempty"`
	LastErrorAt   time.Time `json:"lastErrorAt,omitzero"`
	OpenCount     uint64    `json:"openCount"`
	ReopenCount   uint64    `json:"reopenCount"`
	LastRxAt      time.Time `json:"lastRxAt,omitzero"`
	LastTxAt      time.Time `json:"lastTxAt,omitzero"`
	RxBytes       uint64    `json:"rxBytes"`
	TxBytes       uint64    `json:"txBytes"`
	Echoes        uint64    `json:"echoes"`
	Stale         uint64    `json:"staleRequests"`
	Ineligible    uint64    `json:"ineligibleRequests"`
	WriteErrors   uint64    `json:"writeErrors"`
	// ReplyLatencyUs is host-side time from the read completing a request to
	// the reply write returning; it excludes USB and wire time.
	LastReplyLatencyUs int64                       `json:"lastReplyLatencyUs"`
	MaxReplyLatencyUs  int64                       `json:"maxReplyLatencyUs"`
	Framer             rtu.Stats                   `json:"framer"`
	Units              map[string]device.UnitStats `json:"units"`
}

// Status is the mutex-guarded live snapshot shared by the bus loop and writer.
type Status struct {
	mu   sync.Mutex
	snap Snapshot
}

// Update applies fn to the snapshot under the lock.
func (s *Status) Update(fn func(*Snapshot)) {
	s.mu.Lock()
	defer s.mu.Unlock()
	fn(&s.snap)
}

// Copy returns a copy of the current snapshot.
func (s *Status) Copy() Snapshot {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.snap
}

// WriteFile atomically replaces path with the snapshot as JSON. Readers on
// Windows may briefly hold the file, so the rename is retried.
func WriteFile(path string, snap Snapshot) error {
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	for attempt := 0; ; attempt++ {
		err = os.Rename(tmp, path)
		if err == nil || attempt == 5 {
			return err
		}
		time.Sleep(20 * time.Millisecond)
	}
}
