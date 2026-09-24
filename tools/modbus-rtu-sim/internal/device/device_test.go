package device

import (
	"encoding/hex"
	"testing"

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
		"unsupported function": {"0b0600000001", ExceptionIllegalFunction},
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
