package serialrun

import (
	"encoding/hex"
	"testing"
	"time"

	"go.bug.st/serial"

	"codesys-api/tools/modbus-rtu-sim/internal/device"
)

// fakePort records writes; the embedded nil interface panics on anything else.
type fakePort struct {
	serial.Port
	writes [][]byte
}

func (p *fakePort) Write(b []byte) (int, error) {
	p.writes = append(p.writes, append([]byte(nil), b...))
	return len(b), nil
}

func newTestRunner(t *testing.T) (*Runner, *fakePort) {
	t.Helper()
	bank, err := device.NewBank([]device.Unit{{ID: 11, Holding: map[uint16]uint16{0: 1101, 1: 1102}}})
	if err != nil {
		t.Fatal(err)
	}
	port := &fakePort{}
	r := NewRunner(Options{Mode: serial.Mode{BaudRate: 115200, DataBits: 8}}, bank, &Status{})
	r.port = port
	r.framer.Idle()
	return r, port
}

func feed(t *testing.T, r *Runner, hexData string) {
	t.Helper()
	data, err := hex.DecodeString(hexData)
	if err != nil {
		t.Fatal(err)
	}
	if err := r.process(r.echo.Filter(data, time.Now()), time.Now()); err != nil {
		t.Fatal(err)
	}
}

// Replays bench traffic: foreign request/reply pairs, then our request
// coalesced behind a foreign reply, as seen on COM11 at 38,400 baud.
func TestReplayAnswersOnlyOwnUnit(t *testing.T) {
	r, port := newTestRunner(t)
	feed(t, r, "010300000002c40b")
	feed(t, r, "01030404d2162ed546")
	feed(t, r, "040304019101927f1f"+"0b0300000002c4a1")
	if len(port.writes) != 1 {
		t.Fatalf("writes = %x, want exactly one reply", port.writes)
	}
	// Expected bytes cross-checked with PyModbus FramerRTU.compute_CRC.
	if got := hex.EncodeToString(port.writes[0]); got != "0b0304044d044e43e0" {
		t.Fatalf("reply = %s", got)
	}
}

// If the master already sent more bytes after our request, replying would
// collide with that traffic.
func TestStaleRequestIsNotAnswered(t *testing.T) {
	r, port := newTestRunner(t)
	feed(t, r, "0b0300000002c4a1"+"010300000002c40b")
	if len(port.writes) != 0 {
		t.Fatalf("stale request answered: %x", port.writes)
	}
	if s := r.status.Copy(); s.Stale != 1 {
		t.Errorf("Stale = %d", s.Stale)
	}
}

func TestOwnEchoIsNotParsedAsTraffic(t *testing.T) {
	r, port := newTestRunner(t)
	feed(t, r, "0b0300000002c4a1")
	echo := hex.EncodeToString(port.writes[0])
	feed(t, r, echo+"0b0300000002c4a1")
	if len(port.writes) != 2 {
		t.Fatalf("writes after echo+request = %d, want 2", len(port.writes))
	}
	if r.echo.Echoes() != 1 {
		t.Errorf("echoes = %d", r.echo.Echoes())
	}
}

func TestSerialMatchesFTDIInterfaceSuffix(t *testing.T) {
	if !serialMatches("BG00XX03A", "BG00XX03") || !serialMatches("bg00xx03", "BG00XX03") {
		t.Error("expected match")
	}
	if serialMatches("BG00XX031A", "BG00XX03") || serialMatches("BG01GGR2A", "BG00XX03") {
		t.Error("unexpected match")
	}
}
