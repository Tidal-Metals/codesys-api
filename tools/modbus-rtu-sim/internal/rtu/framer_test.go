package rtu

import (
	"bytes"
	"encoding/hex"
	"testing"
	"time"
)

// Captured on the bench at 38,400 baud (COM11 listening to units 1-10).
const (
	reqUnit1   = "010300000002c40b"
	replyUnit1 = "01030404d2162ed546"
	reqUnit9   = "090300000002c543"
	replyUnit4 = "040304019101927f1f"
)

func mustHex(t *testing.T, s string) []byte {
	t.Helper()
	clean := bytes.ReplaceAll([]byte(s), []byte(" "), nil)
	out, err := hex.DecodeString(string(clean))
	if err != nil {
		t.Fatalf("bad hex %q: %v", s, err)
	}
	return out
}

// synced returns a framer that has seen line silence, as after startup.
func synced() *Framer {
	f := NewFramer()
	f.Idle()
	return f
}

func TestCRCMatchesCapturedFrames(t *testing.T) {
	for _, frame := range []string{reqUnit1, replyUnit1, reqUnit9, replyUnit4} {
		if !hasValidCRC(mustHex(t, frame)) {
			t.Errorf("captured frame %s failed CRC", frame)
		}
	}
	// Expected value cross-checked with PyModbus FramerRTU.compute_CRC.
	built := AppendCRC(mustHex(t, "0b0300000002"))
	if hex.EncodeToString(built) != "0b0300000002c4a1" {
		t.Errorf("AppendCRC = %x", built)
	}
}

func TestRequestThenForeignReplyClassified(t *testing.T) {
	f := synced()
	frames := f.Feed(mustHex(t, reqUnit1+replyUnit1))
	if len(frames) != 2 {
		t.Fatalf("got %d frames, want 2", len(frames))
	}
	if frames[0].Kind != KindRequest || frames[1].Kind != KindResponse {
		t.Errorf("kinds = %v, %v", frames[0].Kind, frames[1].Kind)
	}
	if !frames[0].FollowedByData || frames[1].FollowedByData {
		t.Errorf("FollowedByData = %v, %v", frames[0].FollowedByData, frames[1].FollowedByData)
	}
}

// A foreign reply coalesced with the next request must not drop the request.
func TestCoalescedForeignReplyKeepsTrailingRequest(t *testing.T) {
	f := synced()
	frames := f.Feed(mustHex(t, replyUnit4+reqUnit9))
	if len(frames) != 2 {
		t.Fatalf("got %d frames, want 2", len(frames))
	}
	last := frames[1]
	if last.Kind != KindRequest || last.Unit != 9 || !last.Eligible || last.FollowedByData {
		t.Errorf("trailing request = %+v", last)
	}
}

func TestEverySplitPointYieldsSameFrames(t *testing.T) {
	stream := mustHex(t, reqUnit1+replyUnit1+reqUnit9)
	for split := 1; split < len(stream); split++ {
		f := synced()
		frames := append(f.Feed(stream[:split]), f.Feed(stream[split:])...)
		if len(frames) != 3 {
			t.Fatalf("split %d: got %d frames", split, len(frames))
		}
		if frames[2].Unit != 9 || frames[2].Kind != KindRequest || !frames[2].Eligible {
			t.Errorf("split %d: last frame %+v", split, frames[2])
		}
	}
}

func TestByteAtATime(t *testing.T) {
	stream := mustHex(t, replyUnit4+reqUnit9+replyUnit1)
	f := synced()
	var frames []Frame
	for _, b := range stream {
		frames = append(frames, f.Feed([]byte{b})...)
	}
	if len(frames) != 3 {
		t.Fatalf("got %d frames, want 3", len(frames))
	}
}

func TestCorruptCRCNeverProducesEligibleRequest(t *testing.T) {
	bad := mustHex(t, reqUnit9)
	bad[4] ^= 0x01
	f := synced()
	frames := f.Feed(bad)
	for _, frame := range frames {
		if frame.Kind == KindRequest && frame.Eligible {
			t.Fatalf("corrupt input produced eligible request %x", frame.Raw)
		}
	}
	f.Idle()
	if f.Pending() != 0 || f.Stats().DiscardedBytes == 0 {
		t.Errorf("corrupt bytes not discarded: pending=%d stats=%+v", f.Pending(), f.Stats())
	}
}

