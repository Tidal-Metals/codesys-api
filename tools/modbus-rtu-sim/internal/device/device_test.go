package device

import (
	"bytes"
	"encoding/hex"
	"slices"
	"strings"
	"testing"
	"time"

	"codesys-api/tools/modbus-rtu-sim/internal/rtu"
)

func request(t *testing.T, payload string) []byte {
	t.Helper()
	raw, err := hex.DecodeString(payload)
	if err != nil {
		t.Fatal(err)
	}
	return rtu.AppendCRC(raw)
}

func bench(t *testing.T) *Bank {
	t.Helper()
	bank, err := NewBank([]Unit{
		{ID: 11, Name: "Unit11", Holding: map[uint16]uint16{0: 1101, 1: 1102}, InputRegisters: map[uint16]uint16{0: 1234}},
		{ID: 12, Name: "Quiet", Holding: map[uint16]uint16{0: 1}, Silent: true},
	})
	if err != nil {
		t.Fatal(err)
	}
	return bank
}

func TestReadHoldingRegisters(t *testing.T) {
	reply, outcome := bench(t).Handle(request(t, "0b0300000002"))
	want := hex.EncodeToString(rtu.AppendCRC([]byte{11, 3, 4, 0x04, 0x4d, 0x04, 0x4e}))
	if outcome != Replied || hex.EncodeToString(reply) != want {
		t.Fatalf("reply %x outcome %v, want %s", reply, outcome, want)
	}
}

func TestExceptions(t *testing.T) {
	cases := map[string]struct {
		payload string
		code    byte
	}{
		"missing register":     {"0b0300010002", ExceptionIllegalAddress},
		"zero quantity":        {"0b0300000000", ExceptionIllegalValue},
		"quantity over 125":    {"0b030000007e", ExceptionIllegalValue},
		"unsupported function": {"0b0700000001", ExceptionIllegalFunction},
		"input past end":       {"0b0400000002", ExceptionIllegalAddress},
	}
	for name, c := range cases {
		reply, outcome := bench(t).Handle(request(t, c.payload))
		if outcome != Excepted || len(reply) != 5 || reply[1]&0x80 == 0 || reply[2] != c.code {
			t.Errorf("%s: reply %x outcome %v", name, reply, outcome)
		}
	}
}

func TestSilenceForOthersBroadcastAndSilentUnits(t *testing.T) {
	bank := bench(t)
	for payload, want := range map[string]Outcome{
		"010300000002": NotMine,
		"000300000002": Broadcast,
		"0c0300000001": Silenced,
	} {
		if reply, outcome := bank.Handle(request(t, payload)); reply != nil || outcome != want {
			t.Errorf("%s: reply %x outcome %v, want silence/%v", payload, reply, outcome, want)
		}
	}
	if stats := bank.Snapshot()["12"]; stats.Requests != 1 || stats.Replies != 0 {
		t.Errorf("silent unit stats %+v", stats)
	}
}

func TestNewBankRejectsBadIDs(t *testing.T) {
	if _, err := NewBank([]Unit{{ID: 5}, {ID: 5}}); err == nil {
		t.Error("duplicate IDs accepted")
	}
	if _, err := NewBank([]Unit{{ID: 0}}); err == nil {
		t.Error("ID 0 accepted")
	}
	if _, err := NewBank(nil); err == nil {
		t.Error("empty bank accepted")
	}
}

// coilPattern is coils 0-9 = 1,0,1,1,0,0,1,0,1,1, which packs to bytes 4d 03.
var coilPattern = []bool{true, false, true, true, false, false, true, false, true, true}

// bitsBench serves unit 13 with the coil pattern, inverted discrete inputs and
// holding registers 0-2 = 10, 11, 12.
func bitsBench(t *testing.T) *Bank {
	t.Helper()
	coils := map[uint16]bool{}
	discrete := map[uint16]bool{}
	for i, on := range coilPattern {
		coils[uint16(i)] = on
		discrete[uint16(i)] = !on
	}
	bank, err := NewBank([]Unit{{
		ID: 13, Name: "Bits", Coils: coils, DiscreteInputs: discrete,
		Holding: map[uint16]uint16{0: 10, 1: 11, 2: 12},
	}})
	if err != nil {
		t.Fatal(err)
	}
	return bank
}

// call sends payload (hex, no CRC) and returns the reply as hex without its
// CRC, after checking the outcome and the reply CRC.
func call(t *testing.T, bank *Bank, payload string, want Outcome) string {
	t.Helper()
	reply, outcome := bank.Handle(request(t, payload))
	if outcome != want {
		t.Fatalf("%s: outcome %v, want %v (reply %x)", payload, outcome, want, reply)
	}
	if reply == nil {
		return ""
	}
	body := reply[:len(reply)-2]
	if !bytes.Equal(reply, rtu.AppendCRC(body)) {
		t.Fatalf("%s: reply %x has a bad CRC", payload, reply)
	}
	return hex.EncodeToString(body)
}

func TestReadCoilsPacksLSBFirst(t *testing.T) {
	bank := bitsBench(t)
	cases := map[string]string{
		"0d0100000001": "0d010101",   // n=1
		"0d0100000008": "0d01014d",   // n=8, one full byte
		"0d010000000a": "0d01024d03", // n=10, crosses a byte boundary
		"0d0100060004": "0d01010d",   // start 6, n=4: 1,0,1,1
	}
	for payload, want := range cases {
		if got := call(t, bank, payload, Replied); got != want {
			t.Errorf("%s: got %s, want %s", payload, got, want)
		}
	}
	reply, _ := bank.Handle(request(t, "0d010000000a"))
	if want := hex.EncodeToString(rtu.AppendCRC([]byte{13, 1, 2, 0x4d, 0x03})); hex.EncodeToString(reply) != want {
		t.Errorf("reply %x, want %s", reply, want)
	}
}

func TestReadDiscreteInputs(t *testing.T) {
	// Discrete inputs are the inverse of the coil pattern: b2 00 for n=10.
	if got := call(t, bitsBench(t), "0d020000000a", Replied); got != "0d0202b200" {
		t.Errorf("got %s, want 0d0202b200", got)
	}
}

func TestReadBitsExceptions(t *testing.T) {
	bank := bitsBench(t)
	cases := map[string][2]string{
		"zero quantity":  {"0d0100000000", "0d8103"},
		"over 2000":      {"0d01000007d1", "0d8103"},
		"past end":       {"0d010000000b", "0d8102"},
		"start past end": {"0d0100640001", "0d8102"},
		"fc2 past end":   {"0d020005000a", "0d8202"},
		"short pdu":      {"0d010000", "0d8103"},
	}
	for name, c := range cases {
		if got := call(t, bank, c[0], Excepted); got != c[1] {
			t.Errorf("%s: got %s, want %s", name, got, c[1])
		}
	}
}

func TestWriteSingleCoil(t *testing.T) {
	bank := bitsBench(t)
	if got := call(t, bank, "0d050001ff00", Replied); got != "0d050001ff00" {
		t.Errorf("on echo %s", got)
	}
	if got := call(t, bank, "0d0500000000", Replied); got != "0d0500000000" {
		t.Errorf("off echo %s", got)
	}
	// Coils 0-7 are now 0,1,1,1,0,0,1,0 -> 0x4e.
	if got := call(t, bank, "0d0100000008", Replied); got != "0d01014e" {
		t.Errorf("read back %s", got)
	}
	if got := call(t, bank, "0d0500011234", Excepted); got != "0d8503" {
		t.Errorf("bad value %s", got)
	}
	if got := call(t, bank, "0d050064ff00", Excepted); got != "0d8502" {
		t.Errorf("missing address %s", got)
	}
	stats := bank.Snapshot()["13"]
	last := stats.LastWrite
	if stats.Writes != 2 || last == nil || last.Function != 5 || last.Start != 0 || !slices.Equal(last.Values, []int{0}) {
		t.Errorf("writes %d last %+v", stats.Writes, last)
	}
}

func TestWriteMultipleCoilsThenRead(t *testing.T) {
	bank := bitsBench(t)
	// Coils 0-9 = 0,1,0,0,1,1,0,1,0,0 -> bytes b2 00.
	if got := call(t, bank, "0d0f0000000a02b200", Replied); got != "0d0f0000000a" {
		t.Fatalf("reply %s", got)
	}
	if got := call(t, bank, "0d010000000a", Replied); got != "0d0102b200" {
		t.Errorf("read back %s", got)
	}
	stats := bank.Snapshot()["13"]
	last := stats.LastWrite
	if stats.Writes != 1 || last == nil || last.Function != 15 || last.Start != 0 ||
		!slices.Equal(last.Values, []int{0, 1, 0, 0, 1, 1, 0, 1, 0, 0}) {
		t.Fatalf("writes %d last %+v", stats.Writes, last)
	}
	if _, err := time.Parse(time.RFC3339Nano, last.Time); err != nil {
		t.Errorf("time %q: %v", last.Time, err)
	}
	if len(stats.Coils) != 10 || stats.Coils["1"] != 1 || stats.Coils["0"] != 0 {
		t.Errorf("snapshot coils %v", stats.Coils)
	}
}