// After garbage, the first frame found is not answered; the next one is.
func TestResyncAfterGarbage(t *testing.T) {
	f := synced()
	frames := f.Feed(append(mustHex(t, "ff13"), mustHex(t, reqUnit9+reqUnit1)...))
	if len(frames) != 2 {
		t.Fatalf("got %d frames", len(frames))
	}
	if frames[0].Eligible {
		t.Error("frame found by resync must not be eligible")
	}
	if !frames[1].Eligible {
		t.Error("frame after a resynced frame should be eligible")
	}
}

func TestStartupIsUnsyncedUntilSilence(t *testing.T) {
	f := NewFramer()
	if frames := f.Feed(mustHex(t, reqUnit9)); len(frames) != 1 || frames[0].Eligible {
		t.Fatalf("first frame before silence must be ineligible: %+v", frames)
	}
	f.Idle()
	if frames := f.Feed(mustHex(t, reqUnit9)); len(frames) != 1 || !frames[0].Eligible {
		t.Fatalf("frame after silence must be eligible: %+v", frames)
	}
}

func TestIdleDropsTruncatedFrame(t *testing.T) {
	f := synced()
	f.Feed(mustHex(t, reqUnit9)[:5])
	f.Idle()
	frames := f.Feed(mustHex(t, reqUnit1))
	if len(frames) != 1 || frames[0].Unit != 1 || !frames[0].Eligible {
		t.Fatalf("after idle: %+v", frames)
	}
	if f.Stats().PartialDiscards != 1 {
		t.Errorf("PartialDiscards = %d", f.Stats().PartialDiscards)
	}
}

func TestExceptionAndWriteFrames(t *testing.T) {
	exception := AppendCRC(mustHex(t, "0b8302"))
	writeMultiple := AppendCRC(mustHex(t, "0b10000000020400010002"))
	writeMultipleReply := AppendCRC(mustHex(t, "0b1000000002"))
	f := synced()
	stream := append(append(append([]byte{}, exception...), writeMultiple...), writeMultipleReply...)
	frames := f.Feed(stream)
	want := []Kind{KindException, KindRequest, KindResponse}
	if len(frames) != len(want) {
		t.Fatalf("got %d frames", len(frames))
	}
	for i, kind := range want {
		if frames[i].Kind != kind {
			t.Errorf("frame %d kind %v, want %v", i, frames[i].Kind, kind)
		}
	}
}

func TestImpossibleByteCountIsDiscarded(t *testing.T) {
	f := synced()
	// Unit 11 FC03 with byte count 0xFF: a reply would exceed 256 bytes.
	frames := f.Feed(append(mustHex(t, "0b03ff"), mustHex(t, reqUnit1)...))
	if len(frames) != 1 || frames[0].Unit != 1 {
		t.Fatalf("frames = %+v", frames)
	}
}

func TestEchoFilterRemovesOwnReplyOnly(t *testing.T) {
	now := time.Now()
	reply := mustHex(t, replyUnit1)
	var e EchoFilter
	e.Expect(reply, now, 100*time.Millisecond, true)
	out := e.Filter(append(append([]byte{}, reply...), mustHex(t, reqUnit9)...), now)
	if hex.EncodeToString(out) != reqUnit9 || e.Echoes() != 1 {
		t.Fatalf("out=%x echoes=%d", out, e.Echoes())
	}

	// No echo: a request sharing the reply's first two bytes passes intact.
	e.Expect(reply, now, 100*time.Millisecond, true)
	out = e.Filter(mustHex(t, reqUnit1)[:2], now)
	out = append(out, e.Filter(mustHex(t, reqUnit1)[2:], now)...)
	if hex.EncodeToString(out) != reqUnit1 {
		t.Fatalf("shared-prefix request mangled: %x", out)
	}

	// A held prefix is released once the window expires.
	e.Expect(reply, now, 10*time.Millisecond, true)
	if out := e.Filter(reply[:3], now); len(out) != 0 {
		t.Fatalf("prefix released early: %x", out)
	}
	if out := e.Expire(now.Add(20 * time.Millisecond)); !bytes.Equal(out, reply[:3]) {
		t.Fatalf("expired prefix = %x", out)
	}
}