func TestWriteMultipleCoilsRejections(t *testing.T) {
	bank := bitsBench(t)
	cases := map[string][2]string{
		"byte count mismatch": {"0d0f0000000a01ff", "0d8f03"},
		"pdu length mismatch": {"0d0f0000000a02ffffff", "0d8f03"},
		"zero quantity":       {"0d0f000000000100", "0d8f03"},
		"quantity over 1968":  {"0d0f000007b1f7" + strings.Repeat("00", 247), "0d8f03"},
		"one missing address": {"0d0f00050006" + "01ff", "0d8f02"}, // coils 5-10; 10 is missing
	}
	for name, c := range cases {
		if got := call(t, bank, c[0], Excepted); got != c[1] {
			t.Errorf("%s: got %s, want %s", name, got, c[1])
		}
	}
	if got := call(t, bank, "0d010000000a", Replied); got != "0d01024d03" {
		t.Errorf("coils changed: %s", got)
	}
	if stats := bank.Snapshot()["13"]; stats.Writes != 0 || stats.LastWrite != nil {
		t.Errorf("rejected writes recorded: %+v", stats)
	}
}

func TestWriteRegistersThenRead(t *testing.T) {
	bank := bitsBench(t)
	if got := call(t, bank, "0d0600010abc", Replied); got != "0d0600010abc" {
		t.Errorf("fc6 echo %s", got)
	}
	if got := call(t, bank, "0d0300010001", Replied); got != "0d03020abc" {
		t.Errorf("fc6 read back %s", got)
	}
	if got := call(t, bank, "0d10000100020400630064", Replied); got != "0d1000010002" {
		t.Errorf("fc16 reply %s", got)
	}
	if got := call(t, bank, "0d0300000003", Replied); got != "0d0306000a00630064" {
		t.Errorf("fc16 read back %s", got)
	}
	stats := bank.Snapshot()["13"]
	last := stats.LastWrite
	if stats.Writes != 2 || last == nil || last.Function != 16 || last.Start != 1 || !slices.Equal(last.Values, []int{99, 100}) {
		t.Errorf("writes %d last %+v", stats.Writes, last)
	}
}

func TestWriteRegistersRejections(t *testing.T) {
	bank := bitsBench(t)
	cases := map[string][2]string{
		"fc6 missing address":    {"0d0600640001", "0d8602"},
		"fc16 quantity 124":      {"0d10" + "0000" + "007c" + "f8" + strings.Repeat("00", 248), "0d9003"},
		"fc16 byte count wrong":  {"0d100000000202" + "00010002", "0d9003"},
		"fc16 pdu length wrong":  {"0d100000000204" + "00010002ff", "0d9003"},
		"fc16 zero quantity":     {"0d100000000000", "0d9003"},
		"fc16 one missing":       {"0d100002000204" + "00010002", "0d9002"}, // registers 2-3; 3 is missing
		"fc16 start past 0xFFFF": {"0d10ffff000204" + "00010002", "0d9002"},
	}
	for name, c := range cases {
		if got := call(t, bank, c[0], Excepted); got != c[1] {
			t.Errorf("%s: got %s, want %s", name, got, c[1])
		}
	}
	if got := call(t, bank, "0d0300000003", Replied); got != "0d0306000a000b000c" {
		t.Errorf("holding changed: %s", got)
	}
	if stats := bank.Snapshot()["13"]; stats.Writes != 0 || stats.LastWrite != nil {
		t.Errorf("rejected writes recorded: %+v", stats)
	}
}

func TestBroadcastWriteIsIgnored(t *testing.T) {
	bank := bitsBench(t)
	call(t, bank, "00050000ff00", Broadcast)
	if got := call(t, bank, "0d0100000001", Replied); got != "0d010101" {
		t.Errorf("broadcast changed coils: %s", got)
	}
}
